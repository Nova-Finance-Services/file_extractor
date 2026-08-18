"""Close-window period helpers (current + previous N periods)."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import TypedDict


class PeriodRef(TypedDict):
    year: int
    period: int


def shift_period(ref: PeriodRef, delta_months: int) -> PeriodRef:
    absolute = ref["year"] * 12 + (ref["period"] - 1) + delta_months
    year = absolute // 12
    period = (absolute % 12) + 1
    return {"year": year, "period": period}


def period_date_bounds(ref: PeriodRef) -> dict[str, str]:
    start = date(ref["year"], ref["period"], 1)
    end = date(ref["year"], ref["period"], monthrange(ref["year"], ref["period"])[1])
    return {"start": start.isoformat(), "end": end.isoformat()}


def build_close_period_window(current: PeriodRef, lookback_periods: int = 2) -> dict:
    periods: list[PeriodRef] = []
    for i in range(lookback_periods, -1, -1):
        periods.append(shift_period(current, -i))
    oldest = periods[0]
    newest = periods[-1]
    return {
        "start_date": period_date_bounds(oldest)["start"],
        "end_date": period_date_bounds(newest)["end"],
        "periods": periods,
    }
