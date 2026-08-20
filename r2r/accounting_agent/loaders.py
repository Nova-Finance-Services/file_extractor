"""Context loaders: org settings, period, PO/PINV, journals, history."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from r2r import supabase_rest
from r2r.accounting_agent.constants import ACCOUNTING_AGENT_NAME
from r2r.config import (
    DEFAULT_ACCOUNTING_MAX_THRESHOLD,
    DEFAULT_ACCOUNTING_MIN_THRESHOLD,
    DEFAULT_GL_ACCOUNTS,
    DEFAULT_MONTH_END_OFFSET_DAYS,
    DEFAULT_MONTH_START_RUN_DAYS,
)
from provider.router import (
    erp_get_accounting_period,
    erp_get_purchase_invoice,
    erp_get_purchase_order,
    erp_list_gl_accounts,
    erp_list_journal_lines,
    erp_list_supplier_ids_with_gl_activity,
)

logger = logging.getLogger(__name__)


def _code_or_default(value: Any, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _threshold_or_default(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if number >= 0 else fallback


def get_organization_context(organization_id: str) -> dict[str, Any]:
    p2p = None
    o2c = None
    try:
        p2p = supabase_rest.select(
            "p2p_settings",
            columns="*",
            filters={"organization_id": organization_id},
            maybe_single=True,
        )
    except Exception as exc:
        logger.warning("p2p_settings load failed: %s", exc)
    try:
        o2c = supabase_rest.select(
            "o2c_settings",
            columns="*",
            filters={"organization_id": organization_id},
            maybe_single=True,
        )
    except Exception as exc:
        logger.warning("o2c_settings load failed: %s", exc)

    min_threshold = _threshold_or_default(
        (p2p or {}).get("accounting_min_threshold"),
        DEFAULT_ACCOUNTING_MIN_THRESHOLD,
    )
    max_threshold = _threshold_or_default(
        (p2p or {}).get("accounting_max_threshold"),
        DEFAULT_ACCOUNTING_MAX_THRESHOLD,
    )
    memorial = ((o2c or {}).get("memorial_journal_code") or "").strip().upper() or "90"
    return {
        "materiality_threshold": min_threshold,
        "requires_approval_above": max(max_threshold, min_threshold),
        "close_calendar_name": "standard_month_end",
        "working_day_rule": "calendar_days",
        "month_start_run_days": (p2p or {}).get("month_start_run_days")
        if isinstance((p2p or {}).get("month_start_run_days"), list)
        else DEFAULT_MONTH_START_RUN_DAYS,
        "month_end_offset_days": (p2p or {}).get("month_end_offset_days")
        if isinstance((p2p or {}).get("month_end_offset_days"), list)
        else DEFAULT_MONTH_END_OFFSET_DAYS,
        "memorial_journal_code": memorial,
        "gl_accounts": {
            "cost_gl_account_code": _code_or_default(
                (p2p or {}).get("cost_gl_account_code"),
                DEFAULT_GL_ACCOUNTS["cost_gl_account_code"],
            ),
            "accrued_cost_gl_account_code": _code_or_default(
                (p2p or {}).get("accrued_cost_gl_account_code"),
                DEFAULT_GL_ACCOUNTS["accrued_cost_gl_account_code"],
            ),
            "prepaid_gl_account_code": _code_or_default(
                (p2p or {}).get("prepaid_gl_account_code"),
                DEFAULT_GL_ACCOUNTS["prepaid_gl_account_code"],
            ),
        },
    }


def get_accounting_period_context(organization_id: str, occurred_at: str) -> dict[str, Any]:
    period_date = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    if period_date.tzinfo is None:
        period_date = period_date.replace(tzinfo=timezone.utc)
    utc = period_date.astimezone(timezone.utc)
    date_iso = utc.date().isoformat()
    try:
        erp_period = erp_get_accounting_period(organization_id, date_iso)
        if erp_period:
            return erp_period
    except Exception as exc:
        logger.warning("[accounting-period-context] ERP period lookup failed, using calendar fallback: %s", exc)

    utc = period_date.astimezone(timezone.utc) if period_date.tzinfo else period_date.replace(tzinfo=timezone.utc)
    year = utc.year
    period = utc.month
    return {
        "year": year,
        "period": period,
        "is_open": False,
        "currency": "EUR",
        "source": "calendar_fallback",
        "previous_period": {"year": year - 1, "period": 12} if period == 1 else {"year": year, "period": period - 1},
    }


def load_nova_po_gl_account_codes(organization_id: str, provider_ids: list[str]) -> dict[str, str]:
    ids = list({pid.strip() for pid in provider_ids if pid and pid.strip()})
    if not ids:
        return {}
    try:
        rows = supabase_rest.select(
            "purchase_orders",
            columns="provider_purchase_order_id,glaccount_code",
            filters={"organization_id": organization_id},
            in_filters={"provider_purchase_order_id": ids},
        ) or []
    except Exception as exc:
        logger.warning("[accounting-agent] loadNovaPoGlAccountCodes failed: %s", exc)
        return {}
    out: dict[str, str] = {}
    for row in rows:
        provider_id = str(row.get("provider_purchase_order_id") or "").strip()
        code = str(row.get("glaccount_code") or "").strip()
        if provider_id and code:
            out[provider_id] = code
    return out


def get_historical_context(event: dict[str, Any]) -> dict[str, Any]:
    try:
        rows = supabase_rest.select(
            "agent_memory",
            columns="decision_types",
            filters={
                "agent_name": ACCOUNTING_AGENT_NAME,
                "organization_id": event["organization_id"],
            },
            order="created_at.desc",
            limit=10,
        ) or []
    except Exception as exc:
        logger.warning("historical context failed: %s", exc)
        return {"similar_decisions_count": 0}
    if not rows:
        return {"similar_decisions_count": 0}
    last_types = rows[0].get("decision_types") or []
    return {
        "similar_decisions_count": len(rows),
        "last_decision": last_types[0] if last_types else None,
    }


def get_po_context(event: dict[str, Any]) -> dict[str, Any]:
    empty = {
        "is_delivered": False,
        "is_closed": False,
        "invoice_received": False,
        "erp_synced": False,
    }
    provider_po_id = str((event.get("payload") or {}).get("provider_purchase_order_id") or "").strip()
    if not provider_po_id:
        return empty
    nova_gl = load_nova_po_gl_account_codes(event["organization_id"], [provider_po_id])
    gl_account_code = nova_gl.get(provider_po_id)
    try:
        mapped = erp_get_purchase_order(event["organization_id"], provider_po_id)
        if not mapped:
            return {**empty, **({"gl_account_code": gl_account_code} if gl_account_code else {})}
        return {
            **mapped,
            "provider_purchase_order_id": provider_po_id,
            "erp_synced": True,
            **({"gl_account_code": gl_account_code} if gl_account_code else {}),
        }
    except Exception as exc:
        logger.warning("[accounting-agent] ERP PO fetch failed: %s", exc)
        return {**empty, **({"gl_account_code": gl_account_code} if gl_account_code else {})}


def get_purchase_invoice_context(event: dict[str, Any]) -> dict[str, Any]:
    provider_invoice_id = str((event.get("payload") or {}).get("provider_purchase_invoice_id") or "").strip()
    if not provider_invoice_id:
        return {}
    try:
        return erp_get_purchase_invoice(event["organization_id"], provider_invoice_id) or {}
    except Exception as exc:
        logger.warning("[accounting-agent] ERP purchase entry fetch failed: %s", exc)
        return {}


def _role_for_code(code: Optional[str], gl: dict[str, str]) -> str:
    if not code:
        return "other"
    if code == gl["cost_gl_account_code"]:
        return "cost"
    if code == gl["accrued_cost_gl_account_code"]:
        return "accrued_cost"
    if code == gl["prepaid_gl_account_code"]:
        return "prepaid"
    return "other"


def _with_roles(lines: list[dict[str, Any]], gl: dict[str, str]) -> list[dict[str, Any]]:
    return [{**line, "role": _role_for_code(line.get("gl_account_code"), gl)} for line in lines]


def _gl_codes(gl_accounts: dict[str, str]) -> list[str]:
    return [
        gl_accounts["cost_gl_account_code"],
        gl_accounts["accrued_cost_gl_account_code"],
        gl_accounts["prepaid_gl_account_code"],
    ]


def load_existing_journals_for_supplier(
    *,
    organization_id: str,
    provider_supplier_id: str,
    start_date: str,
    end_date: str,
    gl_accounts: dict[str, str],
    document_refs: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    lines = erp_list_journal_lines(
        organization_id,
        start_date=start_date,
        end_date=end_date,
        gl_account_codes=_gl_codes(gl_accounts),
        provider_supplier_id=provider_supplier_id,
        document_refs=document_refs,
    )
    return _with_roles(lines, gl_accounts)


def list_supplier_ids_with_close_gl_activity(
    *,
    organization_id: str,
    start_date: str,
    end_date: str,
    gl_accounts: dict[str, str],
) -> list[str]:
    return erp_list_supplier_ids_with_gl_activity(
        organization_id,
        start_date=start_date,
        end_date=end_date,
        gl_account_codes=_gl_codes(gl_accounts),
    )


def load_available_gl_accounts_for_agent(organization_id: str, defaults: dict[str, str]) -> list[dict[str, Any]]:
    return erp_list_gl_accounts(organization_id, _gl_codes(defaults))
