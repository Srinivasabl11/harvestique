"""The land utilization planner: deterministic greedy allocation under land, budget, water, labour and demand."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D
from itertools import product

import pytest

from app.core.enums import CropSeason, FindingSeverity, RankBy
from app.domain.planning import (
    AllocationInput,
    Candidate,
    CostInputs,
    PlanInput,
    PlanningInputError,
    evaluate_plan,
    suggest_allocation,
)
from tests.planning_factory import item, rng


def crop(name="A", *, margin_per_acre=10000, cost_per_acre=0, **kw):
    """A candidate with expected revenue = cost + margin per acre (yield 1000 kg x price)."""
    price = D(margin_per_acre + cost_per_acre) / 1000
    cost = kw.pop("cost", CostInputs(seed=D(cost_per_acre)))
    return item(
        crop_name=name,
        area_acres=D(1),
        yield_per_acre_kg=rng(1000, 1000, 1000),
        price_per_kg=rng(price, price, price),
        cost=cost,
        **kw,
    )


def cand(template, **kw):
    return Candidate(template, **kw)


def request(*candidates, land=10, **kw):
    return AllocationInput(
        available_land_acres=D(str(land)),
        season=CropSeason.YEAR_ROUND,
        candidates=tuple(c if isinstance(c, Candidate) else cand(c) for c in candidates),
        **kw,
    )


def areas(out):
    return {a.crop_name: a.area_acres for a in out.allocations}


# ------------------------------------------------------------------- ranking


def test_best_margin_per_acre_is_filled_first():
    out = suggest_allocation(
        request(
            crop("Low", margin_per_acre=5000), crop("High", margin_per_acre=20000), land=10, max_crop_share_pct=D(60)
        )
    )
    assert out.ranking == (1, 0)  # High first
    assert areas(out) == {"High": D(6), "Low": D(4)}  # High capped at 60% of 10 acres; Low takes the rest


def test_without_a_share_cap_the_best_crop_takes_all_the_land():
    out = suggest_allocation(request(crop("Low", margin_per_acre=5000), crop("High", margin_per_acre=20000), land=10))
    assert areas(out) == {"High": D(10)}
    assert out.allocations[0].limited_by == "land"
    assert [e.code for e in out.excluded] == ["insufficient_land"]  # Low found no room


def test_return_on_cost_can_rank_differently_from_margin_per_acre():
    big = crop("BigSpender", margin_per_acre=30000, cost_per_acre=60000)  # ROI 50%
    lean = crop("Lean", margin_per_acre=15000, cost_per_acre=10000)  # ROI 150%
    by_margin = suggest_allocation(request(big, lean, rank_by=RankBy.MARGIN_PER_ACRE))
    by_roi = suggest_allocation(request(big, lean, rank_by=RankBy.RETURN_ON_COST))
    assert by_margin.ranking == (0, 1) and by_roi.ranking == (1, 0)


def test_ties_are_broken_by_name_then_input_order():
    a, b = crop("Banana", margin_per_acre=8000), crop("Apple", margin_per_acre=8000)
    assert suggest_allocation(request(a, b)).ranking == (1, 0)  # Apple before Banana
    same_a, same_b = crop("Same", margin_per_acre=8000), crop("Same", margin_per_acre=8000)
    assert suggest_allocation(request(same_a, same_b)).ranking == (0, 1)  # then input order


def test_allocation_is_deterministic():
    req = request(
        crop("A", margin_per_acre=9000),
        crop("B", margin_per_acre=7000),
        crop("C", margin_per_acre=7000),
        land=7,
        max_crop_share_pct=D(50),
    )
    assert suggest_allocation(req) == suggest_allocation(req)


def test_every_decision_is_explained():
    out = suggest_allocation(request(crop("A"), land=3))
    (a,) = out.allocations
    assert a.limited_by == "land" and "limited by land" in a.reason and a.reason.startswith("Ranked #1")


# ------------------------------------------------------------------ the limits


def test_land_limit():
    (a,) = suggest_allocation(request(crop("A"), land=4)).allocations
    assert (a.area_acres, a.limited_by) == (D(4), "land")


def test_budget_limit_with_fixed_cost():
    # per acre 40,000; fixed 10,000; budget 110,000 -> (110,000 - 10,000) / 40,000 = 2.5 acres
    c = crop("A", margin_per_acre=60000, cost=CostInputs(seed=D(40000), fixed_cost=D(10000)))
    (a,) = suggest_allocation(request(c, land=10, budget_inr=D(110000))).allocations
    assert (a.area_acres, a.limited_by) == (D("2.5"), "budget")


def test_budget_is_shared_between_crops_in_rank_order():
    first = crop("First", margin_per_acre=50000, cost_per_acre=20000)  # best margin: gets the money first
    second = crop("Second", margin_per_acre=30000, cost_per_acre=20000)
    out = suggest_allocation(request(first, second, land=10, budget_inr=D(100000), max_crop_share_pct=D(30)))
    assert areas(out) == {"First": D(3), "Second": D(2)}  # 3 acres (60k, share cap) then the remaining 40k buys 2 acres
    assert out.allocations[0].limited_by == "max_crop_share" and out.allocations[1].limited_by == "budget"


def test_water_limit():
    c = crop("A", water_kl_per_acre=D(80))
    (a,) = suggest_allocation(request(c, land=10, available_water_kl=D(300))).allocations
    assert (a.area_acres, a.limited_by) == (D("3.75"), "water")


def test_labour_limit():
    c = crop("A", cost=CostInputs(labour_person_days_per_acre=D(40), labour_wage_per_day=D(0)))
    (a,) = suggest_allocation(request(c, land=10, available_labour_person_days=D(100))).allocations
    assert (a.area_acres, a.limited_by) == (D("2.5"), "labour")


def test_demand_limit():
    # the market takes 2,500 kg; yield is 1,000 kg/acre -> 2.5 acres
    (a,) = suggest_allocation(request(crop("A", demand_quantity_kg=D(2500)), land=10)).allocations
    assert (a.area_acres, a.limited_by) == (D("2.5"), "demand")


def test_share_cap_limit():
    (a,) = suggest_allocation(request(crop("A"), land=10, max_crop_share_pct=D(25))).allocations
    assert (a.area_acres, a.limited_by) == (D("2.5"), "max_crop_share")


def test_candidate_maximum_limit():
    (a,) = suggest_allocation(request(cand(crop("A"), max_area_acres=D(3)), land=10)).allocations
    assert (a.area_acres, a.limited_by) == (D(3), "candidate_max_area")


def test_areas_are_whole_thousandths_rounded_down():
    c = crop("A", cost=CostInputs(seed=D(30000)), margin_per_acre=50000)  # 100,000 / 30,000 = 3.3333... acres
    (a,) = suggest_allocation(request(c, land=10, budget_inr=D(100000))).allocations
    assert a.area_acres == D("3.333") and a.area_acres * D(30000) <= D(100000)


# ------------------------------------------------------------------ exclusions


def test_loss_making_crops_are_excluded_with_a_reason():
    out = suggest_allocation(request(crop("Good"), crop("Bad", margin_per_acre=-500, cost_per_acre=2000)))
    assert [a.crop_name for a in out.allocations] == ["Good"]
    (e,) = out.excluded
    assert (e.crop_name, e.code) == ("Bad", "non_positive_margin") and "would not add income" in e.reason


def test_zero_margin_is_excluded_too():
    assert suggest_allocation(request(crop("Flat", margin_per_acre=0, cost_per_acre=1000))).allocations == ()


def test_allocation_below_the_minimum_area_is_excluded():
    out = suggest_allocation(
        request(
            crop("A", cost=CostInputs(seed=D(40000)), margin_per_acre=60000),
            cand(crop("B"), min_area_acres=D(2)),
            land=10,
            budget_inr=D(41000),
            max_crop_share_pct=D(50),
        )
    )
    assert any(e.code == "insufficient_budget" for e in out.excluded) or any(
        e.code == "insufficient_land" for e in out.excluded
    )


def test_budget_too_small_for_even_the_fixed_cost_excludes_the_crop():
    c = crop("A", cost=CostInputs(seed=D(1000), fixed_cost=D(50000)))
    out = suggest_allocation(request(c, budget_inr=D(40000)))
    assert out.allocations == () and out.excluded[0].code == "insufficient_budget"


def test_fixed_cost_not_recovered_is_excluded():
    c = crop(
        "A", margin_per_acre=1000, cost=CostInputs(seed=D(0), fixed_cost=D(50000))
    )  # 10 acres x 1,000 = 10,000 < 50,000
    out = suggest_allocation(request(c, land=10))
    assert out.allocations == () and out.excluded[0].code == "fixed_cost_not_recovered"


def test_excluded_crops_do_not_consume_resources():
    wasteful = crop("Wasteful", margin_per_acre=1000, cost=CostInputs(seed=D(0), fixed_cost=D(90000)))
    good = crop("Good", margin_per_acre=900, cost_per_acre=100)
    out = suggest_allocation(request(wasteful, good, land=10, budget_inr=D(100000)))
    assert [a.crop_name for a in out.allocations] == ["Good"]


# ----------------------------------------------------- time-aware land sharing


def test_crops_in_different_seasons_each_get_the_whole_land():
    early = crop(
        "Early", margin_per_acre=9000, sowing_date=date(2026, 6, 1), duration_days=60, harvest_window_days=10
    )  # done by mid-Aug
    late = crop("Late", margin_per_acre=8000, sowing_date=date(2026, 11, 1), duration_days=60, harvest_window_days=10)
    assert areas(suggest_allocation(request(early, late, land=5))) == {"Early": D(5), "Late": D(5)}


def test_crops_that_overlap_in_time_compete_for_land():
    a = crop("A", margin_per_acre=9000, sowing_date=date(2026, 6, 1), duration_days=60, harvest_window_days=10)
    b = crop(
        "B", margin_per_acre=8000, sowing_date=date(2026, 7, 1), duration_days=60, harvest_window_days=10
    )  # overlaps A
    out = suggest_allocation(request(a, b, land=5, max_crop_share_pct=D(60)))
    assert areas(out) == {
        "A": D(3),
        "B": D(2),
    }  # A takes 3 (share cap); B only gets the 2 that are free during its window


def test_partial_overlap_uses_the_tightest_window():
    long_one = crop(
        "Long", margin_per_acre=9000, sowing_date=date(2026, 6, 1), duration_days=120, harvest_window_days=10
    )  # Jun 1 - Oct 8
    short_one = crop(
        "Short", margin_per_acre=8000, sowing_date=date(2026, 9, 1), duration_days=30, harvest_window_days=10
    )  # Sep 1 - Oct 10
    out = suggest_allocation(request(long_one, short_one, land=4, max_crop_share_pct=D(75)))
    assert areas(out) == {"Long": D(3), "Short": D(1)}  # Short overlaps Long's last weeks


def test_staggered_candidates_get_multiples_of_the_batch_step():
    c = crop("A", batches=3, batch_interval_days=100, duration_days=60, harvest_window_days=10)
    # each batch may hold 33.33% of 4 acres = 1.3332 acres => at most 3.9996 in total, in steps of 0.003 (3 batches)
    (a,) = suggest_allocation(request(c, land=4, max_crop_share_pct=D("33.33"))).allocations
    assert a.area_acres == D("3.999") and a.area_acres % D("0.003") == 0 and a.limited_by == "max_crop_share"


def test_staggering_lets_one_crop_use_more_than_the_land_at_once_would_allow():
    # 3 batches 100 days apart never overlap, so each batch can use all 5 acres => 15 acres of crop in total
    c = crop("A", batches=3, batch_interval_days=100, duration_days=60, harvest_window_days=10)
    (a,) = suggest_allocation(request(c, land=5)).allocations
    assert a.area_acres == D(15) and a.limited_by == "land"


def test_a_crops_own_overlapping_batches_count_against_the_land():
    """Regression: 2 batches 45 days apart overlap (each is in the ground ~120 days), so both are on the
    land at once. The allocator once granted 10 acres on a 5-acre farm by checking batches independently."""
    c = crop("A", batches=2, batch_interval_days=45, duration_days=90, harvest_window_days=30)
    (a,) = suggest_allocation(request(c, land=5)).allocations
    assert a.area_acres == D(5) and a.limited_by == "land"
    placed = evaluate_plan(PlanInput(D(5), CropSeason.YEAR_ROUND, (replace(c, area_acres=a.area_acres),)))
    assert placed.land.peak_in_use_acres == D(5) and placed.feasible


def test_batches_that_only_overlap_in_part_use_the_busiest_day():
    # 3 batches 60 days apart, each in the ground 100 days: at most 2 overlap at once -> area/3 x 2 <= land
    c = crop("A", batches=3, batch_interval_days=60, duration_days=90, harvest_window_days=11)
    (a,) = suggest_allocation(request(c, land=4)).allocations
    assert a.area_acres == D(6)  # 6/3 = 2 acres per batch, 2 batches at once = 4 acres = the land


# ---------------------------------------- the central guarantee: always feasible

LANDS, BUDGETS, WATERS = [D(1), D("2.5"), D(5), D(12)], [None, D(20000), D(100000), D(400000)], [None, D(60)]


@pytest.mark.parametrize(("land", "budget", "water"), list(product(LANDS, BUDGETS, WATERS)))
def test_suggested_allocations_always_respect_every_limit(land, budget, water):
    cands = (
        crop(
            "Tomato",
            margin_per_acre=60000,
            cost_per_acre=40000,
            water_kl_per_acre=D(40),
            sowing_date=date(2026, 6, 1),
            duration_days=100,
            harvest_window_days=30,
            demand_quantity_kg=D(6000),
        ),
        crop(
            "Ragi",
            margin_per_acre=12000,
            cost_per_acre=5000,
            water_kl_per_acre=D(15),
            sowing_date=date(2026, 7, 1),
            duration_days=110,
        ),
        crop(
            "Maize",
            margin_per_acre=20000,
            cost_per_acre=9000,
            water_kl_per_acre=D(25),
            sowing_date=date(2027, 1, 10),
            duration_days=90,
            batches=2,
            batch_interval_days=45,
        ),
        crop("Loser", margin_per_acre=-1000, cost_per_acre=3000),
    )
    req = AllocationInput(
        available_land_acres=land,
        season=CropSeason.YEAR_ROUND,
        candidates=tuple(cand(c) for c in cands),
        budget_inr=budget,
        available_water_kl=water,
        max_crop_share_pct=D(70),
    )
    out = suggest_allocation(req)
    assert "Loser" not in areas(out)
    if not out.allocations:
        return
    items = tuple(replace(cands[a.candidate_index], area_acres=a.area_acres) for a in out.allocations)
    result = evaluate_plan(PlanInput(land, CropSeason.YEAR_ROUND, items, budget, water, None))
    hard = [f.code for f in result.findings if f.severity is FindingSeverity.HARD]
    assert hard == [], f"allocation broke a hard limit: {hard}"
    assert result.feasible
    assert "water_exceeded" not in [f.code for f in result.findings]
    for it, a in zip(items, out.allocations, strict=True):
        assert it.demand_quantity_kg is None or a.area_acres * it.yield_per_acre_kg.expected <= it.demand_quantity_kg
        assert (
            a.area_acres <= land * D("0.7") * (it.batches if it.batches > 1 else 1) or a.limited_by != "max_crop_share"
        )


def test_more_land_never_reduces_total_expected_margin():
    cands = [crop("A", margin_per_acre=9000), crop("B", margin_per_acre=6000)]
    totals = []
    for land in (1, 2, 4, 8):
        out = suggest_allocation(request(*cands, land=land, max_crop_share_pct=D(60)))
        totals.append(sum(a.expected_margin for a in out.allocations))
    assert totals == sorted(totals)


def _random_candidate(r, i):
    price, y = D(r.randint(5, 60)), D(r.randint(500, 9000))
    batches = r.choice([1, 1, 2, 3, 5])
    cost = CostInputs(
        seed=D(r.randint(0, 40000)),
        fixed_cost=D(r.choice([0, 0, 2000, 15000])),
        labour_person_days_per_acre=D(r.randint(0, 60)),
        labour_wage_per_day=D(r.randint(250, 500)),
    )
    template = item(
        crop_name=f"C{i}",
        area_acres=D(batches),
        sowing_date=date(2026, 1, 1) + timedelta(days=r.randint(0, 400)),
        duration_days=r.randint(30, 200),
        harvest_window_days=r.randint(1, 60),
        yield_per_acre_kg=rng(y * D("0.6"), y, y * D("1.4")),
        price_per_kg=rng(price * D("0.7"), price, price * D("1.5")),
        cost=cost,
        water_kl_per_acre=r.choice([None, D(r.randint(5, 80))]),
        demand_quantity_kg=r.choice([None, D(r.randint(2000, 40000))]),
        batches=batches,
        batch_interval_days=None if batches == 1 else r.randint(5, 120),
    )
    return Candidate(template, min_area_acres=D(r.choice(["0.001", "0.1", "0.5"])))


def test_random_scenarios_never_violate_any_limit():
    """600 seeded random scenarios (land, budget, water, labour, seasons, batches, demand, share caps).
    Whatever is suggested must pass `evaluate_plan` with no hard finding and stay within every cap."""
    r = random.Random(20261007)
    checked = 0
    for case in range(600):
        land = D(r.choice([0.5, 1, 2, 3.5, 6, 10, 25]))
        cands = tuple(_random_candidate(r, i) for i in range(r.randint(1, 6)))
        budget = r.choice([None, D(r.randint(5000, 600000))])
        water = r.choice([None, D(r.randint(20, 600))])
        labour = r.choice([None, D(r.randint(50, 2000))])
        share = D(r.choice([10, 33, 50, 100]))
        out = suggest_allocation(
            AllocationInput(land, CropSeason.YEAR_ROUND, cands, budget, water, labour, r.choice(list(RankBy)), share)
        )
        if not out.allocations:
            continue
        checked += 1
        items = tuple(replace(cands[a.candidate_index].template, area_acres=a.area_acres) for a in out.allocations)
        result = evaluate_plan(PlanInput(land, CropSeason.YEAR_ROUND, items, budget, water, labour))
        codes = {f.code for f in result.findings}
        hard = [f.code for f in result.findings if f.severity is FindingSeverity.HARD]
        assert hard == [] and not codes & {"water_exceeded", "labour_exceeded", "demand_exceeded"}, (case, codes)
        for a, it in zip(out.allocations, items, strict=True):
            cand = cands[a.candidate_index]
            assert a.area_acres >= cand.min_area_acres, case
            assert a.area_acres % (D("0.001") * it.batches) == 0, case  # equal batches
            if it.batches == 1:
                assert a.area_acres <= land * share / 100, case
    assert checked > 400  # the generator really exercises the allocator, not just empty results


# ----------------------------------------------------------------- invalid input


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"land": 0}, "land_not_positive"),
        ({"max_crop_share_pct": D(0)}, "share_invalid"),
        ({"max_crop_share_pct": D(101)}, "share_invalid"),
        ({"budget_inr": D(0)}, "budget_inr_not_positive"),
        ({"available_water_kl": D(-1)}, "available_water_kl_not_positive"),
    ],
)
def test_invalid_allocation_requests(kwargs, code):
    with pytest.raises(PlanningInputError) as exc:
        request(crop("A"), **{"land": 5, **kwargs})
    assert exc.value.code == code


def test_no_candidates_is_an_error():
    with pytest.raises(PlanningInputError) as exc:
        AllocationInput(available_land_acres=D(5), season=CropSeason.YEAR_ROUND, candidates=())
    assert exc.value.code == "no_candidates"


def test_invalid_candidate_bounds():
    with pytest.raises(PlanningInputError) as exc:
        cand(crop("A"), min_area_acres=D(0))
    assert exc.value.code == "min_area_not_positive"
    with pytest.raises(PlanningInputError) as exc:
        cand(crop("A"), min_area_acres=D(2), max_area_acres=D(1))
    assert exc.value.code == "max_area_below_min"


def test_allocation_carries_its_own_caveats():
    out = suggest_allocation(request(crop("A")))
    assert any("not guaranteed" in n for n in out.notes)
