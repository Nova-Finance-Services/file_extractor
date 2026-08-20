"""Agent-shaped Exact operations. Accounting agents must not import Exact field names."""
from __future__ import annotations

import logging
from typing import Any, Optional

from provider.errors import ErpClosedPeriodError, ErpError
from provider.exact.connection import get_organization_connection
from provider.exact.purchasing import (
    PO_STATUS_CANCELLED,
    PO_STATUS_COMPLETE,
    get_purchase_entries,
    get_purchase_entry,
    get_purchase_order,
    get_purchase_orders,
)
from provider.exact.gl import (
    get_financial_period_for_date,
    get_gl_account_guid_by_code,
    get_gl_accounts,
    get_reporting_year_and_period,
)
from provider.exact.journals import (
    ExactMemorialPostError,
    list_journal_entry_lines,
    post_general_journal_entry,
)
from provider.exact.odata import normalize_exact_date

logger = logging.getLogger(__name__)

_PO_PAGE_SIZE = 100
_PINV_PAGE_SIZE = 200
_MAX_PAGES = 10
_PO_SELECT = (
    "PurchaseOrderID,OrderNumber,OrderDate,ReceiptDate,ReceiptStatus,InvoiceStatus,"
    "AmountDC,AmountFC,Currency,Supplier,SupplierName,Description"
)
_PINV_SELECT = (
    "EntryID,EntryNumber,EntryDate,Description,AmountFC,AmountDC,Currency,"
    "Supplier,SupplierName,YourRef,InvoiceNumber"
)


def pick_pinv_gl_account_code(entry: Optional[dict[str, Any]]) -> Optional[str]:
    if not entry:
        return None
    raw = entry.get("PurchaseEntryLines")
    lines: list[dict[str, Any]] = []
    if isinstance(raw, list):
        lines = [row for row in raw if isinstance(row, dict)]
    elif isinstance(raw, dict) and isinstance(raw.get("results"), list):
        lines = [row for row in raw["results"] if isinstance(row, dict)]

    best_code: Optional[str] = None
    best_abs = -1.0
    for line in lines:
        code = str(line.get("GLAccountCode") or "").strip()
        if not code:
            continue
        amount = abs(float(line.get("AmountFC") or line.get("AmountDC") or 0) or 0)
        if amount >= best_abs:
            best_abs = amount
            best_code = code
    return best_code


def map_purchase_order(row: dict[str, Any]) -> Optional[dict[str, Any]]:
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
    amount = row.get("AmountDC") if isinstance(row.get("AmountDC"), (int, float)) else row.get("AmountFC")
    return {
        "provider_purchase_order_id": po_id,
        "order_number": row.get("OrderNumber") if isinstance(row.get("OrderNumber"), (int, float)) else None,
        "order_date": normalize_exact_date(row.get("OrderDate")),
        "receipt_date": normalize_exact_date(row.get("ReceiptDate")),
        "delivery_date": normalize_exact_date(row.get("ReceiptDate")),
        "is_delivered": receipt_status == PO_STATUS_COMPLETE,
        "is_closed": receipt_status == PO_STATUS_CANCELLED or invoice_status == PO_STATUS_CANCELLED,
        "invoice_received": invoice_status == PO_STATUS_COMPLETE,
        "amount": abs(amount) if isinstance(amount, (int, float)) else None,
        "currency": row.get("Currency") if isinstance(row.get("Currency"), str) else None,
        "description": row.get("Description") if isinstance(row.get("Description"), str) else None,
        "supplier": row.get("SupplierName") if isinstance(row.get("SupplierName"), str) else None,
        "provider_supplier_id": str(row.get("Supplier") or "").strip() or None,
        "supplier_name": row.get("SupplierName") if isinstance(row.get("SupplierName"), str) else None,
    }


def map_purchase_invoice(row: dict[str, Any], *, include_gl: bool = False) -> Optional[dict[str, Any]]:
    pinv_id = str(row.get("EntryID") or row.get("ID") or "").strip()
    if not pinv_id:
        return None
    amount = None
    if isinstance(row.get("AmountFC"), (int, float)):
        amount = abs(row["AmountFC"])
    elif isinstance(row.get("AmountDC"), (int, float)):
        amount = abs(row["AmountDC"])
    mapped = {
        "provider_purchase_invoice_id": pinv_id,
        "entry_number": row.get("EntryNumber") if isinstance(row.get("EntryNumber"), (int, float)) else None,
        "invoice_date": normalize_exact_date(row.get("EntryDate")),
        "amount": amount,
        "currency": row.get("Currency") if isinstance(row.get("Currency"), str) else None,
        "description": row.get("Description") if isinstance(row.get("Description"), str) else None,
        "your_ref": row.get("YourRef") if isinstance(row.get("YourRef"), str) else None,
        "provider_supplier_id": str(row.get("Supplier") or "").strip() or None,
        "supplier_name": row.get("SupplierName") if isinstance(row.get("SupplierName"), str) else None,
    }
    gl = pick_pinv_gl_account_code(row) if include_gl or row.get("PurchaseEntryLines") else None
    if gl:
        mapped["gl_account_code"] = gl
    return mapped


