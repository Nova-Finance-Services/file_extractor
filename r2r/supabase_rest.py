"""Minimal Supabase PostgREST client using the service-role key."""
from __future__ import annotations

import logging
from typing import Any, Optional
import requests

from r2r.config import resolve_supabase_service_role_key, resolve_supabase_url

logger = logging.getLogger(__name__)

_TIMEOUT = 30


class SupabaseRestError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


def _headers() -> dict[str, str]:
    key = resolve_supabase_service_role_key()
    if not key:
        raise SupabaseRestError("SUPABASE_SERVICE_ROLE_KEY is not configured")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _rest_url(table: str) -> str:
    base = resolve_supabase_url()
    if not base:
        raise SupabaseRestError("Supabase URL is not configured")
    return f"{base.rstrip('/')}/rest/v1/{table}"


def select(
    table: str,
    *,
    columns: str = "*",
    filters: Optional[dict[str, str]] = None,
    in_filters: Optional[dict[str, list[str]]] = None,
    order: Optional[str] = None,
    limit: Optional[int] = None,
    maybe_single: bool = False,
) -> Any:
    params: list[tuple[str, str]] = [("select", columns)]
    for key, value in (filters or {}).items():
        params.append((key, f"eq.{value}"))
    for key, values in (in_filters or {}).items():
        joined = ",".join(str(v) for v in values)
        params.append((key, f"in.({joined})"))
    if order:
        params.append(("order", order))
    if limit is not None:
        params.append(("limit", str(limit)))

    headers = _headers()
    if maybe_single:
        headers["Accept"] = "application/vnd.pgrst.object+json"

    response = requests.get(
        _rest_url(table),
        headers=headers,
        params=params,
        timeout=_TIMEOUT,
    )
    if maybe_single and response.status_code == 406:
        return None
    if not response.ok:
        raise SupabaseRestError(
            f"Supabase select {table} failed: {response.status_code} {response.text[:400]}",
            status=response.status_code,
            body=response.text,
        )
    if not response.content:
        return None if maybe_single else []
    return response.json()


def insert(table: str, row: dict[str, Any]) -> Any:
    response = requests.post(
        _rest_url(table),
        headers=_headers(),
        json=row,
        timeout=_TIMEOUT,
    )
    if not response.ok:
        raise SupabaseRestError(
            f"Supabase insert {table} failed: {response.status_code} {response.text[:400]}",
            status=response.status_code,
            body=response.text,
        )
    return response.json() if response.content else None


def update(table: str, row: dict[str, Any], *, filters: dict[str, str]) -> Any:
    params: list[tuple[str, str]] = []
    for key, value in filters.items():
        params.append((key, f"eq.{value}"))
    response = requests.patch(
        _rest_url(table),
        headers=_headers(),
        params=params,
        json=row,
        timeout=_TIMEOUT,
    )
    if not response.ok:
        raise SupabaseRestError(
            f"Supabase update {table} failed: {response.status_code} {response.text[:400]}",
            status=response.status_code,
            body=response.text,
        )
    return response.json() if response.content else None


def delete(table: str, *, filters: dict[str, str]) -> None:
    params: list[tuple[str, str]] = []
    for key, value in filters.items():
        params.append((key, f"eq.{value}"))
    response = requests.delete(
        _rest_url(table),
        headers=_headers(),
        params=params,
        timeout=_TIMEOUT,
    )
    if not response.ok:
        raise SupabaseRestError(
            f"Supabase delete {table} failed: {response.status_code} {response.text[:400]}",
            status=response.status_code,
            body=response.text,
        )
