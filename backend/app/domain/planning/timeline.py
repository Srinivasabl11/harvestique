"""Calendar logic: when land is occupied and when money moves.

* LAND  - a batch occupies its area from the sowing day through the LAST day of its harvest window.
* INCOME - a batch's revenue is spread evenly over the days of its harvest window and counted in the
           months those days fall in (no payment delay is assumed).
* COST  - a batch's share of the item cost falls in its sowing month.
"""

from __future__ import annotations

import calendar
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.core.enums import ContinuityLevel
from app.domain.farming import Occupancy
from app.domain.planning.calculator import HUNDRED, MONEY, PCT, QTY, Economics, inr, num, q, qt
from app.domain.planning.models import (
    ZERO,
    BatchSchedule,
    D,
    IncomeContinuity,
    ItemInput,
    LandMonth,
    LandUtilization,
    MonthlyFlow,
    PlanningPeriod,
    Triple,
)

Month = tuple[int, int]  # (year, month)


def month_key(month: Month) -> str:
    return f"{month[0]:04d}-{month[1]:02d}"


def month_of(day: date) -> Month:
    return day.year, day.month


def months_between(first: Month, last: Month) -> list[Month]:
    out: list[Month] = []
    y, m = first
    while (y, m) <= last:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def month_bounds(month: Month) -> tuple[date, date]:
    return date(month[0], month[1], 1), date(month[0], month[1], calendar.monthrange(*month)[1])


def days_per_month(start: date, end: date) -> dict[Month, int]:
    """How many days of the inclusive range [start, end] fall in each calendar month."""
    out: dict[Month, int] = {}
    cur = start
    while cur <= end:
        _, month_end = month_bounds(month_of(cur))
        seg_end = min(end, month_end)
        out[month_of(cur)] = (seg_end - cur).days + 1
        cur = seg_end + timedelta(days=1)
    return out


# ----------------------------------------------------------------- land use


@dataclass(frozen=True, slots=True)
class UsageProfile:
    """Land in use over time as a step function: `levels[i]` applies from `dates[i]` until the next date."""

    dates: tuple[date, ...]
    levels: tuple[Decimal, ...]

    @classmethod
    def build(cls, occupancies: Sequence[Occupancy]) -> UsageProfile:
        deltas: dict[date, Decimal] = defaultdict(lambda: ZERO)
        for o in occupancies:
            deltas[o.start] += o.area
            deltas[o.end + timedelta(days=1)] -= o.area  # freed the day after the last occupied day
        dates, levels, running = [], [], ZERO
        for day in sorted(deltas):
            running += deltas[day]
            dates.append(day)
            levels.append(running)
        return cls(tuple(dates), tuple(levels))

    def at(self, day: date) -> Decimal:
        i = bisect_right(self.dates, day) - 1
        return ZERO if i < 0 else self.levels[i]

    def peak(self, start: date, end: date) -> Decimal:
        """Highest usage on any day of [start, end]."""
        peak = self.at(start)
        for i in range(bisect_right(self.dates, start), bisect_right(self.dates, end)):
            peak = max(peak, self.levels[i])
        return peak

    def overall_peak(self) -> Decimal:
        return max(self.levels, default=ZERO)

    def first_day_over(self, limit: Decimal) -> date | None:
        for day, level in zip(self.dates, self.levels, strict=True):
            if level > limit:
                return day
        return None


def occupancies_of(item_batches: Sequence[Sequence[BatchSchedule]]) -> list[Occupancy]:
    return [Occupancy(b.sowing_date, b.harvest_end, b.area_acres) for batches in item_batches for b in batches]


def period_of(item_batches: Sequence[Sequence[BatchSchedule]]) -> PlanningPeriod:
    starts = [b.sowing_date for batches in item_batches for b in batches]
    ends = [b.harvest_end for batches in item_batches for b in batches]
    start, end = min(starts), max(ends)
    return PlanningPeriod(start, end, (end - start).days + 1, len(months_between(month_of(start), month_of(end))))


def land_utilization(occupancies: Sequence[Occupancy], available: Decimal, period: PlanningPeriod) -> LandUtilization:
    profile = UsageProfile.build(occupancies)
    peak = profile.overall_peak()

    area_days = sum(((o.end - o.start).days + 1) * o.area for o in occupancies)
    average_pct = area_days / (available * period.days) * HUNDRED

    monthly: list[LandMonth] = []
    for month in months_between(month_of(period.start), month_of(period.end)):
        first, last = month_bounds(month)
        used = sum(
            (max(0, (min(last, o.end) - max(first, o.start)).days + 1) * o.area for o in occupancies),
            ZERO,
        )
        days = (last - first).days + 1
        month_peak = profile.peak(first, last)
        monthly.append(
            LandMonth(
                month_key(month), q(month_peak, QTY), q(used / days, QTY), q(month_peak / available * HUNDRED, PCT)
            )
        )

    return LandUtilization(
        available_acres=available,
        peak_in_use_acres=q(peak, QTY),
        peak_utilization_pct=q(peak / available * HUNDRED, PCT),
        average_utilization_pct=q(average_pct, PCT),
        unused_at_peak_acres=q(available - peak, QTY),
        first_over_limit_on=profile.first_day_over(available),
        monthly=tuple(monthly),
    )


