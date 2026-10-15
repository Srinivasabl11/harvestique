"""Cost and income arithmetic, checked against hand calculation."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from app.core.enums import RiskLevel
from app.domain.planning import CostInputs, ItemInput, PlanningInputError, Range, evaluate_plan
from app.domain.planning.calculator import (
    DEFAULT_OVERRUN_PCT,
    batch_schedules,
    compute_economics,
    cost_per_acre,
    q,
    split_area,
)
from tests.planning_factory import TOMATO_COST, item, plan, rng, simple

# ------------------------------------------------------------- the worked example


def test_cost_per_acre_splits_inputs_and_labour():
    total, inputs, labour = cost_per_acre(TOMATO_COST)
    assert (inputs, labour, total) == (D(17000), D(24000), D(41000))  # 60 person-days x 400 = 24,000


def test_expected_and_high_cost():
    e = compute_economics(item())
    assert e.cost_expected == D(87000)  # 41,000 x 2 acres + 5,000 fixed
    assert e.overrun_pct == D(10)  # medium risk default
    assert e.cost_high == D(95700)  # 87,000 x 1.10


def test_cost_breakdown_adds_up_to_the_expected_cost():
    e = compute_economics(item())
    assert e.breakdown == {
        "seed": D(8000),
        "fertilizer": D(12000),
        "pesticide": D(6000),
        "irrigation": D(4000),
        "machinery": D(3000),
        "other": D(1000),
        "labour": D(48000),
        "fixed": D(5000),
    }
    assert sum(e.breakdown.values()) == e.cost_expected


def test_production_revenue_and_margin_ranges():
    e = compute_economics(item())
    assert (e.production.low, e.production.expected, e.production.high) == (D(16000), D(24000), D(32000))
    assert (e.revenue.low, e.revenue.expected, e.revenue.high) == (D(128000), D(288000), D(576000))
    # worst case = lowest revenue - HIGH cost; best case keeps the expected cost
    assert e.margin.low == D(128000) - D(95700) == D(32300)
    assert e.margin.expected == D(288000) - D(87000) == D(201000)
    assert e.margin.high == D(576000) - D(87000) == D(489000)


def test_break_even_figures():
    e = compute_economics(item())
    assert e.be_price_expected == D(87000) / D(24000) == D("3.625")
    assert e.be_price_conservative == D(95700) / D(16000) == D("5.98125")
    assert e.be_yield_per_acre == D(87000) / (D(12) * D(2)) == D(3625)
    assert q(e.margin_of_safety_pct, D("0.01")) == D("69.79")  # (12,000 - 3,625) / 12,000
    assert q(e.roi_pct, D("0.01")) == D("231.03")  # 201,000 / 87,000


def test_result_rounds_half_up_to_paise():
    r = evaluate_plan(plan(item())).items[0]
    assert r.break_even.price_per_kg_expected == D("3.63")  # 3.625 -> half-up
    assert r.break_even.price_per_kg_conservative == D("5.98")
    assert r.break_even.yield_kg_per_acre == D("3625.000")
    assert r.roi_expected_pct == D("231.03")
    assert r.cost.expected == D("87000.00") and r.cost.high == D("95700.00")


def test_pessimistic_never_exceeds_expected_never_exceeds_optimistic():
    for r in evaluate_plan(plan(item())).items:
        assert r.revenue.low <= r.revenue.expected <= r.revenue.high
        assert r.margin.low <= r.margin.expected <= r.margin.high


# --------------------------------------------------------------------- overrun


@pytest.mark.parametrize("risk", list(RiskLevel))
def test_default_overrun_follows_declared_risk(risk):
    e = compute_economics(item(declared_risk=risk))
    assert e.overrun_pct == DEFAULT_OVERRUN_PCT[risk]
    assert e.cost_high == e.cost_expected * (1 + DEFAULT_OVERRUN_PCT[risk] / 100)


def test_default_overrun_values():
    assert {RiskLevel.LOW: D(5), RiskLevel.MEDIUM: D(10), RiskLevel.HIGH: D(20)} == DEFAULT_OVERRUN_PCT


def test_explicit_overrun_overrides_the_default():
    e = compute_economics(item(cost=replace(TOMATO_COST, overrun_pct=D(25))))
    assert e.cost_high == D(87000) * D("1.25") == D(108750)


def test_zero_overrun_means_high_cost_equals_expected():
    e = compute_economics(item(cost=replace(TOMATO_COST, overrun_pct=D(0))))
    assert e.cost_high == e.cost_expected


# ---------------------------------------------------------------------- demand


def test_demand_cap_limits_sold_quantity_and_revenue():
    e = compute_economics(item(demand_quantity_kg=D(20000)))
    assert (e.sold.low, e.sold.expected, e.sold.high) == (D(16000), D(20000), D(20000))
    assert (e.revenue.low, e.revenue.expected, e.revenue.high) == (D(128000), D(240000), D(360000))
    assert e.demand_limited is True
    assert e.be_price_expected == D(87000) / D(20000) == D("4.35")


def test_demand_above_production_changes_nothing():
    capped, free = compute_economics(item(demand_quantity_kg=D(99999))), compute_economics(item())
    assert capped.revenue == free.revenue and capped.demand_limited is False


def test_demand_exactly_equal_to_expected_production_is_not_limited():
    assert compute_economics(item(demand_quantity_kg=D(24000))).demand_limited is False


# --------------------------------------------------------------- edge economics


def test_total_crop_failure_case():
    e = compute_economics(item(yield_per_acre_kg=rng(0, 12000, 16000)))
    assert e.revenue.low == 0
    assert e.margin.low == -e.cost_high  # lose everything spent, including the overrun
    assert e.be_price_conservative is None  # nothing sold in the low case: no meaningful break-even price


def test_zero_cost_plan_has_no_roi_and_zero_break_even():
    e = compute_economics(simple())
    assert e.cost_expected == 0 and e.roi_pct is None and e.be_price_expected == 0
    assert e.margin.expected == e.revenue.expected == D(10000)


def test_fixed_cost_does_not_scale_with_area():
    one = compute_economics(simple(area=1, cost_per_acre=100, fixed=500))
    two = compute_economics(simple(area=2, cost_per_acre=100, fixed=500))
    assert (one.cost_expected, two.cost_expected) == (D(600), D(700))


def test_labour_cost_is_person_days_times_wage():
    c = CostInputs(labour_person_days_per_acre=D("12.5"), labour_wage_per_day=D(380))
    assert cost_per_acre(c) == (D(4750), D(0), D(4750))


def test_a_loss_making_crop_reports_negative_margin():
    e = compute_economics(simple(area=1, y=100, price=5, cost_per_acre=1000))
    assert e.margin.expected == D(500) - D(1000) == D(-500)
    assert e.roi_pct == D(-50)


# ----------------------------------------------------------------- explanations


def test_explanations_show_the_working():
    text = " ".join(evaluate_plan(plan(item(demand_quantity_kg=D(20000)))).items[0].explanations)
    for expected in (
        "₹41,000.00",
        "₹87,000.00",
        "₹95,700.00",
        "10.00% overrun",
        "60.00 person-days",
        "Demand is limited to 20,000 kg",
    ):
        assert expected in text, expected


def test_no_demand_sentence_when_not_limited():
    assert "Demand is limited" not in " ".join(evaluate_plan(plan(item())).items[0].explanations)


# ---------------------------------------------------------------------- batches


def test_split_area_equal_shares_with_remainder_on_the_last():
    assert split_area(D("3.000"), 3) == [D("1.000")] * 3
    areas = split_area(D("1.000"), 3)
    assert areas == [D("0.333"), D("0.333"), D("0.334")] and sum(areas) == D("1.000")


def test_batch_schedule_dates_follow_the_interval():
    schedule = batch_schedules(
        item(area_acres=D(3), batches=3, batch_interval_days=30, duration_days=100, harvest_window_days=10)
    )
    assert [b.sowing_date for b in schedule] == [date(2026, 11, 1), date(2026, 12, 1), date(2026, 12, 31)]
    first = schedule[0]
    assert first.harvest_start == date(2027, 2, 9) and first.harvest_end == date(
        2027, 2, 18
    )  # sow + 100 d, 10-day window
    assert [b.area_acres for b in schedule] == [D(1)] * 3


def test_single_batch_schedule():
    (b,) = batch_schedules(item())
    assert (b.sowing_date, b.area_acres) == (date(2026, 11, 1), D(2))
    assert b.harvest_end == date(2027, 3, 10)  # 30-day window starting Feb 9


def test_batches_do_not_change_totals():
    whole, staggered = (
        evaluate_plan(plan(item())).items[0],
        evaluate_plan(plan(item(batches=4, batch_interval_days=20))).items[0],
    )
    assert whole.cost == staggered.cost and whole.revenue == staggered.revenue and whole.margin == staggered.margin


# ------------------------------------------------------------------ invalid input


@pytest.mark.parametrize(
    ("args", "code"),
    [
        ((-1, 5, 6), "range_negative"),
        ((9, 5, 12), "range_not_ordered"),  # low > expected
        ((5, 9, 7), "range_not_ordered"),  # expected > high
        ((0, 0, 0), "range_expected_not_positive"),
        ((0, 0, 5), "range_expected_not_positive"),
    ],
)
def test_invalid_ranges_are_rejected(args, code):
    with pytest.raises(PlanningInputError) as exc:
        Range(*(D(a) for a in args))
    assert exc.value.code == code


def test_a_single_point_range_is_allowed():
    assert Range(D(5), D(5), D(5)).spread == 0


def test_range_spread():
    assert rng(8000, 12000, 16000).spread == D(8000) / D(12000)


@pytest.mark.parametrize(
    "field",
    ["seed", "fertilizer", "pesticide", "irrigation", "machinery", "other", "fixed_cost", "labour_wage_per_day"],
)
def test_negative_costs_are_rejected(field):
    with pytest.raises(PlanningInputError) as exc:
        CostInputs(**{field: D(-1)})
    assert exc.value.code == "cost_negative"


def test_negative_overrun_is_rejected():
    with pytest.raises(PlanningInputError, match="overrun"):
        CostInputs(overrun_pct=D(-1))


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"area_acres": D(0)}, "area_not_positive"),
        ({"area_acres": D(-2)}, "area_not_positive"),
        ({"area_acres": D("1.2345")}, "area_precision"),
        ({"duration_days": 0}, "duration_not_positive"),
        ({"harvest_window_days": 0}, "harvest_window_invalid"),
        ({"harvest_window_days": 366}, "harvest_window_invalid"),
        ({"batches": 0}, "batches_invalid"),
        ({"batches": 13}, "batches_invalid"),
        ({"batches": 3}, "batch_interval_required"),
        ({"batches": 3, "batch_interval_days": 0}, "batch_interval_required"),
        ({"demand_quantity_kg": D(0)}, "demand_quantity_not_positive"),
        ({"water_kl_per_acre": D(-1)}, "water_negative"),
        ({"crop_name": "   "}, "crop_name_blank"),
        ({"area_acres": D("0.005"), "batches": 12, "batch_interval_days": 7}, "batch_area_too_small"),
    ],
)
def test_invalid_items_are_rejected(override, code):
    with pytest.raises(PlanningInputError) as exc:
        item(**override)
    assert exc.value.code == code


def test_invalid_plans_are_rejected():
    with pytest.raises(PlanningInputError, match="at least one crop"):
        plan()
    with pytest.raises(PlanningInputError) as exc:
        plan(item(), land=0)
    assert exc.value.code == "land_not_positive"
    with pytest.raises(PlanningInputError) as exc:
        plan(item(), budget_inr=D(0))
    assert exc.value.code == "budget_inr_not_positive"
    with pytest.raises(PlanningInputError) as exc:
        plan(*[item() for _ in range(31)])
    assert exc.value.code == "too_many_items"


# ---------------------------------------------------------------- determinism


def test_evaluation_is_deterministic():
    p = plan(item(), item(crop_name="Ragi", sowing_date=date(2026, 6, 15)))
    assert evaluate_plan(p) == evaluate_plan(p)


def test_independently_built_identical_inputs_give_identical_results():
    assert evaluate_plan(plan(item())) == evaluate_plan(plan(item()))


def test_input_is_not_mutated():
    original = item()
    snapshot = ItemInput(**{f: getattr(original, f) for f in original.__dataclass_fields__})
    evaluate_plan(plan(original))
    assert original == snapshot
