"""Purchase orders and purchase invoices (Exact purchase entries)."""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from provider.exact.connection import require_connection
from provider.exact.odata import exact_v1, odata_entity, odata_results

PO_STATUS_COMPLETE = 30
PO_STATUS_CANCELLED = 40


def get_purchase_order(
    organization_id: str,
    purchase_order_id: str,
    select: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    access_token, division = require_connection(organization_id)
    url = f"{exact_v1('purchaseorder/PurchaseOrders', division)}(guid'{purchase_order_id}')"
    if select:
        url += f"?$select={select}"
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=60,
    )
    if response.status_code == 404:
        return None
    if not response.ok:
        raise RuntimeError(f"Failed to fetch purchase order: {response.status_code} {response.text[:400]}")
    return odata_entity(response.json())


def get_purchase_orders(
    organization_id: str,
    *,
    page: int = 1,
    limit: int = 100,
    orderby: str = "OrderDate desc",
    select: str,
    filter_expr: Optional[str] = None,
) -> dict[str, Any]:
    access_token, division = require_connection(organization_id)
    skip = (page - 1) * limit
    params = {
        "$top": str(limit),
        "$skip": str(skip),
        "$orderby": orderby,
        "$select": select,
        "$inlinecount": "allpages",
    }
    if filter_expr:
        params["$filter"] = filter_expr
    response = requests.get(
        f"{exact_v1('purchaseorder/PurchaseOrders', division)}?{urlencode(params)}",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=60,
    )
    if not response.ok:
        raise RuntimeError(f"Failed to fetch purchase orders: {response.status_code} {response.text[:400]}")
    payload = response.json()
    rows = odata_results(payload)
    total = payload.get("d", {}).get("__count") if isinstance(payload.get("d"), dict) else None
    total_count = int(total) if total is not None else len(rows)
    return {
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total_count,
            "totalPages": max(1, (total_count + limit - 1) // limit) if total_count else 1,
        },
        "data": rows,
    }


def get_purchase_entries(
    organization_id: str,
    *,
    page: int = 1,
    limit: int = 200,
    orderby: str = "EntryDate desc",
    select: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict[str, Any]:
    access_token, division = require_connection(organization_id)
    skip = (page - 1) * limit
    filter_parts = []
    if start_date and re.match(r"^\d{4}-\d{2}-\d{2}$", start_date):
        filter_parts.append(f"EntryDate ge datetime'{start_date}T00:00:00'")
    if end_date and re.match(r"^\d{4}-\d{2}-\d{2}$", end_date):
        filter_parts.append(f"EntryDate le datetime'{end_date}T00:00:00'")
    params = {
        "$top": str(limit),
        "$skip": str(skip),
        "$orderby": orderby,
        "$select": select,
        "$inlinecount": "allpages",
    }
    if filter_parts:
        params["$filter"] = " and ".join(filter_parts)
    response = requests.get(
        f"{exact_v1('purchaseentry/PurchaseEntries', division)}?{urlencode(params)}",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=60,
    )
    if not response.ok:
        raise RuntimeError(f"Failed to fetch purchase entries: {response.status_code} {response.text[:400]}")
    payload = response.json()
    rows = odata_results(payload)
    total = payload.get("d", {}).get("__count") if isinstance(payload.get("d"), dict) else None
    total_count = int(total) if total is not None else len(rows)
    return {
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total_count,
            "totalPages": max(1, (total_count + limit - 1) // limit) if total_count else 1,
        },
        "data": rows,
    }


def get_purchase_entry(organization_id: str, entry_id: str) -> Optional[dict[str, Any]]:
    access_token, division = require_connection(organization_id)
    url = (
        f"{exact_v1('purchaseentry/PurchaseEntries', division)}"
        f"(guid'{entry_id}')?$expand=PurchaseEntryLines"
    )
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=60,
    )
    if response.status_code == 404:
        return None
    if not response.ok:
        raise RuntimeError(f"Failed to fetch purchase entry: {response.status_code} {response.text[:400]}")
    return odata_entity(response.json())
