"""Post a journal proposal through the ERP adapter."""
from __future__ import annotations

from typing import Any

from provider.router import erp_post_memorial_journal


def post_journal_proposal_to_erp(context: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    metadata = proposal.get("metadata") or {}
    supplier_id = (
        (context.get("supplier_context") or {}).get("provider_supplier_id")
        or (metadata.get("provider_supplier_id") if isinstance(metadata.get("provider_supplier_id"), str) else "")
        or ""
    ).strip()
    if not proposal.get("currency"):
        proposal = {
            **proposal,
            "currency": context["accounting_period"].get("currency") or "EUR",
        }
    return erp_post_memorial_journal(
        context["event"]["organization_id"],
        journal_code=context["organization_policy"]["memorial_journal_code"],
        proposal=proposal,
        provider_supplier_id=supplier_id or None,
        provider_purchase_order_id=(
            metadata.get("provider_purchase_order_id")
            or context["po_context"].get("provider_purchase_order_id")
        ),
        provider_purchase_invoice_id=(
            metadata.get("provider_purchase_invoice_id")
            or context["purchase_invoice_context"].get("provider_purchase_invoice_id")
        ),
    )
