"""Context loaders: org settings, period, PO/PINV, journals, history."""
from __future__ import annotations

import logging
import re
from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Any, Optional

from r2r import supabase_rest
from r2r.accounting_agent.constants import ACCOUNTING_AGENT_NAME
from r2r.accounting_agent.gl_codes import pick_primary_gl_account_code_from_entry_lines
from r2r.config import (
    DEFAULT_ACCOUNTING_MAX_THRESHOLD,
    DEFAULT_ACCOUNTING_MIN_THRESHOLD,
    DEFAULT_GL_ACCOUNTS,
    DEFAULT_MONTH_END_OFFSET_DAYS,
    DEFAULT_MONTH_START_RUN_DAYS,
)
from provider.router import resolve_organization_erp_provider
from provider.exact import (
    PO_STATUS_CANCELLED,
    PO_STATUS_COMPLETE,
    get_financial_period_for_date,
    get_gl_account_guid_by_code,
    get_gl_accounts,
    get_organization_connection,
    get_purchase_entry,
    get_purchase_order,
    list_journal_entry_lines,
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
        token = get_organization_connection(organization_id)
        if token.get("connected") and token.get("access_token") and token.get("division") is not None:
            erp_period = get_financial_period_for_date(
                int(token["division"]),
                str(token["access_token"]),
                date_iso,
            )
            if erp_period:
                year = int(erp_period["financialYear"])
                period = int(erp_period["financialPeriod"])
                return {
                    "year": year,
                    "period": period,
                    "is_open": True,
                    "currency": "EUR",
                    "source": "erp",
                    "previous_period": (
                        {"year": year - 1, "period": 12}
                        if period <= 1
                        else {"year": year, "period": period - 1}
                    ),
                }
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


def map_po_close_flags(erp_po: dict[str, Any]) -> dict[str, Any]:
    receipt_status = erp_po.get("ReceiptStatus")
    invoice_status = erp_po.get("InvoiceStatus")
    try:
        receipt_status = int(receipt_status)
    except (TypeError, ValueError):
        receipt_status = None
    try:
        invoice_status = int(invoice_status)
    except (TypeError, ValueError):
        invoice_status = None
    amount = erp_po.get("AmountDC") if isinstance(erp_po.get("AmountDC"), (int, float)) else erp_po.get("AmountFC")
    return {
        "is_delivered": receipt_status == PO_STATUS_COMPLETE,
        "is_closed": receipt_status == PO_STATUS_CANCELLED or invoice_status == PO_STATUS_CANCELLED,
        "invoice_received": invoice_status == PO_STATUS_COMPLETE,
        "erp_receipt_status": receipt_status,
        "delivery_date": (
            str(erp_po["ReceiptDate"]).split("T")[0]
            if isinstance(erp_po.get("ReceiptDate"), str)
            else None
        ),
        "amount": amount if isinstance(amount, (int, float)) else None,
        "supplier": erp_po.get("SupplierName") if isinstance(erp_po.get("SupplierName"), str) else None,
        "cost_center": erp_po.get("CostCenter") if isinstance(erp_po.get("CostCenter"), str) else None,
        "order_number": erp_po.get("OrderNumber") if isinstance(erp_po.get("OrderNumber"), (int, float)) else None,
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
    provider = resolve_organization_erp_provider(event["organization_id"])
    if not provider:
        return {**empty, **({"gl_account_code": gl_account_code} if gl_account_code else {})}
    try:
        erp_po = get_purchase_order(
            event["organization_id"],
            provider_po_id,
            select="PurchaseOrderID,OrderNumber,ReceiptDate,ReceiptStatus,InvoiceStatus,AmountDC,AmountFC,Currency,SupplierName,CostCenter",
        )
        if not erp_po:
            return {**empty, **({"gl_account_code": gl_account_code} if gl_account_code else {})}
        flags = map_po_close_flags(erp_po)
        return {
            "provider_purchase_order_id": provider_po_id,
            "order_number": flags["order_number"],
            "is_delivered": flags["is_delivered"],
            "is_closed": flags["is_closed"],
            "delivery_date": flags["delivery_date"],
            "erp_receipt_status": flags["erp_receipt_status"],
            "erp_synced": True,
            "invoice_received": flags["invoice_received"],
            "amount": flags["amount"],
            "supplier": flags["supplier"],
            "cost_center": flags["cost_center"],
            **({"gl_account_code": gl_account_code} if gl_account_code else {}),
        }
    except Exception as exc:
        logger.warning("[accounting-agent] ERP PO fetch failed: %s", exc)
        return {**empty, **({"gl_account_code": gl_account_code} if gl_account_code else {})}


def infer_service_period_from_text(text: str) -> dict[str, str]:
    range_match = re.search(
        r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\s*(?:to|tot|-|–|—)\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})",
        text,
        re.I,
    ) or re.search(
        r"(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})\s*(?:to|tot|-|–|—)\s*(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})",
        text,
        re.I,
    )
    if not range_match:
        return {}

    def _normalize(value: str) -> str:
        return value.replace("/", "-").replace(".", "-")

    return {"start": _normalize(range_match.group(1)), "end": _normalize(range_match.group(2))}


