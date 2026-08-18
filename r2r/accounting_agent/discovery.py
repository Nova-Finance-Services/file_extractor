"""Supplier discovery and AccountingAgentContext assembly."""
from __future__ import annotations

import logging
from typing import Any, Optional

from r2r.accounting_agent.gl_codes import pick_primary_gl_account_code_from_entry_lines
from r2r.accounting_agent.loaders import (
    get_accounting_period_context,
    get_historical_context,
    get_organization_context,
    get_po_context,
    get_purchase_invoice_context,
    infer_service_period_from_text,
    list_supplier_ids_with_close_gl_activity,
    load_available_gl_accounts_for_agent,
    load_existing_journals_for_supplier,
    load_nova_po_gl_account_codes,
)
from r2r.accounting_agent.period_window import build_close_period_window
from r2r.accounting_agent.policies import get_policy_knowledge_context
from provider.exact import (
    PO_STATUS_COMPLETE,
    get_purchase_entries,
    get_purchase_entry,
    get_purchase_orders,
    normalize_exact_date,
)
from provider.router import resolve_organization_erp_provider

logger = logging.getLogger(__name__)

PO_PAGE_SIZE = 100
PINV_PAGE_SIZE = 200
MAX_PAGES = 10


def event_has_document_payload(payload: Optional[dict[str, Any]]) -> bool:
    payload = payload or {}
    return bool(payload.get("provider_purchase_order_id") or payload.get("provider_purchase_invoice_id"))


def event_has_supplier_payload(payload: Optional[dict[str, Any]]) -> bool:
    return bool((payload or {}).get("provider_supplier_id"))


