"""Plan-level evaluation: totals, land and budget limits, multi-crop plans, findings, risk and confidence."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from app.core.enums import (
    ConfidenceLevel,
    CropSeason,
    DemandLevel,
    EstimateBasis,
    FindingSeverity,
    RiskLevel,
)
from app.domain.planning import PlanningInputError, evaluate_plan, scoring
from app.domain.planning.engine import ASSUMPTIONS, DISCLAIMER
from tests.planning_factory import TOMATO_COST, item, plan, rng, simple

RAGI = dict(
    crop_name="Ragi",
    area_acres=D(4),
    sowing_date=date(2026, 6, 15),
    duration_days=120,
    harvest_window_days=15,
    yield_per_acre_kg=rng(600, 900, 1200),
    price_per_kg=rng(25, 32, 40),
)


def codes(result, severity=None):
    return [f.code for f in result.findings if severity is None or f.severity is severity]


# ------------------------------------------------------------ multi-crop totals


def test_plan_totals_are_the_sum_of_the_crops():
    r = evaluate_plan(plan(item(), item(**RAGI), land=10))
    a, b = r.items
    assert r.totals.cost.expected == a.cost.expected + b.cost.expected
    assert r.totals.cost.high == a.cost.high + b.cost.high
    assert r.totals.revenue.expected == a.revenue.expected + b.revenue.expected
    assert r.totals.revenue.low == a.revenue.low + b.revenue.low
    assert r.totals.margin.expected == a.margin.expected + b.margin.expected
    assert r.totals.area_sown_acres == D(6)


def test_plan_margin_pairs_worst_revenue_with_highest_cost():
    r = evaluate_plan(plan(item(), item(**RAGI), land=10))
    assert r.totals.margin.low == r.totals.revenue.low - r.totals.cost.high
    assert r.totals.margin.high == r.totals.revenue.high - r.totals.cost.expected


def test_plan_break_even_figures():
    r = evaluate_plan(plan(item()))
    t = r.totals
    assert t.break_even_revenue == D(87000)
    assert t.break_even_pct_of_expected_revenue == D("30.21")  # 87,000 / 288,000
    assert t.cover_ratio_expected == D("3.31")  # 288,000 / 87,000
    assert t.cover_ratio_pessimistic == D("1.34")  # 128,000 / 95,700
    assert t.roi_expected_pct == D("231.03")


def test_results_are_returned_in_input_order():
    r = evaluate_plan(plan(item(), item(**RAGI), land=10))
    assert [i.crop_name for i in r.items] == ["Tomato", "Ragi"] and [i.index for i in r.items] == [0, 1]


# ---------------------------------------------------------------------- land


def test_overlapping_crops_that_do_not_fit_are_infeasible():
    p = plan(item(area_acres=D(3)), item(crop_name="Chilli", area_acres=D(3)), land=5)  # both in the ground at once
    r = evaluate_plan(p)
    assert r.feasible is False
    (finding,) = [f for f in r.findings if f.code == "land_exceeded"]
    assert finding.severity is FindingSeverity.HARD
    assert finding.details == {"peak_acres": 6.0, "available_acres": 5.0}
    assert r.land.first_over_limit_on == date(2026, 11, 1)
    assert r.land.peak_in_use_acres == D(6) and r.land.unused_at_peak_acres == D(-1)


def test_land_exactly_used_is_feasible_but_one_more_thousandth_is_not():
    assert evaluate_plan(plan(item(area_acres=D(5)), land=5)).feasible is True
    assert evaluate_plan(plan(item(area_acres=D("5.001")), land=5)).feasible is False


def test_sequential_crops_can_reuse_the_same_land():
    """8 acres are sown in total on a 5-acre farm, but never more than 4 at the same time."""
    r = evaluate_plan(
        plan(item(**RAGI), item(area_acres=D(4)), land=5)
    )  # ragi harvested by late Oct; tomato sown Nov 1
    assert r.totals.area_sown_acres == D(8)
    assert r.land.peak_in_use_acres == D(4) and r.feasible is True
    assert "land_exceeded" not in codes(r)


def test_harvest_day_still_occupies_the_land():
    first = item(**RAGI)  # last harvest day: 2026-06-15 + 120 d + 14 d = 2026-10-27
    last_day = evaluate_plan(plan(first)).items[0].batches[0].harvest_end
    clash = item(area_acres=D(4), sowing_date=last_day)  # sown on the last harvest day
    ok = item(area_acres=D(4), sowing_date=date(last_day.year, last_day.month, last_day.day + 1))
    assert evaluate_plan(plan(first, clash, land=5)).feasible is False
    assert evaluate_plan(plan(first, ok, land=5)).feasible is True


def test_land_utilization_numbers():
    # 1 acre sown Jan 1, harvest Jan 26 - Feb 4 (10 days): occupies Jan 1 - Feb 4 = 35 days, on 2 acres of land
    r = evaluate_plan(
        plan(simple(area=1, sowing_date=date(2027, 1, 1), duration_days=25, harvest_window_days=10), land=2)
    )
    land = r.land
    assert (land.peak_in_use_acres, land.peak_utilization_pct) == (D(1), D("50.00"))
    assert land.average_utilization_pct == D("50.00")  # 35 area-days of 70 available
    jan, feb = land.monthly
    assert (jan.month, jan.peak_area_acres, jan.average_area_acres, jan.utilization_pct) == (
        "2027-01",
        D(1),
        D(1),
        D("50.00"),
    )
    assert (feb.month, feb.peak_area_acres, feb.average_area_acres) == ("2027-02", D(1), D("0.143"))  # 4 of 28 days


# -------------------------------------------------------------------- budget


def test_budget_exceeded_is_a_hard_finding():
    r = evaluate_plan(plan(item(), budget_inr=D(86999)))  # expected cost is 87,000
    assert r.feasible is False
    assert "budget_exceeded" in codes(r, FindingSeverity.HARD)


def test_budget_equal_to_expected_cost_is_feasible_but_at_risk():
    r = evaluate_plan(plan(item(), budget_inr=D(87000)))
    assert r.feasible is True
    assert codes(r, FindingSeverity.HARD) == []
    assert "budget_at_risk" in codes(r, FindingSeverity.WARNING)  # a 10% overrun (95,700) would break it


def test_budget_covering_the_overrun_has_no_budget_finding():
    r = evaluate_plan(plan(item(), budget_inr=D(95700)))
    assert r.feasible is True and not {"budget_exceeded", "budget_at_risk"} & set(codes(r))


def test_budget_summary_numbers():
    b = evaluate_plan(plan(item(), budget_inr=D(100000))).budget
    assert (b.budget, b.expected_cost, b.high_cost) == (D(100000), D("87000.00"), D("95700.00"))
    assert (b.headroom_expected, b.headroom_high, b.utilization_pct) == (D("13000.00"), D("4300.00"), D("87.00"))


def test_no_budget_means_no_budget_findings():
    r = evaluate_plan(plan(item()))
    assert r.budget.budget is None and r.budget.headroom_expected is None and r.budget.utilization_pct is None
    assert not {"budget_exceeded", "budget_at_risk"} & set(codes(r))


def test_budget_is_checked_across_all_crops():
    two = plan(item(), item(**RAGI), land=10)
    total = evaluate_plan(two).totals.cost.expected
    assert evaluate_plan(plan(item(), item(**RAGI), land=10, budget_inr=total)).feasible is True
    assert evaluate_plan(plan(item(), item(**RAGI), land=10, budget_inr=total - D("0.01"))).feasible is False


def test_land_and_budget_can_both_fail():
    r = evaluate_plan(plan(item(area_acres=D(8)), land=5, budget_inr=D(1000)))
    assert sorted(codes(r, FindingSeverity.HARD)) == ["budget_exceeded", "land_exceeded"] and r.feasible is False


# ----------------------------------------------------------- water and labour


def test_water_and_labour_shortfalls_are_warnings_not_blockers():
    p = plan(
        item(water_kl_per_acre=D(100)),  # 2 acres -> 200 kL; labour 60 x 2 = 120 person-days
        available_water_kl=D(150),
        available_labour_person_days=D(100),
    )
    r = evaluate_plan(p)
    assert r.feasible is True
    assert {"water_exceeded", "labour_exceeded"} <= set(codes(r, FindingSeverity.WARNING))
    assert (r.water.required, r.water.headroom, r.water.utilization_pct) == (D("200.000"), D("-50.000"), D("133.33"))
    assert (r.labour.required, r.labour.headroom) == (D("120.000"), D("-20.000"))


def test_water_within_limit_has_no_finding_and_counts_missing_estimates():
    r = evaluate_plan(plan(item(water_kl_per_acre=D(10)), item(**RAGI), land=10, available_water_kl=D(500)))
    assert "water_exceeded" not in codes(r)
    assert r.water.required == D(20) and r.water.items_without_estimate == 1  # ragi has no water estimate


def test_no_availability_means_no_resource_warnings():
    r = evaluate_plan(plan(item(water_kl_per_acre=D(10_000))))
    assert not {"water_exceeded", "labour_exceeded"} & set(codes(r)) and r.water.available is None


# --------------------------------------------------------------------- season


def test_sowing_outside_the_plan_season_warns():
    r = evaluate_plan(plan(item(sowing_date=date(2026, 7, 1)), season=CropSeason.RABI))  # July is a kharif month
    assert "sowing_outside_season" in codes(r)


def test_sowing_in_season_is_clean():
    r = evaluate_plan(plan(item(sowing_date=date(2026, 11, 1)), season=CropSeason.RABI))
    assert "sowing_outside_season" not in codes(r)


def test_catalog_crop_season_mismatch_warns():
    r = evaluate_plan(plan(item(crop_season=CropSeason.KHARIF, sowing_date=date(2026, 11, 1)), season=CropSeason.RABI))
    assert "crop_season_mismatch" in codes(r)


def test_year_round_plan_and_year_round_crop_never_warn():
    assert not {"sowing_outside_season", "crop_season_mismatch"} & set(
        codes(evaluate_plan(plan(item(crop_season=CropSeason.KHARIF))))
    )
    r = evaluate_plan(
        plan(item(crop_season=CropSeason.YEAR_ROUND, sowing_date=date(2026, 7, 1)), season=CropSeason.RABI)
    )
    assert "crop_season_mismatch" not in codes(r)


# ------------------------------------------------------------ other findings


def test_expected_loss_and_loss_possible_findings():
    losing = evaluate_plan(plan(simple(y=100, price=5, cost_per_acre=1000)))  # expected margin -500
    assert "expected_loss" in codes(losing) and "loss_possible" not in codes(losing)
    risky = evaluate_plan(plan(item(yield_per_acre_kg=rng(1000, 12000, 16000))))  # expected fine, worst case loses
    assert "loss_possible" in codes(risky) and "expected_loss" not in codes(risky)
    assert not {"expected_loss", "loss_possible"} & set(codes(evaluate_plan(plan(item()))))


def test_demand_exceeded_finding_names_the_crop():
    r = evaluate_plan(plan(item(demand_quantity_kg=D(10000))))
    (f,) = [f for f in r.findings if f.code == "demand_exceeded"]
    assert f.item_index == 0 and "Tomato" in f.message and r.items[0].demand_limited


def test_findings_list_hard_ones_first():
    r = evaluate_plan(plan(item(area_acres=D(8), demand_quantity_kg=D(1000)), land=5))
    severities = [f.severity for f in r.findings]
    assert severities == sorted(severities, key=lambda s: s is not FindingSeverity.HARD)
    assert r.findings[0].severity is FindingSeverity.HARD


# --------------------------------------------------------------------- period


def test_planning_period():
    p = evaluate_plan(plan(item(**RAGI), item(area_acres=D(2)), land=5)).period
    assert p.start == date(2026, 6, 15)
    assert p.end == date(2027, 3, 10)  # tomato: Nov 1 + 100 d = Feb 9, 30-day window
    assert p.days == (date(2027, 3, 10) - date(2026, 6, 15)).days + 1
    assert p.months == 10  # Jun 2026 .. Mar 2027


# ------------------------------------------------------------- risk (weights)


def test_every_weight_table_sums_to_one():
    assert sum(scoring.ITEM_RISK_WEIGHTS.values()) == 1
    assert sum(scoring.PLAN_RISK_WEIGHTS.values()) == 1
    assert sum(scoring.CONFIDENCE_WEIGHTS.values()) == 1


@pytest.mark.parametrize(
    ("score", "level"),
    [
        ("0", RiskLevel.LOW),
        ("34.9", RiskLevel.LOW),
        ("35", RiskLevel.MEDIUM),
        ("64.9", RiskLevel.MEDIUM),
        ("65", RiskLevel.HIGH),
        ("100", RiskLevel.HIGH),
    ],
)
def test_risk_level_thresholds(score, level):
    assert scoring.risk_level(D(score)) is level


@pytest.mark.parametrize(
    ("score", "level"),
    [
        ("0", ConfidenceLevel.LOW),
        ("44.9", ConfidenceLevel.LOW),
        ("45", ConfidenceLevel.MEDIUM),
        ("69.9", ConfidenceLevel.MEDIUM),
        ("70", ConfidenceLevel.HIGH),
    ],
)
def test_confidence_level_thresholds(score, level):
    assert scoring.confidence_level(D(score)) is level


def test_item_risk_matches_the_hand_calculation():
    """0.25*66.67 + 0.20*83.33 + 0.20*0 + 0.15*50 + 0.10*35 + 0.10*0 = 44.33"""
    risk = evaluate_plan(plan(item())).items[0].risk
    by_name = {c.name: c.score for c in risk.components}
    assert by_name == {
        "yield_uncertainty": D("66.7"),  # spread (16,000-8,000)/12,000
        "price_uncertainty": D("83.3"),  # spread (18-8)/12
        "loss_exposure": D("0.0"),  # worst case still profitable
        "declared_risk": D("50.0"),
        "demand": D("35.0"),
        "season_fit": D("0.0"),
    }
    assert risk.score == D("44.3") and risk.level is RiskLevel.MEDIUM


def test_a_wider_range_means_higher_risk():
    narrow = evaluate_plan(plan(item(yield_per_acre_kg=rng(11000, 12000, 13000)))).items[0].risk.score
    wide = evaluate_plan(plan(item(yield_per_acre_kg=rng(4000, 12000, 20000)))).items[0].risk.score
    assert narrow < wide


def test_loss_exposure_rises_when_the_worst_case_loses_money():
    safe = evaluate_plan(plan(item())).items[0].risk
    unsafe = evaluate_plan(plan(item(yield_per_acre_kg=rng(500, 12000, 16000)))).items[0].risk
    assert {c.name: c.score for c in safe.components}["loss_exposure"] == 0
    assert {c.name: c.score for c in unsafe.components}["loss_exposure"] > 0 and unsafe.score > safe.score


def test_demand_pressure_scores():
    def demand_points(**kw):
        return {c.name: c.score for c in evaluate_plan(plan(item(**kw))).items[0].risk.components}["demand"]

    assert demand_points(demand_level=DemandLevel.HIGH) == D(10)
    assert demand_points(demand_level=DemandLevel.LOW) == D(70)
    assert demand_points(demand_quantity_kg=D(10000)) == D(100)  # supply exceeds demand: worst


def test_declared_risk_moves_the_score():
    low, high = (
        evaluate_plan(plan(item(declared_risk=r))).items[0].risk.score for r in (RiskLevel.LOW, RiskLevel.HIGH)
    )
    assert low < high


def test_plan_risk_matches_the_hand_calculation():
    """single crop: 0.65*44.33 + 0.15*100 (one crop = 100% of revenue) + 0.10*0 + 0.10*0 = 43.8"""
    r = evaluate_plan(plan(item()))
    comps = {c.name: c.score for c in r.risk.components}
    assert (
        comps["concentration"] == D("100.0")
        and comps["income_gaps"] == D("0.0")
        and comps["resource_pressure"] == D("0.0")
    )
    assert r.risk.score == D("43.8") and r.risk.level is RiskLevel.MEDIUM


def test_diversifying_lowers_concentration_risk():
    one = evaluate_plan(plan(item(), land=10)).risk
    two = evaluate_plan(plan(item(), item(crop_name="Tomato 2", sowing_date=date(2026, 11, 1)), land=10)).risk
    assert {c.name: c.score for c in two.components}["concentration"] == D("50.0")
    assert two.score < one.score


def test_resource_overuse_raises_plan_risk():
    ok = evaluate_plan(plan(item(water_kl_per_acre=D(100)), available_water_kl=D(1000))).risk.score
    short = evaluate_plan(
        plan(item(water_kl_per_acre=D(100)), available_water_kl=D(100))
    ).risk  # needs 200 vs 100: +100%
    assert {c.name: c.score for c in short.components}["resource_pressure"] == D("100.0") and short.score > ok


def test_every_risk_component_explains_itself():
    r = evaluate_plan(plan(item()))
    for c in [*r.risk.components, *r.items[0].risk.components, *r.items[0].confidence.components]:
        assert c.detail and 0 <= c.score <= 100 and 0 < c.weight <= 1


# ------------------------------------------------------------------ confidence


def test_item_confidence_matches_the_hand_calculation():
    """0.4*65 (local knowledge) + 0.4*25 (75% avg spread) + 0.2*40 (labour + not-an-assumption) = 44.0"""
    c = evaluate_plan(plan(item())).items[0].confidence
    assert {x.name: x.score for x in c.components} == {
        "estimate_basis": D("65.0"),
        "range_tightness": D("25.0"),
        "completeness": D("40.0"),
    }
    assert c.score == D("44.0") and c.level is ConfidenceLevel.LOW


def test_better_evidence_means_higher_confidence():
    base = evaluate_plan(plan(item())).items[0].confidence.score
    records = evaluate_plan(plan(item(estimate_basis=EstimateBasis.OWN_RECORDS))).items[0].confidence.score
    guess = evaluate_plan(plan(item(estimate_basis=EstimateBasis.ASSUMPTION))).items[0].confidence.score
    assert guess < base < records


def test_tighter_ranges_and_complete_inputs_raise_confidence():
    base = evaluate_plan(plan(item())).items[0].confidence.score
    tight = (
        evaluate_plan(plan(item(yield_per_acre_kg=rng(11500, 12000, 12500), price_per_kg=rng(11, 12, 13))))
        .items[0]
        .confidence.score
    )
    complete = (
        evaluate_plan(plan(item(has_catalog_crop=True, water_kl_per_acre=D(50), demand_quantity_kg=D(99999))))
        .items[0]
        .confidence.score
    )
    assert tight > base and complete > base


def test_a_well_documented_plan_can_reach_high_confidence():
    good = item(
        estimate_basis=EstimateBasis.OWN_RECORDS,
        yield_per_acre_kg=rng(11000, 12000, 13000),
        price_per_kg=rng(11, 12, 13),
        has_catalog_crop=True,
        water_kl_per_acre=D(50),
        demand_quantity_kg=D(99999),
    )
    assert evaluate_plan(plan(good)).confidence.level is ConfidenceLevel.HIGH


def test_plan_confidence_is_weighted_by_expected_revenue():
    strong = item(
        estimate_basis=EstimateBasis.OWN_RECORDS,
        yield_per_acre_kg=rng(11500, 12000, 12500),
        price_per_kg=rng(11.5, 12, 12.5),
    )
    weak = item(
        crop_name="Guess",
        estimate_basis=EstimateBasis.ASSUMPTION,
        yield_per_acre_kg=rng(100, 500, 900),
        price_per_kg=rng(1, 2, 3),
    )
    r = evaluate_plan(plan(strong, weak, land=10))
    s, w = (i.confidence.score for i in r.items)
    revenue = [i.revenue.expected for i in r.items]
    expected = (s * revenue[0] + w * revenue[1]) / (revenue[0] + revenue[1])
    assert abs(r.confidence.score - expected) <= D("0.05")
    assert r.confidence.score > (s + w) / 2  # the high-revenue, well-founded crop dominates


# ------------------------------------------------------- honesty of the output


def test_results_always_carry_a_disclaimer_and_assumptions():
    r = evaluate_plan(plan(item()))
    assert r.disclaimer == DISCLAIMER and "do not guarantee" in r.disclaimer
    assert r.assumptions == ASSUMPTIONS and any("not" in a.lower() for a in r.assumptions)


def test_money_is_always_reported_as_a_range_not_a_point():
    r = evaluate_plan(plan(item()))
    for triple in (r.totals.cost, r.totals.revenue, r.totals.margin):
        assert triple.low <= triple.expected <= triple.high
    assert r.totals.revenue.low < r.totals.revenue.expected < r.totals.revenue.high


def test_plan_explanations_summarise_the_outcome():
    text = " ".join(evaluate_plan(plan(item(), budget_inr=D(100000))).explanations)
    for expected in ("₹87,000.00", "Expected revenue", "Break-even", "Risk is medium", "fits the land and budget"):
        assert expected in text, expected
    assert "does NOT fit" in " ".join(evaluate_plan(plan(item(), budget_inr=D(1000))).explanations)


def test_cost_inputs_object_is_the_default_when_omitted():
    bare = item(cost=type(TOMATO_COST)())
    r = evaluate_plan(plan(bare)).items[0]
    assert r.cost.expected == D(0) and r.roi_expected_pct is None


def test_a_plan_cannot_be_built_without_crops():
    with pytest.raises(PlanningInputError):
        evaluate_plan(plan())
