"""Memorial journal lines and posting."""
from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from provider.exact.odata import exact_get_json, exact_v1, normalize_exact_date, odata_entity, odata_results

logger = logging.getLogger(__name__)


class ExactMemorialPostError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"Exact memorial post failed: {status} {body}")
        self.status = status
        self.body = body
        self.closed_period = is_closed_accounting_period_error(body)


def is_closed_accounting_period_error(message: str) -> bool:
    lower = message.lower()
    return (
        "period is closed" in lower
        or "accounting period is closed" in lower
        or "period closed" in lower
        or "periode is gesloten" in lower
        or ("boekperiode" in lower and "gesloten" in lower)
    )


def list_journal_entry_lines(
    *,
    division: int,
    access_token: str,
    gl_account_guids: list[str],
    start_date: str,
    end_date: str,
    account_guid: Optional[str] = None,
    top: int = 100,
) -> list[dict[str, Any]]:
    guids = [g.strip() for g in gl_account_guids if g and g.strip()]
    if not guids:
        return []
    start = start_date.split("T")[0]
    end = end_date.split("T")[0]
    gl_filter = " or ".join(f"GLAccount eq guid'{g}'" for g in guids)
    parts = [
        f"Date ge datetime'{start}T00:00:00'",
        f"Date le datetime'{end}T23:59:59'",
        f"({gl_filter})",
    ]
    if account_guid and account_guid.strip():
        parts.insert(0, f"Account eq guid'{account_guid.strip()}'")
    params = urlencode({
        "$filter": " and ".join(parts),
        "$top": str(top),
        "$orderby": "Date desc",
        "$select": "ID,EntryID,EntryNumber,Date,AmountDC,AmountFC,GLAccount,GLAccountCode,Description,Notes,Account",
    })
    try:
        payload = exact_get_json(
            f"{exact_v1('generaljournalentry/GeneralJournalEntryLines', division)}?{params}",
            access_token,
        )
    except Exception as exc:
        logger.warning("list_journal_entry_lines failed: %s", exc)
        return []

    lines = []
    for row in odata_results(payload):
        line_id = str(row.get("ID") or "").strip()
        if not line_id:
            continue
        entry_number = row.get("EntryNumber")
        lines.append({
            "id": line_id,
            "entry_id": str(row["EntryID"]) if row.get("EntryID") is not None else None,
            "entry_number": int(entry_number) if isinstance(entry_number, (int, float)) else None,
            "date": normalize_exact_date(row.get("Date")),
            "amount_dc": row.get("AmountDC") if isinstance(row.get("AmountDC"), (int, float)) else None,
            "amount_fc": row.get("AmountFC") if isinstance(row.get("AmountFC"), (int, float)) else None,
            "gl_account_guid": str(row["GLAccount"]) if row.get("GLAccount") is not None else None,
            "gl_account_code": row.get("GLAccountCode") if isinstance(row.get("GLAccountCode"), str) else None,
            "description": row.get("Description") if isinstance(row.get("Description"), str) else None,
            "notes": row.get("Notes") if isinstance(row.get("Notes"), str) else None,
            "account_guid": str(row["Account"]) if row.get("Account") is not None else None,
        })
    return lines


def post_general_journal_entry(
    *,
    division: int,
    access_token: str,
    journal_code: str,
    entry_date_iso: str,
    currency: str,
    lines: list[dict[str, Any]],
    reporting_year: Optional[int] = None,
    reporting_period: Optional[int] = None,
) -> dict[str, Any]:
    code = journal_code.strip()
    if not code:
        raise RuntimeError("JournalCode is required for GeneralJournalEntries")
    entry_date = entry_date_iso.split("T")[0]
    payload_lines = []
    for line in lines:
        row: dict[str, Any] = {
            "GLAccount": line["glAccountGuid"],
            "AmountDC": float(line["amount"]),
            "AmountFC": float(line["amount"]),
            "Date": entry_date,
            "Description": line.get("description"),
        }
        if line.get("accountGuid"):
            row["Account"] = line["accountGuid"]
        if line.get("notes"):
            row["Notes"] = line["notes"]
        payload_lines.append(row)

    body: dict[str, Any] = {
        "JournalCode": code,
        "Currency": currency,
        "GeneralJournalEntryLines": payload_lines,
    }
    if reporting_year is not None:
        body["FinancialYear"] = reporting_year
    if reporting_period is not None:
        body["FinancialPeriod"] = reporting_period

    response = requests.post(
        exact_v1("generaljournalentry/GeneralJournalEntries", division),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=body,
        timeout=60,
    )
    text = response.text or ""
    if not response.ok:
        raise ExactMemorialPostError(response.status_code, text or response.reason)
    parsed = response.json() if text else {}
    entity = odata_entity(parsed) or (odata_results(parsed)[0] if odata_results(parsed) else parsed)
    entry_id = str((entity or {}).get("EntryID") or (entity or {}).get("ID") or "").strip()
    if not entry_id:
        raise RuntimeError("Exact GeneralJournalEntries post succeeded but returned no EntryID")
    entry_number = (entity or {}).get("EntryNumber")
    return {
        "id": entry_id,
        "entryNumber": int(entry_number) if isinstance(entry_number, (int, float)) else None,
    }
