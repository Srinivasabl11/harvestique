"""Land use over time, staggered planting and income continuity."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.core.enums import ContinuityLevel
from app.domain.farming import Occupancy, peak_concurrent_area
from app.domain.planning import evaluate_plan
from app.domain.planning.timeline import UsageProfile, days_per_month, months_between
from tests.planning_factory import item, plan, simple


def occ(start, end, area):
    return Occupancy(date.fromisoformat(start), date.fromisoformat(end), D(str(area)))


# ------------------------------------------------------------------- helpers


def test_days_per_month_splits_a_range_at_month_ends():
    assert days_per_month(date(2027, 1, 26), date(2027, 2, 4)) == {(2027, 1): 6, (2027, 2): 4}
    assert days_per_month(date(2027, 3, 5), date(2027, 3, 5)) == {(2027, 3): 1}
    assert days_per_month(date(2026, 12, 30), date(2027, 1, 2)) == {(2026, 12): 2, (2027, 1): 2}  # year boundary


def test_days_per_month_handles_february_in_leap_years():
    assert days_per_month(date(2028, 2, 1), date(2028, 2, 29)) == {(2028, 2): 29}
    assert days_per_month(date(2027, 2, 1), date(2027, 2, 28)) == {(2027, 2): 28}


def test_months_between_crosses_years():
    assert months_between((2026, 11), (2027, 2)) == [(2026, 11), (2026, 12), (2027, 1), (2027, 2)]


# ------------------------------------------------------------- usage profile


def test_usage_profile_levels_and_boundaries():
    p = UsageProfile.build([occ("2026-01-10", "2026-01-20", 2), occ("2026-01-15", "2026-01-25", 3)])
    assert p.at(date(2026, 1, 9)) == 0
    assert p.at(date(2026, 1, 10)) == 2
    assert p.at(date(2026, 1, 15)) == 5
    assert p.at(date(2026, 1, 20)) == 5  # the end day is still occupied
    assert p.at(date(2026, 1, 21)) == 3
    assert p.at(date(2026, 1, 26)) == 0
    assert p.overall_peak() == 5


def test_usage_profile_window_peak():
    p = UsageProfile.build([occ("2026-01-10", "2026-01-20", 2), occ("2026-01-15", "2026-01-25", 3)])
    assert p.peak(date(2026, 1, 1), date(2026, 1, 12)) == 2
    assert p.peak(date(2026, 1, 21), date(2026, 1, 30)) == 3
    assert p.peak(date(2026, 1, 26), date(2026, 2, 5)) == 0
    assert p.peak(date(2026, 1, 12), date(2026, 1, 16)) == 5


def test_usage_profile_agrees_with_the_phase2_peak_algorithm():
    """Two independent implementations of 'peak concurrent area' must always agree."""
    base = date(2026, 1, 1)
    for seed in range(40):
        items = [
            Occupancy(
                base + timedelta(days=(seed * 7 + i * 31) % 200),
                base + timedelta(days=(seed * 7 + i * 31) % 200 + 20 + (seed + i * 13) % 90),
                D((seed + i) % 5 + 1) / 2,
            )
            for i in range(1 + seed % 6)
        ]
        assert UsageProfile.build(items).overall_peak() == peak_concurrent_area(items), seed


def test_first_day_over_limit():
    p = UsageProfile.build([occ("2026-01-10", "2026-01-20", 2), occ("2026-01-15", "2026-01-25", 3)])
    assert p.first_day_over(D(4)) == date(2026, 1, 15)
    assert p.first_day_over(D(5)) is None


# ----------------------------------------------------------- staggered planting


def test_staggering_reduces_the_peak_land_needed():
    kw = dict(area=3, duration_days=60, harvest_window_days=10)
    together = evaluate_plan(plan(simple(**kw), land=3))
    staggered = evaluate_plan(plan(simple(**kw, batches=3, batch_interval_days=90), land=3))
    assert together.land.peak_in_use_acres == D(3)
    assert staggered.land.peak_in_use_acres == D(1)  # one acre at a time: 60 + 10 days < 90-day interval


def test_overlapping_batches_add_up():
    r = evaluate_plan(
        plan(simple(area=3, duration_days=60, harvest_window_days=10, batches=3, batch_interval_days=30), land=3)
    )
    # batch windows are 70 days long, 30 days apart: three batches overlap for a while
    assert r.land.peak_in_use_acres == D(3)


def test_staggering_makes_a_plan_feasible_that_was_not():
    kw = dict(area=3, duration_days=60, harvest_window_days=10)
    assert evaluate_plan(plan(simple(**kw), simple(**kw), land=4)).feasible is False  # 6 acres at once on 4
    assert evaluate_plan(plan(simple(**kw, batches=3, batch_interval_days=100), simple(**kw), land=4)).feasible is True


def test_staggering_spreads_income_across_more_months():
    one = evaluate_plan(plan(simple(area=2, duration_days=30, harvest_window_days=5))).continuity
    staggered = evaluate_plan(
        plan(simple(area=2, duration_days=30, harvest_window_days=5, batches=2, batch_interval_days=45))
    ).continuity
    assert one.income_months == 1 and one.level is ContinuityLevel.SINGLE_HARVEST
    assert staggered.income_months == 2


def test_each_batch_gets_its_share_of_revenue():
    r = evaluate_plan(plan(simple(area=2, y=1000, price=10, batches=2, batch_interval_days=60, duration_days=30)))
    assert sum(m.income.expected for m in r.continuity.monthly) == D("20000.00")


# ------------------------------------------------------- income, month by month


def test_revenue_is_split_by_days_across_month_boundaries():
    # harvest Jan 26 - Feb 4: 6 of 10 days in January, 4 in February
    r = evaluate_plan(
        plan(simple(area=1, y=1000, price=10, sowing_date=date(2027, 1, 1), duration_days=25, harvest_window_days=10))
    )
    jan, feb = r.continuity.monthly
    assert (jan.month, jan.income.expected) == ("2027-01", D("6000.00"))
    assert (feb.month, feb.income.expected) == ("2027-02", D("4000.00"))


def test_cost_falls_in_the_sowing_month_and_cumulative_net_is_tracked():
    r = evaluate_plan(
        plan(
            simple(
                area=1,
                y=1000,
                price=10,
                cost_per_acre=2000,
                sowing_date=date(2027, 1, 1),
                duration_days=25,
                harvest_window_days=10,
            )
        )
    )
    jan, feb = r.continuity.monthly
    assert (jan.cost_expected, jan.net_expected, jan.cumulative_net_expected) == (
        D("2000.00"),
        D("4000.00"),
        D("4000.00"),
    )
    assert (feb.cost_expected, feb.net_expected, feb.cumulative_net_expected) == (D("0.00"), D("4000.00"), D("8000.00"))
    assert feb.cumulative_net_expected == r.totals.margin.expected  # 10,000 revenue - 2,000 cost


def test_monthly_income_sums_to_plan_revenue():
    r = evaluate_plan(plan(item(batches=3, batch_interval_days=40), land=5))
    for pick in ("low", "expected", "high"):
        total = sum(getattr(m.income, pick) for m in r.continuity.monthly)
        assert abs(total - getattr(r.totals.revenue, pick)) < D("0.05")  # only paise rounding differs


def test_months_cover_the_whole_planning_period():
    r = evaluate_plan(plan(item(batches=3, batch_interval_days=40), land=5))
    months = [m.month for m in r.continuity.monthly]
    assert months[0] == r.period.start.strftime("%Y-%m") and months[-1] == r.period.end.strftime("%Y-%m")
    assert len(months) == r.period.months == len(set(months))


# ------------------------------------------------------------- continuity levels


def harvest_in(month: int, **kw):
    """A 1-acre crop earning 10,000 whose 1-day harvest falls on the 15th of `month` (2027)."""
    sow = date(2027, month, 15) - timedelta(days=30)
    return simple(area=1, y=1000, price=10, sowing_date=sow, duration_days=30, harvest_window_days=1, **kw)


def test_continuous_income_has_no_gaps():
    c = evaluate_plan(
        plan(harvest_in(3, crop_name="A"), harvest_in(4, crop_name="B"), harvest_in(5, crop_name="C"))
    ).continuity
    assert c.level is ContinuityLevel.CONTINUOUS and c.gap_months == 0 and c.income_months == c.span_months == 3
    assert c.largest_month_share_pct == D("33.33")


def test_gaps_between_harvests_are_found_and_named():
    c = evaluate_plan(plan(harvest_in(3, crop_name="A"), harvest_in(7, crop_name="B"))).continuity
    assert c.level is ContinuityLevel.GAPPED
    assert c.gap_month_list == ("2027-04", "2027-05", "2027-06")
    assert (c.gap_months, c.longest_gap_months, c.span_months, c.income_months) == (3, 3, 5, 2)


def test_longest_gap_is_the_longest_run():
    c = evaluate_plan(
        plan(
            harvest_in(1, crop_name="A"),
            harvest_in(3, crop_name="B"),
            harvest_in(7, crop_name="C"),
            harvest_in(8, crop_name="D"),
        )
    ).continuity
    assert c.gap_month_list == ("2027-02", "2027-04", "2027-05", "2027-06") and c.longest_gap_months == 3


def test_single_harvest_is_flagged():
    c = evaluate_plan(plan(harvest_in(3))).continuity
    assert c.level is ContinuityLevel.SINGLE_HARVEST and c.span_months == 1 and c.gap_months == 0
    assert any("single month" in a for a in c.advice)


def test_uneven_income_when_one_month_dominates():
    big = simple(
        area=4,
        y=1000,
        price=10,
        sowing_date=date(2027, 2, 13),
        duration_days=30,
        harvest_window_days=1,
        crop_name="Big",
    )
    c = evaluate_plan(plan(big, harvest_in(4, crop_name="Small"), land=10)).continuity  # 40,000 vs 10,000: 80% in March
    assert c.level is ContinuityLevel.UNEVEN and c.largest_month_share_pct == D("80.00")
    assert any("80%" in a for a in c.advice)


def test_lead_time_before_the_first_income():
    c = evaluate_plan(plan(harvest_in(5))).continuity  # sown mid-April, first income in May
    assert c.lead_months == 1 and any("first income" in a for a in c.advice)
    soon = evaluate_plan(
        plan(simple(area=1, sowing_date=date(2027, 3, 1), duration_days=10, harvest_window_days=1))
    ).continuity
    assert soon.lead_months == 0 and not any("first income" in a for a in soon.advice)


def test_gap_advice_mentions_the_months():
    c = evaluate_plan(plan(harvest_in(3, crop_name="A"), harvest_in(7, crop_name="B"))).continuity
    assert any("2027-04" in a and "Staggering" in a for a in c.advice)


# ------------------------------------------------------------ funding / cash flow


def test_peak_funding_is_lower_than_total_cost_when_income_is_reinvested():
    """A: spend 1,000 in Jan, earn 3,000 in Feb.  B: spend 2,000 in Mar, earn 5,000 in Apr.
    Cumulative: Jan -1,000 | Feb +2,000 | Mar 0 | Apr +5,000  ->  deepest shortfall 1,000 (total cost is 3,000)."""

    def crop(name, sow, cost, price):
        return simple(
            crop_name=name,
            area=1,
            y=1000,
            price=price,
            cost_per_acre=cost,
            sowing_date=sow,
            duration_days=30,
            harvest_window_days=1,
        )

    a = crop("A", date(2027, 1, 10), 1000, 3)  # harvest Feb 9
    b = crop("B", date(2027, 3, 10), 2000, 5)  # harvest Apr 9
    r = evaluate_plan(plan(a, b))
    assert r.totals.cost.expected == D(3000)
    assert r.continuity.peak_funding_required == D("1000.00")
    cumulative = {m.month: m.cumulative_net_expected for m in r.continuity.monthly}
    assert cumulative == {
        "2027-01": D("-1000.00"),
        "2027-02": D("2000.00"),
        "2027-03": D("0.00"),
        "2027-04": D("5000.00"),
    }


def test_peak_funding_equals_total_cost_when_nothing_is_earned_early():
    r = evaluate_plan(
        plan(
            simple(
                area=1,
                y=1000,
                price=10,
                cost_per_acre=4000,
                sowing_date=date(2027, 1, 1),
                duration_days=90,
                harvest_window_days=1,
            )
        )
    )
    assert r.continuity.peak_funding_required == D("4000.00")


@pytest.mark.parametrize("cost", [0, 1500])
def test_peak_funding_is_never_negative(cost):
    r = evaluate_plan(plan(simple(area=1, cost_per_acre=cost)))
    assert r.continuity.peak_funding_required >= 0
