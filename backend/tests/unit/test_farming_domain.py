from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.enums import CycleStatus
from app.domain.farming import (
    TERMINAL_STATUSES,
    Occupancy,
    can_transition,
    cycle_end_date,
    is_in_future,
    peak_concurrent_area,
)

D = Decimal
P, G, H, A = CycleStatus.PLANNED, CycleStatus.GROWING, CycleStatus.HARVESTED, CycleStatus.ABANDONED


# ------------------------------------------------------------ state machine


@pytest.mark.parametrize(
    ("current", "new", "allowed"),
    [
        (P, G, True),
        (P, A, True),
        (G, H, True),
        (G, A, True),
        (P, H, False),  # cannot harvest what was never sown
        (G, P, False),  # no going back
        (H, G, False),
        (H, A, False),
        (A, P, False),
        (A, G, False),
    ],
)
def test_transitions(current, new, allowed):
    assert can_transition(current, new) is allowed


@pytest.mark.parametrize("status", list(CycleStatus))
def test_staying_in_the_same_status_is_always_allowed(status):
    assert can_transition(status, status)


def test_terminal_statuses():
    assert {H, A} == TERMINAL_STATUSES


# --------------------------------------------------------------------- dates

TODAY = date(2026, 10, 7)


def test_future_tolerance_is_one_day():
    assert not is_in_future(TODAY, TODAY)
    assert not is_in_future(TODAY + timedelta(days=1), TODAY)  # IST is ahead of UTC
    assert is_in_future(TODAY + timedelta(days=2), TODAY)


def test_cycle_end_date_precedence():
    sow = date(2026, 1, 1)
    kw = {"sowing": sow, "typical_duration_days": 100}
    assert cycle_end_date(expected_harvest=None, actual_harvest=None, **kw) == sow + timedelta(days=100)
    assert cycle_end_date(expected_harvest=date(2026, 3, 1), actual_harvest=None, **kw) == date(2026, 3, 1)
    assert cycle_end_date(expected_harvest=date(2026, 3, 1), actual_harvest=date(2026, 2, 20), **kw) == date(
        2026, 2, 20
    )


# ------------------------------------------------------------ land capacity


def occ(start, end, area):
    return Occupancy(start=date.fromisoformat(start), end=date.fromisoformat(end), area=D(area))


def test_no_cycles_means_no_land_in_use():
    assert peak_concurrent_area([]) == 0


def test_single_cycle():
    assert peak_concurrent_area([occ("2026-01-01", "2026-03-01", "2.5")]) == D("2.5")


def test_overlapping_cycles_add_up():
    items = [occ("2026-01-01", "2026-03-01", "2"), occ("2026-02-01", "2026-04-01", "1.5")]
    assert peak_concurrent_area(items) == D("3.5")


def test_sequential_cycles_reuse_the_same_land():
    items = [occ("2026-01-01", "2026-03-31", "4"), occ("2026-04-01", "2026-07-01", "4")]
    assert peak_concurrent_area(items) == D("4")


def test_end_date_is_inclusive():
    """A cycle ending on the 10th still occupies the land that day."""
    sharing_a_day = [occ("2026-01-01", "2026-01-10", "4"), occ("2026-01-10", "2026-02-01", "4")]
    next_day = [occ("2026-01-01", "2026-01-10", "4"), occ("2026-01-11", "2026-02-01", "4")]
    assert peak_concurrent_area(sharing_a_day) == D("8")
    assert peak_concurrent_area(next_day) == D("4")


def test_chain_is_not_double_counted():
    """A overlaps B and A overlaps C, but B and C never coexist: peak is A+B, not A+B+C."""
    a = occ("2026-01-01", "2026-06-30", "2")
    b = occ("2026-01-15", "2026-02-15", "1")
    c = occ("2026-04-01", "2026-05-01", "1")
    assert peak_concurrent_area([a, b, c]) == D("3")  # naive pairwise summing would say 4


def test_decimal_arithmetic_is_exact():
    items = [occ("2026-01-01", "2026-01-31", "0.1"), occ("2026-01-01", "2026-01-31", "0.2")]
    assert peak_concurrent_area(items) == D("0.3")
