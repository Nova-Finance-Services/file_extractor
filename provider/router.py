"""ERP-agnostic routing.

Agents import from `provider.router` only. Exact field names, OData, division tokens,
and status codes stay in `provider.exact`. Add a branch here when onboarding another ERP.
"""
from __future__ import annotations

from typing import Any, Optional

from provider.errors import ErpUnsupportedError
from r2r import supabase_rest

ErpProviderName = str


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


def _provider(organization_id: str) -> Optional[ErpProviderName]:
    return resolve_organization_erp_provider(organization_id)


def _require(organization_id: str, action: str) -> ErpProviderName:
    name = _provider(organization_id)
    if name == "exact":
        return name
    if not name:
        raise ErpUnsupportedError(f"No ERP connection for organization {organization_id}")
    raise ErpUnsupportedError(f"Unsupported ERP provider for {action}: {name}")


def erp_list_supplier_document_batches(organization_id: str, window: dict[str, str]) -> list[dict[str, Any]]:
    if not _provider(organization_id):
        return []
    if _require(organization_id, "list_supplier_document_batches") == "exact":
        from provider.exact.close import list_supplier_document_batches
        return list_supplier_document_batches(organization_id, window)
    return []


def erp_get_purchase_order(organization_id: str, provider_po_id: str) -> Optional[dict[str, Any]]:
    if _require(organization_id, "get_purchase_order") == "exact":
        from provider.exact.close import get_purchase_order_for_close
        return get_purchase_order_for_close(organization_id, provider_po_id)
    return None


def erp_get_purchase_invoice(organization_id: str, provider_pinv_id: str) -> Optional[dict[str, Any]]:
    if _require(organization_id, "get_purchase_invoice") == "exact":
        from provider.exact.close import get_purchase_invoice_for_close
        return get_purchase_invoice_for_close(organization_id, provider_pinv_id)
    return None


def erp_get_accounting_period(organization_id: str, date_iso: str) -> Optional[dict[str, Any]]:
    if not _provider(organization_id):
        return None
    if _require(organization_id, "get_accounting_period") == "exact":
        from provider.exact.close import get_accounting_period
        return get_accounting_period(organization_id, date_iso)
    return None


def erp_list_journal_lines(
    organization_id: str,
    *,
    start_date: str,
    end_date: str,
    gl_account_codes: list[str],
    provider_supplier_id: Optional[str] = None,
    document_refs: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    if not _provider(organization_id):
        return []
    if _require(organization_id, "list_journal_lines") == "exact":
        from provider.exact.close import list_close_journal_lines
        return list_close_journal_lines(
            organization_id,
            start_date=start_date,
            end_date=end_date,
            gl_account_codes=gl_account_codes,
            provider_supplier_id=provider_supplier_id,
            document_refs=document_refs,
        )
    return []


def erp_list_supplier_ids_with_gl_activity(
    organization_id: str,
    *,
    start_date: str,
    end_date: str,
    gl_account_codes: list[str],
) -> list[str]:
    if not _provider(organization_id):
        return []
    if _require(organization_id, "list_supplier_ids_with_gl_activity") == "exact":
        from provider.exact.close import list_supplier_ids_with_gl_activity
        return list_supplier_ids_with_gl_activity(
            organization_id,
            start_date=start_date,
            end_date=end_date,
            gl_account_codes=gl_account_codes,
        )
    return []


def erp_list_gl_accounts(organization_id: str, default_codes: list[str]) -> list[dict[str, Any]]:
    if not _provider(organization_id):
        return [{"code": c, "description": c} for c in default_codes if c]
    if _require(organization_id, "list_gl_accounts") == "exact":
        from provider.exact.close import list_gl_accounts_for_agent
        return list_gl_accounts_for_agent(organization_id, default_codes)
    return [{"code": c, "description": c} for c in default_codes if c]


def erp_post_memorial_journal(
    organization_id: str,
    *,
    journal_code: str,
    proposal: dict[str, Any],
    provider_supplier_id: Optional[str] = None,
    provider_purchase_order_id: Optional[str] = None,
    provider_purchase_invoice_id: Optional[str] = None,
) -> dict[str, Any]:
    if _require(organization_id, "post_memorial_journal") == "exact":
        from provider.exact.close import post_memorial_journal
        return post_memorial_journal(
            organization_id,
            journal_code=journal_code,
            proposal=proposal,
            provider_supplier_id=provider_supplier_id,
            provider_purchase_order_id=provider_purchase_order_id,
            provider_purchase_invoice_id=provider_purchase_invoice_id,
        )
    raise ErpUnsupportedError("Unsupported ERP provider for post_memorial_journal")
