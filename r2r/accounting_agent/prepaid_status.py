"""Deterministic prepaid balance from existing_journals for one PINV."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Optional


def _abs_amount(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return abs(number) if number == number else 0.0  # NaN check


def _round2(value: float) -> float:
    return round(value * 100) / 100


def parse_prepaid_desc_meta(description: Optional[str] = None) -> dict[str, Any]:
    if not description:
        return {}
    inv_match = re.search(r"\binv\s+(\d+)\b", description, re.I)
    service_match = re.search(
        r"\bservice\s+(\d{4}-\d{2}-\d{2})(?:\s+to\s+(\d{4}-\d{2}-\d{2}))?",
        description,
        re.I,
    )
    out: dict[str, Any] = {}
    if inv_match:
        out["entry_number"] = int(inv_match.group(1))
    if service_match:
        out["service_period_start"] = service_match.group(1)
        if service_match.group(2):
            out["service_period_end"] = service_match.group(2)
    return out


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def months_covered(start: Optional[str], end: Optional[str]) -> int:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if not start_date or not end_date:
        return 0
    return (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month) + 1


def service_covers_period(year: int, period: int, start: Optional[str], end: Optional[str]) -> bool:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if not start_date or not end_date:
        return False
    from calendar import monthrange
    period_start = date(year, period, 1)
    period_end = date(year, period, monthrange(year, period)[1])
    return start_date <= period_end and end_date >= period_start


def is_last_service_month(year: int, period: int, end: Optional[str]) -> bool:
    if not end or not re.match(r"^\d{4}-\d{2}-\d{2}", end):
        return False
    return int(end[:4]) == year and int(end[5:7]) == period


def _line_text(line: dict[str, Any]) -> str:
    return f"{line.get('description') or ''} {line.get('notes') or ''}"


def _signed_amount(line: dict[str, Any]) -> float:
    raw = line.get("amount_dc") if line.get("amount_dc") is not None else line.get("amount_fc")
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if number != number else number


def _prepaid_movements(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One memorial entry is setup OR release, never both legs of the same posting."""
    by_entry: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in lines:
        key = str(line.get("entry_id") or line.get("id") or "")
        by_entry[key].append(line)

    movements: list[dict[str, Any]] = []
    for group in by_entry.values():
        prepaid = [line for line in group if line.get("role") == "prepaid"]
        source = prepaid or [
            line for line in group
            if "prepaid setup" in _line_text(line).lower() or "prepaid release" in _line_text(line).lower()
        ]
        if not source:
            continue
        sample = source[0]
        text = _line_text(sample).lower()
        net = sum(_signed_amount(line) for line in source)
        amt = _round2(abs(net)) if abs(net) >= 0.01 else max(_abs_amount(_signed_amount(line)) for line in source)
        if amt <= 0:
            continue
        if "prepaid release" in text or (abs(net) >= 0.01 and net < 0):
            kind = "release"
        else:
            kind = "setup"
        movements.append({"kind": kind, "amount": amt, "line": sample})
    return movements


def _period_key_from_date(value: Optional[str]) -> Optional[str]:
    if not value or not re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return None
    return value[:7]


