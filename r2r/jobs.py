"""Normalize accounting-agent job fields (org, suppliers, dry_run, occurred_at)."""
from __future__ import annotations

from typing import Any


def _id_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    elif isinstance(value, str) and value.strip():
        raw = [part.strip() for part in value.split(",")]
    else:
        raw = []
    seen: list[str] = []
    for item in raw:
        sid = str(item).strip()
        if sid and sid not in seen:
            seen.append(sid)
    return seen


def resolve_forced_supplier_ids(payload: dict[str, Any] | None) -> list[str]:
    """Exact supplier GUIDs from payload.provider_supplier_ids and/or provider_supplier_id."""
    payload = payload or {}
    ids = _id_list(payload.get("provider_supplier_ids"))
    for sid in _id_list(payload.get("provider_supplier_id")):
        if sid not in ids:
            ids.append(sid)
    return ids


def normalize_accounting_agent_job(job: dict[str, Any]) -> dict[str, Any]:
    """
    Fold test/API aliases onto the job the worker already understands.

    Accepts supplier_ids / provider_supplier_ids / provider_supplier_id on the job
    or inside payload, and writes payload.provider_supplier_ids plus
    payload.provider_supplier_id (first id, for existing single-supplier paths).
    """
    normalized = dict(job)
    payload = dict(normalized["payload"]) if isinstance(normalized.get("payload"), dict) else {}

    ids = resolve_forced_supplier_ids(payload)
    for key in ("supplier_ids", "provider_supplier_ids", "provider_supplier_id"):
        extra = normalized.pop(key, None)
        for sid in _id_list(extra):
            if sid not in ids:
                ids.append(sid)

    if ids:
        payload["provider_supplier_ids"] = ids
        payload["provider_supplier_id"] = ids[0]
    normalized["payload"] = payload
    normalized["dry_run"] = bool(normalized.get("dry_run"))
    return normalized
