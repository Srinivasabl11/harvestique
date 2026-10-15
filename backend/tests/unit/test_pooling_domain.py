"""Pure pooling algorithms: matching, scoring, greedy vs LP, shortage assignment, pool states, experiment."""

from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from app.core.enums import DemandStatus, OrderStatus, PoolStatus, QualityGrade
from app.domain.pooling.experiment import STRATEGIES, bootstrap_ci, run, run_trial
from app.domain.pooling.matching import evaluate, haversine_km, rank
from app.domain.pooling.models import DemandSpec, Supply, Weights
from app.domain.pooling.optimizer import greedy, lp
from app.domain.pooling.shortage import Commitment, assign_shortfall, demand_stage, lot_shortfall, pool_status

W0, W1 = date(2026, 12, 1), date(2026, 12, 31)


def sup(ref, kg, *, risk=30, conf=70, grade=QualityGrade.B, rel="0.5", **kw):
    return Supply(
        f"lot-{ref}",
        ref,
        "tomato",
        grade,
        D(kg),
        D(kg),
        kw.pop("start", W0),
        kw.pop("end", W1),
        D(conf),
        None if risk is None else D(risk),
        D(rel),
        **kw,
    )


def demand(qty=2000, **kw):
    return DemandSpec("tomato", D(qty), W0, W1, **kw)


CRITICAL = [sup(k, v) for k, v in {"A": 500, "B": 350, "C": 450, "D": 300, "E": 400}.items()]


# ------------------------------------------------------------- critical case


@pytest.mark.parametrize("algo", [greedy, lp])
def test_critical_scenario_pools_exactly_2000(algo):
    plan = algo(rank(CRITICAL, demand(), D(2000), Weights()), D(2000))
    assert plan.total_kg == 2000
    assert {ln.lot_id[-1]: ln.quantity_kg for ln in plan.lines} == {"A": 500, "B": 350, "C": 450, "D": 300, "E": 400}


def test_critical_drop_is_exactly_250_kg():
    commitments = [Commitment("res-C", D(450), 1, True)]
    shortfall = lot_shortfall(D(200), commitments)
    assert shortfall == 250 and assign_shortfall(shortfall, commitments).cuts == {"res-C": D(250)}


# ------------------------------------------------------------------ matching


@pytest.mark.parametrize(
    ("supply", "spec", "reason"),
    [
        (replace(sup("X", 100), crop_id="onion"), demand(), "crop_mismatch"),
        (sup("X", 100, grade=QualityGrade.C), demand(min_grade=QualityGrade.B), "grade_below_minimum"),
        (replace(sup("X", 100), opted_in=False), demand(), "not_opted_in"),
        (replace(sup("X", 100), lot_open=False), demand(), "lot_not_open"),
        (sup("X", 0), demand(), "no_available_quantity"),
        (sup("X", 100, start=date(2027, 3, 1), end=date(2027, 3, 9)), demand(), "window_no_overlap"),
        (sup("X", 100, conf=30), demand(min_confidence=D(50)), "confidence_below_minimum"),
        (sup("X", 100, risk=80), demand(max_risk=D(60)), "risk_above_maximum"),
        (sup("X", 100), demand(latitude=D(12), longitude=D(76), max_distance_km=D(50)), "location_unknown"),
        (
            sup("X", 100, latitude=D(14), longitude=D(76)),
            demand(latitude=D(12), longitude=D(76), max_distance_km=D(50)),
            "too_far",
        ),
    ],
)
def test_every_ineligibility_reason(supply, spec, reason):
    m = evaluate(supply, spec, D(100), Weights())
    assert not m.eligible and reason in m.reasons


def test_better_grade_than_required_is_eligible():
    assert evaluate(sup("X", 100, grade=QualityGrade.A), demand(min_grade=QualityGrade.B), D(100), Weights()).eligible


