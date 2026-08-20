"""Pure GL helpers (no ERP vendor fields)."""
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