def get_purchase_order_for_close(organization_id: str, provider_po_id: str) -> Optional[dict[str, Any]]:
    raw = get_purchase_order(organization_id, provider_po_id, select=_PO_SELECT)
    return map_purchase_order(raw) if raw else None


def get_purchase_invoice_for_close(organization_id: str, provider_pinv_id: str) -> Optional[dict[str, Any]]:
    raw = get_purchase_entry(organization_id, provider_pinv_id)
    return map_purchase_invoice(raw, include_gl=True) if raw else None


def list_supplier_document_batches(organization_id: str, window: dict[str, str]) -> list[dict[str, Any]]:
    filter_expr = (
        f"OrderDate ge datetime'{window['start_date']}T00:00:00' "
        f"and OrderDate le datetime'{window['end_date']}T23:59:59'"
    )
    po_rows: list[dict[str, Any]] = []
    page = 1
    total_pages = 1
    while page <= total_pages and page <= _MAX_PAGES:
        result = get_purchase_orders(
            organization_id,
            page=page,
            limit=_PO_PAGE_SIZE,
            orderby="OrderDate desc",
            select=_PO_SELECT,
            filter_expr=filter_expr,
        )
        total_pages = result["pagination"]["totalPages"] or 1
        po_rows.extend(result["data"])
        page += 1

    pinv_rows = get_purchase_entries(
        organization_id,
        page=1,
        limit=_PINV_PAGE_SIZE,
        orderby="EntryDate desc",
        select=_PINV_SELECT,
        start_date=window["start_date"],
        end_date=window["end_date"],
    )["data"]

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
        mapped = map_purchase_order(row)
        if not mapped:
            continue
        supplier_id = mapped.get("provider_supplier_id") or ""
        supplier_name = mapped.get("supplier_name")
        if not supplier_id and not supplier_name:
            continue
        order = {k: v for k, v in mapped.items() if k not in {"provider_supplier_id", "supplier_name"}}
        ensure(supplier_id, supplier_name)["purchase_orders"].append(order)

    for row in pinv_rows:
        mapped = map_purchase_invoice(row)
        if not mapped:
            continue
        supplier_id = mapped.get("provider_supplier_id") or ""
        supplier_name = mapped.get("supplier_name")
        if not supplier_id and not supplier_name:
            continue
        pinv_id = mapped["provider_purchase_invoice_id"]
        try:
            entry = get_purchase_entry(organization_id, pinv_id)
            gl = pick_pinv_gl_account_code(entry)
            if gl:
                mapped["gl_account_code"] = gl
        except Exception:
            pass
        invoice = {k: v for k, v in mapped.items() if k not in {"provider_supplier_id", "supplier_name"}}
        ensure(supplier_id, supplier_name)["purchase_invoices"].append(invoice)

    return [
        batch
        for batch in by_supplier.values()
        if batch["purchase_orders"] or batch["purchase_invoices"]
    ]


def get_accounting_period(organization_id: str, date_iso: str) -> Optional[dict[str, Any]]:
    token = get_organization_connection(organization_id)
    if not token.get("connected") or not token.get("access_token") or token.get("division") is None:
        return None
    erp_period = get_financial_period_for_date(
        int(token["division"]),
        str(token["access_token"]),
        date_iso,
    )
    if not erp_period:
        return None
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


def _gl_guids(organization_id: str, codes: list[str]) -> list[str]:
    return [g for g in (get_gl_account_guid_by_code(organization_id, code) for code in codes if code) if g]


def _line_matches_refs(line: dict[str, Any], refs: list[str]) -> bool:
    if not refs:
        return True
    hay = f"{line.get('description') or ''} {line.get('notes') or ''}".lower()
    return any(
        rid and (f"pinv:{rid}" in hay or f"po:{rid}" in hay or rid in hay)
        for rid in (r.strip().lower() for r in refs)
    )


