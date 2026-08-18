"""Post a journal proposal to Exact memorial journals."""
from __future__ import annotations

from typing import Any

from provider.exact import (
    ExactMemorialPostError,
    get_gl_account_guid_by_code,
    get_organization_connection,
    get_reporting_year_and_period,
    post_general_journal_entry,
)
from provider.router import resolve_organization_erp_provider


def post_journal_proposal_to_erp(context: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    organization_id = context["event"]["organization_id"]
    provider = resolve_organization_erp_provider(organization_id)
    if provider != "exact":
        raise RuntimeError(f"Unsupported ERP provider for journal post: {provider or 'none'}")

    token = get_organization_connection(organization_id)
    if not token.get("connected") or not token.get("access_token") or token.get("division") is None:
        raise RuntimeError("Exact Online is not connected for this organization")

    division = int(token["division"])
    access_token = str(token["access_token"])
    journal_code = context["organization_policy"]["memorial_journal_code"]

    debit_guid = get_gl_account_guid_by_code(organization_id, proposal["debit_account"])
    credit_guid = get_gl_account_guid_by_code(organization_id, proposal["credit_account"])
    if not debit_guid or not credit_guid:
        raise RuntimeError(
            f"Failed to resolve GL account GUIDs (debit={proposal['debit_account']}, credit={proposal['credit_account']})"
        )

    amount = float(proposal["amount"])
    if not (amount > 0):
        raise RuntimeError(f"Invalid journal amount: {proposal['amount']}")

    reporting = get_reporting_year_and_period(division, access_token, proposal["posting_date"])
    metadata = proposal.get("metadata") or {}
    supplier_account_guid = (
        (context.get("supplier_context") or {}).get("provider_supplier_id")
        or (metadata.get("provider_supplier_id") if isinstance(metadata.get("provider_supplier_id"), str) else "")
        or ""
    ).strip()
    account_guid = (
        supplier_account_guid
        if supplier_account_guid and not supplier_account_guid.startswith("name:")
        else None
    )

    po_ref = metadata.get("provider_purchase_order_id") or context["po_context"].get("provider_purchase_order_id") or "n/a"
    pinv_ref = (
        metadata.get("provider_purchase_invoice_id")
        or context["purchase_invoice_context"].get("provider_purchase_invoice_id")
        or "n/a"
    )
    line_notes = f"po:{po_ref};pinv:{pinv_ref}"

    try:
        posted = post_general_journal_entry(
            division=division,
            access_token=access_token,
            journal_code=journal_code,
            entry_date_iso=proposal["posting_date"],
            currency=proposal.get("currency") or context["accounting_period"].get("currency") or "EUR",
            reporting_year=reporting["reportingYear"],
            reporting_period=reporting["reportingPeriod"],
            lines=[
                {
                    "glAccountGuid": debit_guid,
                    "amount": amount,
                    "description": proposal["description"],
                    "notes": line_notes,
                    "accountGuid": account_guid,
                },
                {
                    "glAccountGuid": credit_guid,
                    "amount": -amount,
                    "description": proposal["description"],
                    "notes": line_notes,
                    "accountGuid": account_guid,
                },
            ],
        )
        return {
            "provider_entry_id": posted["id"],
            "entry_number": posted["entryNumber"],
        }
    except ExactMemorialPostError as exc:
        if exc.closed_period:
            raise RuntimeError(
                f"Exact rejected journal post — accounting period is closed ({exc.status})"
            ) from exc
        raise