def test_score_is_the_documented_weighted_sum():
    m = evaluate(sup("X", 1000, risk=40, conf=80, rel="0.75"), demand(), D(500), Weights())
    assert m.components == {
        "confidence": D(80),
        "safety": D(60),
        "reliability": D(75),
        "window": D(100),
        "proximity": D(50),
        "availability": D(100),
    }
    assert (
        m.score == D("0.25") * 80 + D("0.20") * 60 + D("0.15") * 75 + D("0.15") * 100 + D("0.10") * 50 + D("0.15") * 100
    )


def test_unknown_risk_and_distance_are_neutral_not_guessed():
    m = evaluate(sup("X", 100, risk=None), demand(), D(100), Weights())
    assert m.components["safety"] == 50 and m.components["proximity"] == 50


def test_weights_must_sum_to_one():
    with pytest.raises(ValueError):
        Weights(confidence=D("0.5"))


def test_haversine_one_degree_of_latitude():
    assert abs(haversine_km(D(12), D(76), D(13), D(76)) - D("111.19")) < 1


def test_ranking_is_deterministic_and_puts_eligible_first():
    ranked = rank([sup("B", 0), sup("A", 100), sup("C", 100)], demand(), D(100), Weights())
    assert [m.supply.farm_ref for m in ranked] == ["A", "C", "B"]


# ----------------------------------------------------------------- optimizer


@pytest.mark.parametrize("algo", [greedy, lp])
def test_never_exceeds_availability_or_need(algo):
    plan = algo(rank(CRITICAL, demand(1234.567), D("1234.567"), Weights()), D("1234.567"))
    assert plan.total_kg <= D("1234.567")
    avail = {s.lot_id: s.available_kg for s in CRITICAL}
    assert all(0 < ln.quantity_kg <= avail[ln.lot_id] for ln in plan.lines)


@pytest.mark.parametrize("algo", [greedy, lp])
def test_insufficient_supply_allocates_everything_available(algo):
    assert algo(rank(CRITICAL, demand(3000), D(3000), Weights()), D(3000)).total_kg == 2000


def test_greedy_takes_risky_supply_the_lp_limits_it():
    supplies = [sup("SAFE", 500, risk=20, conf=40), sup("RISKY", 1000, risk=90, conf=95)]
    ranked = rank(supplies, demand(1000), D(1000), Weights())
    g, lp_plan = greedy(ranked, D(1000)), lp(ranked, D(1000), max_pool_risk=D(50))
    assert {ln.lot_id: ln.quantity_kg for ln in g.lines} == {"lot-RISKY": D(1000)}
    lp_lines = {ln.lot_id: ln.quantity_kg for ln in lp_plan.lines}
    avg_risk = (lp_lines.get("lot-SAFE", 0) * 20 + lp_lines.get("lot-RISKY", 0) * 90) / lp_plan.total_kg
    assert avg_risk <= 50 + D("0.01") and lp_lines["lot-SAFE"] == 500  # all safe supply used, risky limited


def test_lp_diversification_cap_applies_when_free():
    supplies = [sup("BIG", 2000, conf=90), *[sup(f"S{i}", 500, conf=50) for i in range(4)]]
    plan = lp(rank(supplies, demand(1000), D(1000), Weights()), D(1000), max_share=D("0.4"))
    assert (
        plan.total_kg == 1000 and max(ln.quantity_kg for ln in plan.lines) <= 400 and "applied" in " ".join(plan.notes)
    )


def test_lp_relaxes_the_cap_rather_than_lose_fulfilment():
    plan = lp(rank([sup("ONLY", 2000)], demand(1000), D(1000), Weights()), D(1000), max_share=D("0.4"))
    assert plan.total_kg == 1000 and "relaxed" in " ".join(plan.notes)


@pytest.mark.parametrize("algo", [greedy, lp])
def test_ineligible_supply_is_never_used(algo):
    supplies = [replace(sup("OUT", 900), opted_in=False), sup("IN", 100)]
    assert algo(rank(supplies, demand(500), D(500), Weights()), D(500)).total_kg == 100