# -------------------------------------------------------------- cash flow


def income_continuity(
    items: Sequence[ItemInput],
    item_batches: Sequence[Sequence[BatchSchedule]],
    economics: Sequence[Economics],
    period: PlanningPeriod,
) -> IncomeContinuity:
    income: dict[Month, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO, ZERO])
    cost: dict[Month, Decimal] = defaultdict(lambda: ZERO)

    for item, batches, econ in zip(items, item_batches, economics, strict=True):
        for b in batches:
            share = b.area_acres / item.area_acres
            cost[month_of(b.sowing_date)] += econ.cost_expected * share
            window_days = (b.harvest_end - b.harvest_start).days + 1
            for month, days in days_per_month(b.harvest_start, b.harvest_end).items():
                portion = share * D(days) / D(window_days)
                row = income[month]
                row[0] += econ.revenue.low * portion
                row[1] += econ.revenue.expected * portion
                row[2] += econ.revenue.high * portion

    months = months_between(month_of(period.start), month_of(period.end))
    flows: list[MonthlyFlow] = []
    cumulative = ZERO
    deepest = ZERO
    for month in months:
        low, expected, high = income.get(month, [ZERO, ZERO, ZERO])
        month_cost = cost.get(month, ZERO)
        cumulative -= month_cost  # costs are assumed to land before the month's income
        deepest = min(deepest, cumulative)
        cumulative += expected
        flows.append(
            MonthlyFlow(
                month=month_key(month),
                income=qt(Triple(low, expected, high), MONEY),
                cost_expected=q(month_cost, MONEY),
                net_expected=q(expected - month_cost, MONEY),
                cumulative_net_expected=q(cumulative, MONEY),
            )
        )

    paying = [i for i, m in enumerate(months) if income.get(m, [ZERO, ZERO, ZERO])[1] > 0]
    paying_set = set(paying)
    first_i, last_i = paying[0], paying[-1]  # never empty: every crop has a positive expected revenue
    span = last_i - first_i + 1
    income_months = len(paying)
    in_span = range(first_i, last_i + 1)
    gap_months_list = [month_key(months[i]) for i in in_span if i not in paying_set]
    longest = _longest_run([i not in paying_set for i in in_span])

    total = sum((income[m][1] for m in income), ZERO)
    largest_share = max(income[m][1] for m in income) / total * HUNDRED if total > 0 else HUNDRED

    if span == 1:
        level = ContinuityLevel.SINGLE_HARVEST
    elif gap_months_list:
        level = ContinuityLevel.GAPPED
    elif largest_share > 50:
        level = ContinuityLevel.UNEVEN
    else:
        level = ContinuityLevel.CONTINUOUS

    return IncomeContinuity(
        level=level,
        monthly=tuple(flows),
        income_months=income_months,
        span_months=span,
        lead_months=first_i,
        gap_months=len(gap_months_list),
        gap_month_list=tuple(gap_months_list),
        longest_gap_months=longest,
        largest_month_share_pct=q(largest_share, PCT),
        peak_funding_required=q(-deepest, MONEY),
        advice=_advice(level, months, first_i, gap_months_list, largest_share, -deepest),
    )


def _longest_run(flags: Sequence[bool]) -> int:
    best = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def _advice(
    level: ContinuityLevel,
    months: Sequence[Month],
    first_income_index: int,
    gaps: Sequence[str],
    largest_share: Decimal,
    peak_funding: Decimal,
) -> tuple[str, ...]:
    advice: list[str] = []
    if first_income_index > 0:
        advice.append(
            f"The first income is expected about {first_income_index} month(s) after the first sowing "
            f"({month_key(months[first_income_index])}); you must be able to fund that wait."
        )
    if level is ContinuityLevel.GAPPED:
        advice.append(
            f"No income is expected in {len(gaps)} month(s) between harvests ({', '.join(gaps)}). "
            "Staggering sowing dates or adding a crop that harvests in those months would smooth this."
        )
    elif level is ContinuityLevel.SINGLE_HARVEST:
        advice.append("All income arrives in a single month; staggered sowing (batches) would spread it out.")
    elif level is ContinuityLevel.UNEVEN:
        advice.append(
            f"{num(largest_share, 0)}% of expected income arrives in one month; spreading sowing dates would even it out."
        )
    else:
        advice.append("Expected income arrives in every month between the first and last harvest.")
    if peak_funding > 0:
        advice.append(
            f"If income is reinvested as it arrives, the deepest cumulative cash shortfall is about {inr(peak_funding)}."
        )
    return tuple(advice)