def _abs_amount(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return abs(number)


def _invoice_months_covered(start: Optional[str], end: Optional[str]) -> int:
    if not start or not end:
        return 0
    try:
        start_date = __import__("datetime").date.fromisoformat(start[:10])
        end_date = __import__("datetime").date.fromisoformat(end[:10])
    except ValueError:
        return 0
    return (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month) + 1


def _service_covers_period(year: int, period: int, start: Optional[str], end: Optional[str]) -> bool:
    from calendar import monthrange
    from datetime import date
    if not start or not end:
        return False
    try:
        start_date = date.fromisoformat(start[:10])
        end_date = date.fromisoformat(end[:10])
    except ValueError:
        return False
    period_start = date(year, period, 1)
    period_end = date(year, period, monthrange(year, period)[1])
    return start_date <= period_end and end_date >= period_start


def _prepaid_monthly_release_amount(amount: float, months: int) -> float:
    abs_amt = _abs_amount(amount)
    if abs_amt <= 0 or months <= 1:
        return 0.0
    return round((abs_amt / months) * 100) / 100


def _empty_po_context() -> dict[str, Any]:
    return {
        "is_delivered": False,
        "is_closed": False,
        "invoice_received": False,
        "erp_synced": False,
    }


def _map_po(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    po_id = str(row.get("PurchaseOrderID") or row.get("ID") or "").strip()
    if not po_id:
        return None
    try:
        receipt_status = int(row.get("ReceiptStatus"))
    except (TypeError, ValueError):
        receipt_status = None
    try:
        invoice_status = int(row.get("InvoiceStatus"))
    except (TypeError, ValueError):
        invoice_status = None
    amount = None
    if isinstance(row.get("AmountDC"), (int, float)):
        amount = abs(row["AmountDC"])
    elif isinstance(row.get("AmountFC"), (int, float)):
        amount = abs(row["AmountFC"])
    return {
        "provider_purchase_order_id": po_id,
        "order_number": row.get("OrderNumber") if isinstance(row.get("OrderNumber"), (int, float)) else None,
        "order_date": normalize_exact_date(row.get("OrderDate")),
        "receipt_date": normalize_exact_date(row.get("ReceiptDate")),
        "receipt_status": receipt_status,
        "invoice_status": invoice_status,
        "is_delivered": receipt_status == PO_STATUS_COMPLETE,
        "invoice_received": invoice_status == PO_STATUS_COMPLETE,
        "amount": amount,
        "currency": row.get("Currency") if isinstance(row.get("Currency"), str) else None,
        "description": row.get("Description") if isinstance(row.get("Description"), str) else None,
    }


def _map_pinv(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    pinv_id = str(row.get("EntryID") or row.get("ID") or "").strip()
    if not pinv_id:
        return None
    amount = None
    if isinstance(row.get("AmountFC"), (int, float)):
        amount = abs(row["AmountFC"])
    elif isinstance(row.get("AmountDC"), (int, float)):
        amount = abs(row["AmountDC"])
    return {
        "provider_purchase_invoice_id": pinv_id,
        "entry_number": row.get("EntryNumber") if isinstance(row.get("EntryNumber"), (int, float)) else None,
        "invoice_date": normalize_exact_date(row.get("EntryDate")),
        "amount": amount,
        "currency": row.get("Currency") if isinstance(row.get("Currency"), str) else None,
        "description": row.get("Description") if isinstance(row.get("Description"), str) else None,
        "your_ref": row.get("YourRef") if isinstance(row.get("YourRef"), str) else None,
    }


def list_exact_supplier_close_batches(organization_id: str, window: dict[str, str]) -> list[dict[str, Any]]:
    filter_expr = (
        f"OrderDate ge datetime'{window['start_date']}T00:00:00' "
        f"and OrderDate le datetime'{window['end_date']}T23:59:59'"
    )
    po_rows: list[dict[str, Any]] = []
    page = 1
    total_pages = 1
    while page <= total_pages and page <= MAX_PAGES:
        result = get_purchase_orders(
            organization_id,
            page=page,
            limit=PO_PAGE_SIZE,
            orderby="OrderDate desc",
            select="PurchaseOrderID,OrderNumber,OrderDate,ReceiptDate,ReceiptStatus,InvoiceStatus,AmountDC,AmountFC,Currency,Supplier,SupplierName,Description",
            filter_expr=filter_expr,
        )
        total_pages = result["pagination"]["totalPages"] or 1
        po_rows.extend(result["data"])
        page += 1

    pinv_result = get_purchase_entries(
        organization_id,
        page=1,
        limit=PINV_PAGE_SIZE,
        orderby="EntryDate desc",
        select="EntryID,EntryNumber,EntryDate,Description,AmountFC,AmountDC,Currency,Supplier,SupplierName,YourRef,InvoiceNumber",
        start_date=window["start_date"],
        end_date=window["end_date"],
    )
    pinv_rows = pinv_result["data"]

    by_supplier: dict[str, dict[str, Any]] = {}

    def ensure(supplier_id: str, supplier_name: Optional[str]) -> dict[str, Any]:
        key = supplier_id or f"name:{supplier_name or 'unknown'}"
        batch = by_supplier.get(key)
        if not batch:
            batch = {
                "provider_supplier_id": supplier_id or key,
                "supplier_name": supplier_name,
                "purchase_orders": [],
                "purchase_invoices": [],
            }
            by_supplier[key] = batch
        elif supplier_name and not batch.get("supplier_name"):
            batch["supplier_name"] = supplier_name
        return batch

    for row in po_rows:
        supplier_id = str(row.get("Supplier") or "").strip()
        supplier_name = row.get("SupplierName") if isinstance(row.get("SupplierName"), str) else None
        if not supplier_id and not supplier_name:
            continue
        mapped = _map_po(row)
        if mapped:
            ensure(supplier_id, supplier_name)["purchase_orders"].append(mapped)

    for row in pinv_rows:
        supplier_id = str(row.get("Supplier") or "").strip()
        supplier_name = row.get("SupplierName") if isinstance(row.get("SupplierName"), str) else None
        if not supplier_id and not supplier_name:
            continue
        mapped = _map_pinv(row)
        if mapped:
            ensure(supplier_id, supplier_name)["purchase_invoices"].append(mapped)

    return [
        batch
        for batch in by_supplier.values()
        if batch["purchase_orders"] or batch["purchase_invoices"]
    ]


def list_supplier_close_batches(
    organization_id: str,
    event_type: str,
    window: dict[str, str],
) -> list[dict[str, Any]]:
    if event_type not in {"month_start", "month_end"}:
        return []
    provider = resolve_organization_erp_provider(organization_id)
    if not provider:
        return []
    if provider != "exact":
        raise RuntimeError(f"Unsupported ERP provider for close candidates: {provider}")
    doc_batches = list_exact_supplier_close_batches(organization_id, window)
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


def _enrich_pinv_service_period(pinv: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(p for p in [pinv.get("description"), pinv.get("your_ref")] if p)
    inferred = infer_service_period_from_text(text)
    return {
        "provider_purchase_invoice_id": pinv["provider_purchase_invoice_id"],
        "invoice_date": pinv.get("invoice_date"),
        "amount": pinv.get("amount"),
        "description": pinv.get("description"),
        "currency": pinv.get("currency") or "EUR",
        "service_period_start": inferred.get("start"),
        "service_period_end": inferred.get("end"),
    }


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
    if has_invoice and (
        not purchase_invoice_context.get("service_period_start")
        or not purchase_invoice_context.get("service_period_end")
    ):
        missing_fields.append("service_period")
    derived_amount = _abs_amount(po_context.get("amount") or purchase_invoice_context.get("amount") or 0)
    months_covered = _invoice_months_covered(
        purchase_invoice_context.get("service_period_start"),
        purchase_invoice_context.get("service_period_end"),
    )
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
            "invoice_months_covered": months_covered,
            "prepaid_monthly_release_amount": _prepaid_monthly_release_amount(derived_amount, months_covered),
            "service_covers_current_period": _service_covers_period(
                accounting_period["year"],
                accounting_period["period"],
                purchase_invoice_context.get("service_period_start"),
                purchase_invoice_context.get("service_period_end"),
            ),
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
    pinv_gl_map: dict[str, str] = {}
    for pinv in batch.get("purchase_invoices") or []:
        try:
            entry = get_purchase_entry(event["organization_id"], pinv["provider_purchase_invoice_id"])
            gl = pick_primary_gl_account_code_from_entry_lines(entry)
            if gl:
                pinv_gl_map[pinv["provider_purchase_invoice_id"]] = gl
        except Exception:
            continue

    purchase_orders_with_gl = [
        {**po, **({"gl_account_code": nova_po_gl[po["provider_purchase_order_id"]]} if po["provider_purchase_order_id"] in nova_po_gl else {})}
        for po in batch.get("purchase_orders") or []
    ]
    if not purchase_orders_with_gl and not batch.get("purchase_invoices") and not existing_journals:
        missing_fields.append("supplier_documents")

    enriched_pinvs = []
    for pinv in batch.get("purchase_invoices") or []:
        enriched = _enrich_pinv_service_period(pinv)
        amount = _abs_amount(pinv.get("amount"))
        months = _invoice_months_covered(enriched.get("service_period_start"), enriched.get("service_period_end"))
        gl = pinv_gl_map.get(pinv["provider_purchase_invoice_id"])
        row = {
            **pinv,
            "amount": amount,
            "service_period_start": enriched.get("service_period_start"),
            "service_period_end": enriched.get("service_period_end"),
            "invoice_months_covered": months,
            "prepaid_monthly_release_amount": _prepaid_monthly_release_amount(amount, months),
            "service_covers_current_period": _service_covers_period(
                accounting_period["year"],
                accounting_period["period"],
                enriched.get("service_period_start"),
                enriched.get("service_period_end"),
            ),
        }
        if gl:
            row["gl_account_code"] = gl
        enriched_pinvs.append(row)

    if len(enriched_pinvs) == 1:
        only = enriched_pinvs[0]
        purchase_invoice_context = {
            "provider_purchase_invoice_id": only["provider_purchase_invoice_id"],
            "invoice_date": only.get("invoice_date"),
            "amount": _abs_amount(only.get("amount")),
            "description": only.get("description"),
            "currency": only.get("currency") or "EUR",
            "service_period_start": only.get("service_period_start"),
            "service_period_end": only.get("service_period_end"),
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
            "invoice_months_covered": (single_pinv or {}).get("invoice_months_covered") or 0,
            "prepaid_monthly_release_amount": (single_pinv or {}).get("prepaid_monthly_release_amount") or 0,
            "service_covers_current_period": (single_pinv or {}).get("service_covers_current_period") or False,
            "current_period_key": current_period_key,
            "po_count": len(purchase_orders_with_gl),
            "pinv_count": len(batch.get("purchase_invoices") or []),
        },
        "policy_knowledge": policy_knowledge,
    }