def test_empty_inputs():
    assert greedy([], D(10)).total_kg == 0 and lp([], D(10)).total_kg == 0


# ------------------------------------------------------------------- shortage


def test_newest_pool_commitment_is_cut_first_and_older_preserved():
    c = [Commitment("old", D(300), 1, True), Commitment("new", D(200), 2, True)]
    assert assign_shortfall(D(250), c).cuts == {"new": D(200), "old": D(50)}


def test_farmer_reservations_are_never_cut_by_the_system():
    c = [Commitment("farmer", D(300), 3, False), Commitment("pool", D(100), 1, True)]
    a = assign_shortfall(D(250), c)
    assert a.cuts == {"pool": D(100)} and a.uncovered_kg == 150


def test_no_shortfall_when_supply_covers_commitments():
    assert lot_shortfall(D(500), [Commitment("x", D(500), 1, True)]) == 0


@pytest.mark.parametrize(
    ("demand_kg", "allocated", "short", "lot_risk", "status"),
    [
        (2000, 2000, 0, False, PoolStatus.FILLED),
        (2000, 1500, 0, False, PoolStatus.PARTIAL),
        (2000, 0, 0, False, PoolStatus.UNFILLED),
        (2000, 1750, 250, False, PoolStatus.AT_RISK),
        (2000, 2000, 0, True, PoolStatus.AT_RISK),
    ],
)
def test_pool_states(demand_kg, allocated, short, lot_risk, status):
    assert pool_status(D(demand_kg), D(allocated), D(short), lot_risk) is status


# ------------------------------------------------------------------ experiment


def _stable(r):
    return {k: v for k, v in r.__dict__.items() if k != "reallocation_ms"}


def test_experiment_is_reproducible():
    a, b = run(seeds=(1, 2), levels=(0.25,)), run(seeds=(1, 2), levels=(0.25,))
    assert [_stable(x) for x in a] == [_stable(x) for x in b]


def test_static_strategy_never_reallocates_and_others_do_under_disruption():
    a = run_trial("A_static", 3, 0.5)
    b = run_trial("B_greedy", 3, 0.5)
    assert a.shortage_events == 0 and a.reallocation_steps == 0 and b.shortage_events > 0
    assert set(STRATEGIES) == {"A_static", "B_greedy", "C_harvestique", "C0_lp_no_risk_cap"}


def test_all_strategies_see_the_same_synthetic_world():
    trials = [run_trial(s, 4, 0.25) for s in STRATEGIES]
    assert len({(t.mape, t.coverage) for t in trials}) == 1


def test_bootstrap_ci_brackets_the_mean():
    m, lo, hi = bootstrap_ci([0.1, 0.2, 0.3, 0.4])
    assert lo <= m <= hi


@pytest.mark.parametrize(
    ("demand", "pool", "order", "live", "stage"),
    [
        (DemandStatus.OPEN, None, None, None, "open"),
        (DemandStatus.OPEN, None, None, "full", "matching_supply_available"),
        (DemandStatus.OPEN, None, None, "partial", "partially_matched"),
        (DemandStatus.OPEN, None, None, "none", "no_matching_supply"),
        (DemandStatus.CANCELLED, None, None, "full", "cancelled"),
        (DemandStatus.POOLED, PoolStatus.PARTIAL, None, "full", "partially_matched"),  # live ignored once pooled
        (DemandStatus.POOLED, PoolStatus.AT_RISK, OrderStatus.CONFIRMED, None, "reallocation_required"),
        (DemandStatus.POOLED, PoolStatus.FILLED, OrderStatus.PLACED, None, "awaiting_farmer_confirmation"),
    ],
)
def test_demand_stage(demand, pool, order, live, stage):
    assert demand_stage(demand, pool, order, live) == stage