def list_close_journal_lines(
    organization_id: str,
    *,
    start_date: str,
    end_date: str,
    gl_account_codes: list[str],
    provider_supplier_id: Optional[str] = None,
    document_refs: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    token = get_organization_connection(organization_id)
    if not token.get("connected") or not token.get("access_token") or token.get("division") is None:
        return []
    guids = _gl_guids(organization_id, gl_account_codes)
    if not guids:
        return []
    common = {
        "division": int(token["division"]),
        "access_token": str(token["access_token"]),
        "gl_account_guids": guids,
        "start_date": start_date,
        "end_date": end_date,
    }
    supplier_id = (provider_supplier_id or "").strip()
    if supplier_id and not supplier_id.startswith("name:"):
        by_account = list_journal_entry_lines(**common, account_guid=supplier_id)
        if by_account:
            return by_account
    refs = [r.strip() for r in (document_refs or []) if r and r.strip()]
    if not refs:
        return []
    by_gl = list_journal_entry_lines(**common, top=200)
    return [line for line in by_gl if _line_matches_refs(line, refs)]


def list_supplier_ids_with_gl_activity(
    organization_id: str,
    *,
    start_date: str,
    end_date: str,
    gl_account_codes: list[str],
) -> list[str]:
    token = get_organization_connection(organization_id)
    if not token.get("connected") or not token.get("access_token") or token.get("division") is None:
        return []
    guids = _gl_guids(organization_id, gl_account_codes)
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
    return list({line["account_guid"].strip() for line in lines if (line.get("account_guid") or "").strip()})


def list_gl_accounts_for_agent(organization_id: str, default_codes: list[str]) -> list[dict[str, Any]]:
    defaults = [code.strip() for code in default_codes if code and code.strip()]

    def default_only() -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for code in defaults:
            if code in seen:
                continue
            seen.add(code)
            out.append({"code": code, "description": code})
        return out

    token = get_organization_connection(organization_id)
    if not token.get("connected") or not token.get("access_token") or token.get("division") is None:
        return default_only()
    try:
        accounts = get_gl_accounts(organization_id, str(token["access_token"]), int(token["division"]))
        default_set = set(defaults)
        by_code: dict[str, dict[str, Any]] = {}
        for acc in accounts:
            code = (acc.get("code") or "").strip()
            if not code:
                continue
            is_pnl = str(acc.get("balanceType") or "").upper() == "W"
            if not is_pnl and code not in default_set:
                continue
            item = {"code": code, "description": (acc.get("description") or "").strip() or code}
            if acc.get("typeDescription"):
                item["typeDescription"] = str(acc["typeDescription"]).strip()
            by_code[code] = item
        for code in default_set:
            by_code.setdefault(code, {"code": code, "description": code})
        return sorted(by_code.values(), key=lambda a: a["code"])
    except Exception as exc:
        logger.warning("list_gl_accounts_for_agent failed: %s", exc)
        return default_only()


def post_memorial_journal(
    organization_id: str,
    *,
    journal_code: str,
    proposal: dict[str, Any],
    provider_supplier_id: Optional[str] = None,
    provider_purchase_order_id: Optional[str] = None,
    provider_purchase_invoice_id: Optional[str] = None,
) -> dict[str, Any]:
    token = get_organization_connection(organization_id)
    if not token.get("connected") or not token.get("access_token") or token.get("division") is None:
        raise ErpError("ERP is not connected for this organization")

    division = int(token["division"])
    access_token = str(token["access_token"])
    debit_guid = get_gl_account_guid_by_code(organization_id, proposal["debit_account"])
    credit_guid = get_gl_account_guid_by_code(organization_id, proposal["credit_account"])
    if not debit_guid or not credit_guid:
        raise ErpError(
            f"Failed to resolve GL accounts (debit={proposal['debit_account']}, credit={proposal['credit_account']})"
        )

    amount = float(proposal["amount"])
    if not (amount > 0):
        raise ErpError(f"Invalid journal amount: {proposal['amount']}")

    reporting = get_reporting_year_and_period(division, access_token, proposal["posting_date"])
    supplier_id = (provider_supplier_id or "").strip()
    account_guid = supplier_id if supplier_id and not supplier_id.startswith("name:") else None
    line_notes = f"po:{provider_purchase_order_id or 'n/a'};pinv:{provider_purchase_invoice_id or 'n/a'}"

    try:
        posted = post_general_journal_entry(
            division=division,
            access_token=access_token,
            journal_code=journal_code,
            entry_date_iso=proposal["posting_date"],
            currency=proposal.get("currency") or "EUR",
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
            raise ErpClosedPeriodError(
                f"ERP rejected journal post — accounting period is closed ({exc.status})"
            ) from exc
        raise ErpError(str(exc)) from exc
