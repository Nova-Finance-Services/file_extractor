"""Supplier discovery and AccountingAgentContext assembly."""
from __future__ import annotations

from typing import Any, Optional

from r2r.accounting_agent.loaders import (
    get_accounting_period_context,
    get_historical_context,
    get_organization_context,
    get_po_context,
    get_purchase_invoice_context,
    list_supplier_ids_with_close_gl_activity,
    load_available_gl_accounts_for_agent,
    load_existing_journals_for_supplier,
    load_nova_po_gl_account_codes,
)
from r2r.accounting_agent.period_window import build_close_period_window
from r2r.jobs import resolve_forced_supplier_ids
from r2r.accounting_agent.policies import get_policy_knowledge_context
from provider.router import erp_list_supplier_document_batches


def event_has_document_payload(payload: Optional[dict[str, Any]]) -> bool:
    payload = payload or {}
    return bool(payload.get("provider_purchase_order_id") or payload.get("provider_purchase_invoice_id"))


def event_has_supplier_payload(payload: Optional[dict[str, Any]]) -> bool:
    return bool(resolve_forced_supplier_ids(payload))


def _abs_amount(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return abs(number)


def _empty_po_context() -> dict[str, Any]:
    return {
        "is_delivered": False,
        "is_closed": False,
        "invoice_received": False,
        "erp_synced": False,
    }


def list_supplier_close_batches(
    organization_id: str,
    event_type: str,
    window: dict[str, str],
) -> list[dict[str, Any]]:
    if event_type not in {"month_start", "month_end"}:
        return []
    doc_batches = erp_list_supplier_document_batches(organization_id, window)
    organization_policy = get_organization_context(organization_id)
    journal_ids = list_supplier_ids_with_close_gl_activity(
        organization_id=organization_id,
        start_date=window["start_date"],
        end_date=window["end_date"],
        gl_accounts=organization_policy["gl_accounts"],
    )
    journal_set = set(journal_ids)
    by_supplier = {batch["provider_supplier_id"]: batch for batch in doc_batches}
    for supplier_id in journal_ids:
        if supplier_id in by_supplier:
            continue
        by_supplier[supplier_id] = {
            "provider_supplier_id": supplier_id,
            "purchase_orders": [],
            "purchase_invoices": [],
        }
    return [
        batch
        for batch in by_supplier.values()
        if batch["purchase_orders"] or batch["purchase_invoices"] or batch["provider_supplier_id"] in journal_set
    ]


def build_context(event: dict[str, Any]) -> dict[str, Any]:
    accounting_period = get_accounting_period_context(event["organization_id"], event["occurred_at"])
    organization_policy = get_organization_context(event["organization_id"])
    po_context = get_po_context(event)
    purchase_invoice_context = get_purchase_invoice_context(event)
    historical_context = get_historical_context(event)
    available_gl_accounts = load_available_gl_accounts_for_agent(
        event["organization_id"],
        organization_policy["gl_accounts"],
    )
    policy_knowledge = get_policy_knowledge_context()
    period_window = build_close_period_window({
        "year": accounting_period["year"],
        "period": accounting_period["period"],
    })
    current_period_key = f"{accounting_period['year']}-{str(accounting_period['period']).zfill(2)}"
    supplier_id = str((event.get("payload") or {}).get("provider_supplier_id") or "").strip()
    document_refs = [
        po_context.get("provider_purchase_order_id"),
        purchase_invoice_context.get("provider_purchase_invoice_id"),
    ]
    document_refs = [rid for rid in document_refs if rid]
    existing_journals = (
        load_existing_journals_for_supplier(
            organization_id=event["organization_id"],
            provider_supplier_id=supplier_id,
            start_date=period_window["start_date"],
            end_date=period_window["end_date"],
            gl_accounts=organization_policy["gl_accounts"],
            document_refs=document_refs,
        )
        if supplier_id
        else []
    )
    has_po = bool(po_context.get("provider_purchase_order_id"))
    has_invoice = bool(purchase_invoice_context.get("provider_purchase_invoice_id"))
    missing_fields = []
    if not has_po and not has_invoice:
        missing_fields.append("provider_purchase_order_id_or_provider_purchase_invoice_id")
    if not po_context.get("amount") and not purchase_invoice_context.get("amount"):
        missing_fields.append("amount")
    derived_amount = _abs_amount(po_context.get("amount") or purchase_invoice_context.get("amount") or 0)
    context: dict[str, Any] = {
        "event": event,
        "accounting_period": accounting_period,
        "period_window": period_window,
        "organization_policy": organization_policy,
        "available_gl_accounts": available_gl_accounts,
        "po_context": po_context,
        "purchase_invoice_context": purchase_invoice_context,
        "existing_journals": existing_journals,
        "history": historical_context,
        "data_quality": {
            "missing_fields": missing_fields,
            "is_complete": len(missing_fields) == 0,
        },
        "derived_metrics": {
            "amount": derived_amount,
            "current_period_key": current_period_key,
            "po_count": 1 if has_po else 0,
            "pinv_count": 1 if has_invoice else 0,
        },
        "policy_knowledge": policy_knowledge,
    }
    if supplier_id:
        context["supplier_context"] = {
            "provider_supplier_id": supplier_id,
            "supplier_name": str((event.get("payload") or {}).get("supplier_name"))
            if (event.get("payload") or {}).get("supplier_name")
            else None,
            "purchase_orders": [],
            "purchase_invoices": [],
        }
    return context


def build_supplier_close_context(
    event: dict[str, Any],
    batch: dict[str, Any],
    period_window: dict[str, Any],
) -> dict[str, Any]:
    accounting_period = get_accounting_period_context(event["organization_id"], event["occurred_at"])
    organization_policy = get_organization_context(event["organization_id"])
    historical_context = get_historical_context(event)
    available_gl_accounts = load_available_gl_accounts_for_agent(
        event["organization_id"],
        organization_policy["gl_accounts"],
    )
    policy_knowledge = get_policy_knowledge_context()
    current_period_key = f"{accounting_period['year']}-{str(accounting_period['period']).zfill(2)}"
    supplier_event = {
        **event,
        "payload": {
            **(event.get("payload") or {}),
            "provider_supplier_id": batch["provider_supplier_id"],
            "supplier_name": batch.get("supplier_name"),
        },
    }
    total_po_amount = sum(float(po.get("amount") or 0) for po in batch.get("purchase_orders") or [])
    missing_fields: list[str] = []
    document_refs = [
        *[po["provider_purchase_order_id"] for po in batch.get("purchase_orders") or []],
        *[pinv["provider_purchase_invoice_id"] for pinv in batch.get("purchase_invoices") or []],
    ]
    existing_journals = load_existing_journals_for_supplier(
        organization_id=event["organization_id"],
        provider_supplier_id=batch["provider_supplier_id"],
        start_date=period_window["start_date"],
        end_date=period_window["end_date"],
        gl_accounts=organization_policy["gl_accounts"],
        document_refs=document_refs,
    )
    nova_po_gl = load_nova_po_gl_account_codes(
        event["organization_id"],
        [po["provider_purchase_order_id"] for po in batch.get("purchase_orders") or []],
    )
    purchase_orders_with_gl = [
        {**po, **({"gl_account_code": nova_po_gl[po["provider_purchase_order_id"]]} if po["provider_purchase_order_id"] in nova_po_gl else {})}
        for po in batch.get("purchase_orders") or []
    ]
    if not purchase_orders_with_gl and not batch.get("purchase_invoices") and not existing_journals:
        missing_fields.append("supplier_documents")

    enriched_pinvs = [
        {**pinv, "amount": _abs_amount(pinv.get("amount"))}
        for pinv in batch.get("purchase_invoices") or []
    ]

    if len(enriched_pinvs) == 1:
        only = enriched_pinvs[0]
        purchase_invoice_context = {
            "provider_purchase_invoice_id": only["provider_purchase_invoice_id"],
            "invoice_date": only.get("invoice_date"),
            "amount": _abs_amount(only.get("amount")),
            "description": only.get("description"),
            "your_ref": only.get("your_ref"),
            "currency": only.get("currency") or "EUR",
            **({"gl_account_code": only["gl_account_code"]} if only.get("gl_account_code") else {}),
        }
    else:
        purchase_invoice_context = {}

    single_pinv = enriched_pinvs[0] if len(enriched_pinvs) == 1 else None
    derived_amount = _abs_amount(total_po_amount) or (_abs_amount(single_pinv.get("amount")) if single_pinv else 0)
    first_po = purchase_orders_with_gl[0] if purchase_orders_with_gl else None
    return {
        "event": supplier_event,
        "accounting_period": accounting_period,
        "period_window": period_window,
        "organization_policy": organization_policy,
        "available_gl_accounts": available_gl_accounts,
        "supplier_context": {
            "provider_supplier_id": batch["provider_supplier_id"],
            "supplier_name": batch.get("supplier_name"),
            "purchase_orders": purchase_orders_with_gl,
            "purchase_invoices": enriched_pinvs,
        },
        "po_context": {
            "provider_purchase_order_id": first_po["provider_purchase_order_id"],
            "order_number": first_po.get("order_number"),
            "is_delivered": first_po.get("is_delivered"),
            "is_closed": False,
            "delivery_date": first_po.get("receipt_date"),
            "erp_synced": True,
            "invoice_received": first_po.get("invoice_received"),
            "amount": _abs_amount(first_po.get("amount")),
            "supplier": batch.get("supplier_name"),
            "gl_account_code": first_po.get("gl_account_code"),
        } if first_po else _empty_po_context(),
        "purchase_invoice_context": purchase_invoice_context,
        "existing_journals": existing_journals,
        "history": historical_context,
        "data_quality": {
            "missing_fields": missing_fields,
            "is_complete": len(missing_fields) == 0,
        },
        "derived_metrics": {
            "amount": derived_amount,
            "current_period_key": current_period_key,
            "po_count": len(purchase_orders_with_gl),
            "pinv_count": len(batch.get("purchase_invoices") or []),
        },
        "policy_knowledge": policy_knowledge,
    }