def get_prepaid_status(context: dict[str, Any], provider_purchase_invoice_id: str) -> dict[str, Any]:
    pinv_id = provider_purchase_invoice_id.strip()
    flags: list[str] = []
    needle = f"pinv:{pinv_id}".lower()
    period_key = context["derived_metrics"]["current_period_key"]
    year = context["accounting_period"]["year"]
    period = context["accounting_period"]["period"]

    pinvs = (context.get("supplier_context") or {}).get("purchase_invoices") or []
    pinv = next((p for p in pinvs if p.get("provider_purchase_invoice_id") == pinv_id), None)
    matches_primary = (
        (context.get("purchase_invoice_context") or {}).get("provider_purchase_invoice_id") == pinv_id
    )

    inv_number = pinv.get("entry_number") if pinv else None
    service_start = (pinv or {}).get("service_period_start")
    service_end = (pinv or {}).get("service_period_end")
    if matches_primary:
        primary = context.get("purchase_invoice_context") or {}
        service_start = service_start or primary.get("service_period_start")
        service_end = service_end or primary.get("service_period_end")

    matching = [
        line for line in (context.get("existing_journals") or [])
        if needle in _line_text(line).lower()
    ]
    movements = _prepaid_movements(matching)

    setup_amount = 0.0
    released_to_date = 0.0
    released_this_period = False
    release_amounts: list[float] = []

    for movement in movements:
        kind = movement["kind"]
        amt = movement["amount"]
        line = movement["line"]
        parsed = parse_prepaid_desc_meta(line.get("description") or line.get("notes"))
        if parsed.get("entry_number") is not None and inv_number is None:
            inv_number = parsed["entry_number"]
        if parsed.get("service_period_start"):
            service_start = service_start or parsed["service_period_start"]
        if parsed.get("service_period_end"):
            service_end = service_end or parsed["service_period_end"]

        if kind == "setup":
            if amt > setup_amount:
                setup_amount = amt
        elif kind == "release":
            released_to_date = _round2(released_to_date + amt)
            release_amounts.append(amt)
            line_period = _period_key_from_date(line.get("date"))
            release_period_match = re.search(
                r"prepaid\s+release\s+(\d{4}-\d{2})\b",
                _line_text(line),
                re.I,
            )
            desc_period = release_period_match.group(1) if release_period_match else None
            if line_period == period_key or desc_period == period_key:
                released_this_period = True

    if not service_start or not service_end or inv_number is None:
        for line in matching:
            parsed = parse_prepaid_desc_meta(line.get("description") or line.get("notes"))
            if parsed.get("entry_number") is not None and inv_number is None:
                inv_number = parsed["entry_number"]
            if parsed.get("service_period_start"):
                service_start = service_start or parsed["service_period_start"]
            if parsed.get("service_period_end"):
                service_end = service_end or parsed["service_period_end"]

    remaining = _round2(max(0.0, setup_amount - released_to_date))
    monthly = (pinv or {}).get("prepaid_monthly_release_amount") or 0
    if monthly <= 0 and matches_primary:
        monthly = context["derived_metrics"].get("prepaid_monthly_release_amount") or 0
    months = months_covered(service_start, service_end)
    if monthly <= 0 and setup_amount > 0 and months > 1:
        monthly = _round2(setup_amount / months)
    if monthly <= 0 and release_amounts:
        monthly = _round2(sum(release_amounts) / len(release_amounts))

    covers = service_covers_period(year, period, service_start, service_end)
    last_month = is_last_service_month(year, period, service_end)
    dates_clear = bool(service_start and service_end)

    suggested = 0.0
    if remaining > 0 and dates_clear and covers:
        suggested = remaining if last_month else _round2(min(monthly if monthly > 0 else remaining, remaining))
    elif remaining > 0 and not dates_clear and setup_amount > 0:
        suggested = _round2(min(monthly if monthly > 0 else remaining, remaining))

    if setup_amount <= 0:
        flags.append("no_prepaid_setup_found")
    if not dates_clear:
        flags.append("service_dates_missing_or_unclear")
    if released_this_period:
        flags.append("already_released_this_period")
    if setup_amount > 0 and remaining <= 0:
        flags.append("fully_released")
    if dates_clear and not covers:
        flags.append("current_period_outside_service_window")
    if last_month:
        flags.append("last_service_month_true_up")

    return {
        "provider_purchase_invoice_id": pinv_id,
        "inv_number": inv_number,
        "service_period_start": service_start,
        "service_period_end": service_end,
        "setup_amount": setup_amount,
        "released_to_date": released_to_date,
        "remaining": remaining,
        "monthly_release_amount": monthly,
        "released_this_period": released_this_period,
        "service_covers_current_period": covers,
        "is_last_service_month": last_month,
        "suggested_release": suggested,
        "can_release": suggested > 0 and dates_clear and covers and not released_this_period,
        "flags": flags,
    }