def map_exact_purchase_entry(provider_invoice_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    description = entry.get("Description") if isinstance(entry.get("Description"), str) else None
    your_ref = entry.get("YourRef") if isinstance(entry.get("YourRef"), str) else ""
    text = " ".join(p for p in [description, your_ref] if p)
    inferred = infer_service_period_from_text(text)
    if (
        not inferred.get("start")
        and isinstance(entry.get("EntryDate"), str)
        and re.search(
            r"\b(prepaid|vooruitbetaald|annual|jaarlijks|yearly|subscription|abonnement|licen[cs]e)\b",
            text,
            re.I,
        )
    ):
        start = entry["EntryDate"].split("T")[0]
        start_date = datetime.fromisoformat(start).date()
        month = start_date.month + 11
        year = start_date.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        day = min(start_date.day, monthrange(year, month)[1])
        inferred = {"start": start, "end": date(year, month, day).isoformat()}
    gl_account_code = pick_primary_gl_account_code_from_entry_lines(entry)
    amount = entry.get("AmountFC") if entry.get("AmountFC") is not None else entry.get("AmountDC")
    try:
        amount_n = float(amount)
    except (TypeError, ValueError):
        amount_n = None
    return {
        "provider_purchase_invoice_id": provider_invoice_id,
        "invoice_date": entry["EntryDate"].split("T")[0] if isinstance(entry.get("EntryDate"), str) else None,
        "service_period_start": inferred.get("start"),
        "service_period_end": inferred.get("end"),
        "amount": amount_n or None,
        "description": description,
        "currency": entry.get("Currency") if isinstance(entry.get("Currency"), str) else "EUR",
        **({"gl_account_code": gl_account_code} if gl_account_code else {}),
    }


def get_purchase_invoice_context(event: dict[str, Any]) -> dict[str, Any]:
    provider_invoice_id = str((event.get("payload") or {}).get("provider_purchase_invoice_id") or "").strip()
    if not provider_invoice_id:
        return {}
    if not resolve_organization_erp_provider(event["organization_id"]):
        return {}
    try:
        entry = get_purchase_entry(event["organization_id"], provider_invoice_id)
        if not entry:
            return {}
        return map_exact_purchase_entry(provider_invoice_id, entry)
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


def _line_matches_refs(line: dict[str, Any], refs: list[str]) -> bool:
    if not refs:
        return True
    hay = f"{line.get('description') or ''} {line.get('notes') or ''}".lower()
    return any(
        rid and (f"pinv:{rid}" in hay or f"po:{rid}" in hay or rid in hay)
        for rid in (r.strip().lower() for r in refs)
    )


def load_existing_journals_for_supplier(
    *,
    organization_id: str,
    provider_supplier_id: str,
    start_date: str,
    end_date: str,
    gl_accounts: dict[str, str],
    document_refs: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    supplier_id = provider_supplier_id.strip()
    if not supplier_id or supplier_id.startswith("name:"):
        return []
    token = get_organization_connection(organization_id)
    if not token.get("connected") or not token.get("access_token") or token.get("division") is None:
        return []
    codes = [
        gl_accounts["cost_gl_account_code"],
        gl_accounts["accrued_cost_gl_account_code"],
        gl_accounts["prepaid_gl_account_code"],
    ]
    guids = [g for g in (get_gl_account_guid_by_code(organization_id, code) for code in codes) if g]
    if not guids:
        return []
    common = {
        "division": int(token["division"]),
        "access_token": str(token["access_token"]),
        "gl_account_guids": guids,
        "start_date": start_date,
        "end_date": end_date,
    }
    by_account = list_journal_entry_lines(**common, account_guid=supplier_id)
    if by_account:
        return _with_roles(by_account, gl_accounts)
    refs = [r.strip() for r in (document_refs or []) if r and r.strip()]
    if not refs:
        return []
    by_gl = list_journal_entry_lines(**common, top=200)
    return _with_roles([line for line in by_gl if _line_matches_refs(line, refs)], gl_accounts)


def list_supplier_ids_with_close_gl_activity(
    *,
    organization_id: str,
    start_date: str,
    end_date: str,
    gl_accounts: dict[str, str],
) -> list[str]:
    token = get_organization_connection(organization_id)
    if not token.get("connected") or not token.get("access_token") or token.get("division") is None:
        return []
    codes = [
        gl_accounts["cost_gl_account_code"],
        gl_accounts["accrued_cost_gl_account_code"],
        gl_accounts["prepaid_gl_account_code"],
    ]
    guids = [g for g in (get_gl_account_guid_by_code(organization_id, code) for code in codes) if g]
    if not guids:
        return []
    lines = list_journal_entry_lines(
        division=int(token["division"]),
        access_token=str(token["access_token"]),
        gl_account_guids=guids,
        start_date=start_date,
        end_date=end_date,
        top=500,
    )
    ids = {line["account_guid"].strip() for line in lines if (line.get("account_guid") or "").strip()}
    return list(ids)


def load_available_gl_accounts_for_agent(organization_id: str, defaults: dict[str, str]) -> list[dict[str, Any]]:
    def default_only() -> list[dict[str, Any]]:
        seen = set()
        out = []
        for raw in (
            defaults["cost_gl_account_code"],
            defaults["accrued_cost_gl_account_code"],
            defaults["prepaid_gl_account_code"],
        ):
            code = raw.strip()
            if not code or code in seen:
                continue
            seen.add(code)
            out.append({"code": code, "description": code})
        return out

    token = get_organization_connection(organization_id)
    if not token.get("connected") or not token.get("access_token") or token.get("division") is None:
        return default_only()
    try:
        accounts = get_gl_accounts(organization_id, str(token["access_token"]), int(token["division"]))
        default_codes = {
            defaults["cost_gl_account_code"].strip(),
            defaults["accrued_cost_gl_account_code"].strip(),
            defaults["prepaid_gl_account_code"].strip(),
        }
        default_codes.discard("")
        by_code: dict[str, dict[str, Any]] = {}
        for acc in accounts:
            code = (acc.get("code") or "").strip()
            if not code:
                continue
            is_pnl = str(acc.get("balanceType") or "").upper() == "W"
            if not is_pnl and code not in default_codes:
                continue
            item = {"code": code, "description": (acc.get("description") or "").strip() or code}
            if acc.get("typeDescription"):
                item["typeDescription"] = str(acc["typeDescription"]).strip()
            by_code[code] = item
        for code in default_codes:
            by_code.setdefault(code, {"code": code, "description": code})
        return sorted(by_code.values(), key=lambda a: a["code"])
    except Exception as exc:
        logger.warning("[accounting-agent] loadAvailableGlAccountsForAgent failed: %s", exc)
        return default_only()
