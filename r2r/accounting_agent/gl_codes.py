"""Pure GL helpers (no Exact/Supabase)."""
from __future__ import annotations

from typing import Any, Optional


def is_allowed_cost_gl_account_code(
    code: Optional[str],
    available: Optional[list[dict[str, Any]]],
    default_cost_code: str,
) -> bool:
    trimmed = (code or "").strip()
    if not trimmed:
        return False
    if trimmed == default_cost_code.strip():
        return True
    return any(a.get("code") == trimmed for a in (available or []))


def pick_primary_gl_account_code_from_entry_lines(
    entry: Optional[dict[str, Any]],
) -> Optional[str]:
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
