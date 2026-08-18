"""GL accounts and financial periods."""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional
from urllib.parse import urlencode

from provider.exact.connection import require_connection
from provider.exact.odata import exact_get_json, exact_v1, is_exact_guid, normalize_exact_date, odata_entity, odata_results

logger = logging.getLogger(__name__)

_gl_cache: dict[str, list[dict[str, Any]]] = {}
_gl_lock = threading.Lock()


def get_gl_accounts(organization_id: str, access_token: str, division: int) -> list[dict[str, Any]]:
    cache_key = f"{organization_id}:{division}"
    with _gl_lock:
        cached = _gl_cache.get(cache_key)
        if cached is not None:
            return cached

    url = (
        f"{exact_v1('bulk/Financial/GLAccounts', division)}"
        f"?$select=ID,Code,Description,BalanceSide,BalanceType,Type,TypeDescription&$top=1000"
    )
    accounts: list[dict[str, Any]] = []
    next_url: Optional[str] = url
    while next_url:
        payload = exact_get_json(next_url, access_token)
        for row in odata_results(payload):
            accounts.append({
                "id": str(row.get("ID") or ""),
                "code": str(row.get("Code") or ""),
                "description": str(row.get("Description") or ""),
                "balanceSide": row.get("BalanceSide"),
                "balanceType": row.get("BalanceType"),
                "type": row.get("Type"),
                "typeDescription": row.get("TypeDescription"),
            })
        inner = payload.get("d") if isinstance(payload, dict) else None
        next_url = None
        if isinstance(inner, dict):
            next_url = inner.get("__next")
        if not next_url and isinstance(payload, dict):
            next_url = payload.get("@odata.nextLink")

    with _gl_lock:
        _gl_cache[cache_key] = accounts
    return accounts


def get_gl_account_guid_by_code(organization_id: str, code_or_guid: str) -> Optional[str]:
    value = (code_or_guid or "").strip()
    if not value:
        return None
    if is_exact_guid(value):
        return value
    try:
        access_token, division = require_connection(organization_id)
    except RuntimeError:
        return None
    try:
        accounts = get_gl_accounts(organization_id, access_token, division)
        match = next((a for a in accounts if (a.get("code") or "").strip() == value), None)
        if match and match.get("id"):
            return str(match["id"])
    except Exception as exc:
        logger.warning("get_gl_accounts failed, falling back to direct lookup: %s", exc)

    escaped = value.replace("'", "''")
    url = (
        f"{exact_v1('financial/GLAccounts', division)}"
        f"?$filter=Code eq '{escaped}'&$select=ID,Code,Description"
    )
    try:
        payload = exact_get_json(url, access_token)
        rows = odata_results(payload)
        if rows and rows[0].get("ID"):
            return str(rows[0]["ID"])
        entity = odata_entity(payload)
        if entity and entity.get("ID"):
            return str(entity["ID"])
    except Exception as exc:
        logger.warning("GL account lookup failed for %s: %s", value, exc)
    return None


def list_financial_periods(division: int, access_token: str) -> list[dict[str, Any]]:
    params = urlencode({
        "$select": "FinYear,FinPeriod,StartDate,EndDate",
        "$orderby": "FinYear asc,FinPeriod asc",
        "$top": "200",
    })
    payload = exact_get_json(
        f"{exact_v1('financial/FinancialPeriods', division)}?{params}",
        access_token,
    )
    periods = []
    for row in odata_results(payload):
        year = row.get("FinYear")
        period = row.get("FinPeriod")
        if year is None or period is None:
            continue
        periods.append({
            "financialYear": int(year),
            "financialPeriod": int(period),
            "startDate": normalize_exact_date(row.get("StartDate")),
            "endDate": normalize_exact_date(row.get("EndDate")),
        })
    return periods


def find_period_for_date(periods: list[dict[str, Any]], date_iso: str) -> Optional[dict[str, Any]]:
    target = date_iso.split("T")[0]
    for period in periods:
        start = period.get("startDate")
        end = period.get("endDate")
        if start and end and start <= target <= end:
            return period
    return None


def get_financial_period_for_date(division: int, access_token: str, date_iso: str) -> Optional[dict[str, Any]]:
    return find_period_for_date(list_financial_periods(division, access_token), date_iso)


def get_reporting_year_and_period(division: int, access_token: str, date_iso: str) -> dict[str, int]:
    period = get_financial_period_for_date(division, access_token, date_iso)
    if not period:
        date_only = date_iso.split("T")[0]
        raise RuntimeError(
            f"Cannot find FinancialPeriod for date {date_only} in Exact Online. "
            "The financial year and period must exist in the FinancialPeriods table."
        )
    return {
        "reportingYear": int(period["financialYear"]),
        "reportingPeriod": int(period["financialPeriod"]),
    }
