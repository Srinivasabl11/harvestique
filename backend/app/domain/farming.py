"""Pure farming rules: no I/O, no framework imports. Unit-testable in isolation.

* crop-cycle status state machine
* date helpers (clock-independent: callers pass `today`)
* land capacity: the peak area simultaneously occupied on a plot
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.core.enums import CycleStatus

# ------------------------------------------------------------ status machine

CYCLE_TRANSITIONS: dict[CycleStatus, frozenset[CycleStatus]] = {
    CycleStatus.PLANNED: frozenset({CycleStatus.GROWING, CycleStatus.ABANDONED}),
    CycleStatus.GROWING: frozenset({CycleStatus.HARVESTED, CycleStatus.ABANDONED}),
    CycleStatus.HARVESTED: frozenset(),
    CycleStatus.ABANDONED: frozenset(),
}
TERMINAL_STATUSES = frozenset({CycleStatus.HARVESTED, CycleStatus.ABANDONED})


def can_transition(current: CycleStatus, new: CycleStatus) -> bool:
    """True if `new` is the same status (no-op) or a permitted forward move."""
    return new == current or new in CYCLE_TRANSITIONS[current]


# -------------------------------------------------------------------- dates

# Users are in India (UTC+5:30) while the server clock is UTC: just after midnight IST the
# server's "today" is still yesterday. One day of tolerance avoids rejecting a farmer's
# legitimate "today" entry.
FUTURE_TOLERANCE = timedelta(days=1)


def is_in_future(day: date, today: date) -> bool:
    return day > today + FUTURE_TOLERANCE


def cycle_end_date(
    *,
    sowing: date,
    expected_harvest: date | None,
    actual_harvest: date | None,
    typical_duration_days: int,
) -> date:
    """Last day the cycle occupies its land: actual > expected > sowing + crop's typical duration."""
    if actual_harvest is not None:
        return actual_harvest
    if expected_harvest is not None:
        return expected_harvest
    return sowing + timedelta(days=typical_duration_days)


# ------------------------------------------------------------ land capacity


@dataclass(frozen=True, slots=True)
class Occupancy:
    """`area` acres of a plot used over the inclusive date range [start, end]."""

    start: date
    end: date
    area: Decimal


def peak_concurrent_area(items: Iterable[Occupancy]) -> Decimal:
    """Maximum area in use at any single moment (sweep line over inclusive ranges).

    Summing every overlapping pair would wrongly reject A->B->C sequences where A overlaps B and
    B overlaps C but A and C never coexist; the sweep gives the exact peak.
    """
    events: list[tuple[date, int, Decimal]] = []
    for item in items:
        events.append((item.start, 1, item.area))
        events.append((item.end + timedelta(days=1), 0, -item.area))  # frees the land the day after `end`
    events.sort(key=lambda e: (e[0], e[1]))  # at equal dates, releases (0) are processed before additions (1)

    current = peak = Decimal(0)
    for _, _, delta in events:
        current += delta
        peak = max(peak, current)
    return peak
