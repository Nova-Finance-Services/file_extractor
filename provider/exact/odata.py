"""OData helpers and Exact Online URL builders."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from provider.exact.const import EXACT_API_BASE_URL

GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_DATE_MS_RE = re.compile(r"^/Date\((-?\d+)(?:[+-]\d+)?\)/$")


def is_exact_guid(value: str) -> bool:
    return bool(GUID_RE.match((value or "").strip()))


def with_division(template: str, division: int | str) -> str:
    return template.replace("{division}", str(division))


def exact_v1(path: str, division: int | str) -> str:
    return f"{EXACT_API_BASE_URL}/v1/{division}/{path}"


def normalize_exact_date(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    match = _DATE_MS_RE.match(text)
    if match:
        return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=timezone.utc).date().isoformat()
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    return None


def odata_results(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    inner = payload.get("d", payload.get("value"))
    if isinstance(inner, list):
        return [row for row in inner if isinstance(row, dict)]
    if isinstance(inner, dict):
        results = inner.get("results")
        if isinstance(results, list):
            return [row for row in results if isinstance(row, dict)]
        if inner.get("ID") or inner.get("EntryID"):
            return [inner]
    return []


def odata_entity(payload: Any) -> Optional[dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    inner = payload.get("d")
    if isinstance(inner, dict):
        return inner
    if payload.get("ID") or payload.get("EntryID"):
        return payload
    return None


def exact_get_json(url: str, access_token: str) -> Any:
    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        timeout=60,
    )
    if not response.ok:
        raise RuntimeError(
            f"Exact GET {response.status_code}: {response.text[:400]}"
        )
    return response.json() if response.content else {}
