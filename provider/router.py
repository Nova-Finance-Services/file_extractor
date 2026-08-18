"""ERP-agnostic routing (mirrors Backend _shared/provider/close-candidates.ts).

Agent / chatbot code should import from `provider` or `provider.router`, not from
Exact modules directly. Add a new branch here when onboarding another ERP.
"""
from __future__ import annotations

from typing import Any, Optional

from provider.exact import (
    ExactMemorialPostError,
    PO_STATUS_CANCELLED,
    PO_STATUS_COMPLETE,
    get_financial_period_for_date,
    get_gl_account_guid_by_code,
    get_gl_accounts,
    get_organization_connection,
    get_purchase_entries,
    get_purchase_entry,
    get_purchase_order,
    get_purchase_orders,
    get_reporting_year_and_period,
    list_journal_entry_lines,
    normalize_exact_date,
    post_general_journal_entry,
)
from r2r import supabase_rest

ErpProviderName = str  # "exact" today; add "twinfield" etc. later


def resolve_organization_erp_provider(organization_id: str) -> Optional[ErpProviderName]:
    """Return which ERP the org is connected to, or None."""
    try:
        row = supabase_rest.select(
            "connections",
            columns="id",
            filters={"organization_id": organization_id},
            maybe_single=True,
        )
    except Exception:
        return None
    return "exact" if row else None


def _require_provider(organization_id: str) -> ErpProviderName:
    provider = resolve_organization_erp_provider(organization_id)
    if not provider:
        raise RuntimeError(f"No ERP connection for organization {organization_id}")
    return provider


def _unsupported(provider: str, action: str) -> None:
    raise RuntimeError(f"Unsupported ERP provider for {action}: {provider}")


def erp_get_connection(organization_id: str) -> dict[str, Any]:
    provider = resolve_organization_erp_provider(organization_id)
    if provider == "exact":
        return get_organization_connection(organization_id)
    if not provider:
        return {"connected": False, "error": f"No connection found for organization {organization_id}"}
    _unsupported(provider, "get_connection")
    return {"connected": False, "error": "unsupported"}


def erp_get_purchase_order(organization_id: str, purchase_order_id: str, select: Optional[str] = None):
    if _require_provider(organization_id) == "exact":
        return get_purchase_order(organization_id, purchase_order_id, select=select)
    _unsupported("unknown", "get_purchase_order")


def erp_get_purchase_orders(organization_id: str, **kwargs):
    if _require_provider(organization_id) == "exact":
        return get_purchase_orders(organization_id, **kwargs)
    _unsupported("unknown", "get_purchase_orders")


def erp_get_purchase_entry(organization_id: str, entry_id: str):
    if _require_provider(organization_id) == "exact":
        return get_purchase_entry(organization_id, entry_id)
    _unsupported("unknown", "get_purchase_entry")


def erp_get_purchase_entries(organization_id: str, **kwargs):
    if _require_provider(organization_id) == "exact":
        return get_purchase_entries(organization_id, **kwargs)
    _unsupported("unknown", "get_purchase_entries")


def erp_get_gl_accounts(organization_id: str, access_token: str, division: int):
    if _require_provider(organization_id) == "exact":
        return get_gl_accounts(organization_id, access_token, division)
    _unsupported("unknown", "get_gl_accounts")


def erp_get_gl_account_guid_by_code(organization_id: str, code_or_guid: str):
    if _require_provider(organization_id) == "exact":
        return get_gl_account_guid_by_code(organization_id, code_or_guid)
    _unsupported("unknown", "get_gl_account_guid_by_code")


def erp_list_journal_entry_lines(**kwargs):
    organization_id = kwargs.pop("organization_id", None)
    if organization_id:
        provider = _require_provider(organization_id)
        if provider != "exact":
            _unsupported(provider, "list_journal_entry_lines")
    return list_journal_entry_lines(**kwargs)


def erp_post_journal_entry(organization_id: str, **kwargs):
    if _require_provider(organization_id) == "exact":
        return post_general_journal_entry(**kwargs)
    _unsupported("unknown", "post_journal_entry")


def erp_get_financial_period_for_date(organization_id: str, division: int, access_token: str, date_iso: str):
    if _require_provider(organization_id) == "exact":
        return get_financial_period_for_date(division, access_token, date_iso)
    _unsupported("unknown", "get_financial_period")


def erp_get_reporting_year_and_period(organization_id: str, division: int, access_token: str, date_iso: str):
    if _require_provider(organization_id) == "exact":
        return get_reporting_year_and_period(division, access_token, date_iso)
    _unsupported("unknown", "get_reporting_year_and_period")


# Re-export Exact-only helpers that callers still need until a second ERP exists.
__all__ = [
    "ErpProviderName",
    "ExactMemorialPostError",
    "PO_STATUS_CANCELLED",
    "PO_STATUS_COMPLETE",
    "erp_get_connection",
    "erp_get_financial_period_for_date",
    "erp_get_gl_account_guid_by_code",
    "erp_get_gl_accounts",
    "erp_get_purchase_entries",
    "erp_get_purchase_entry",
    "erp_get_purchase_order",
    "erp_get_purchase_orders",
    "erp_get_reporting_year_and_period",
    "erp_list_journal_entry_lines",
    "erp_post_journal_entry",
    "normalize_exact_date",
    "resolve_organization_erp_provider",
]
