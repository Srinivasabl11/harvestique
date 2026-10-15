"""POST /planning/calculate and /planning/suggest-allocation (stateless: nothing is saved)."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import text

from tests.planning_factory import calc_body, candidate_body, item_body, ragi_body

pytestmark = pytest.mark.integration
CALC = "/api/v1/planning/calculate"
SUGGEST = "/api/v1/planning/suggest-allocation"


def errors(response) -> dict[str, str]:
    assert response.status_code == 422, response.text
    body = response.json()["error"]
    assert body["code"] == "request_validation_error"
    return {e["field"]: e["message"] for e in body["details"]["errors"]}


# ------------------------------------------------------------------ calculator


def test_calculate_returns_the_hand_checked_numbers(db_client, farmer):
    r = db_client.post(CALC, headers=farmer.headers, json=calc_body())
    assert r.status_code == 200
    body = r.json()
    t = body["totals"]
    assert t["cost"] == {"low": 87000, "expected": 87000, "high": 95700}
    assert t["revenue"] == {"low": 128000, "expected": 288000, "high": 576000}
    assert t["margin"] == {"low": 32300, "expected": 201000, "high": 489000}
    assert t["break_even_revenue"] == 87000 and t["roi_expected_pct"] == 231.03
    item = body["items"][0]
    assert item["break_even"]["price_per_kg_expected"] == 3.63 and item["break_even"]["yield_kg_per_acre"] == 3625
    assert item["cost_breakdown"]["labour"] == 48000 and item["cost_per_acre"] == 41000
    assert body["risk"]["score"] == 43.8 and body["risk"]["level"] == "medium"
    assert body["confidence"]["score"] == 44 and body["confidence"]["level"] == "low"
    assert body["feasible"] is True and body["findings"] == []
    assert body["period"] == {"start": "2026-11-01", "end": "2027-03-10", "days": 130, "months": 5}


def test_numbers_are_json_numbers_not_strings(db_client, farmer):
    body = db_client.post(CALC, headers=farmer.headers, json=calc_body()).json()
    assert isinstance(body["totals"]["revenue"]["expected"], int | float)
    assert isinstance(body["items"][0]["break_even"]["price_per_kg_expected"], float)


def test_results_explain_themselves_and_never_promise(db_client, farmer):
    body = db_client.post(CALC, headers=farmer.headers, json=calc_body()).json()
    assert "do not guarantee" in body["disclaimer"]
    assert body["assumptions"] and body["explanations"] and body["items"][0]["explanations"]
    assert {c["name"] for c in body["risk"]["components"]} == {
        "crop_risk",
        "concentration",
        "income_gaps",
        "resource_pressure",
    }
    assert all(c["detail"] for c in body["items"][0]["risk"]["components"])
    totals = body["totals"]
    assert totals["revenue"]["low"] < totals["revenue"]["expected"] < totals["revenue"]["high"]  # always a range


def test_calculate_is_deterministic(db_client, farmer):
    first = db_client.post(CALC, headers=farmer.headers, json=calc_body(item_body(), ragi_body(), land=10))
    second = db_client.post(CALC, headers=farmer.headers, json=calc_body(item_body(), ragi_body(), land=10))
    assert first.json() == second.json()


def test_multi_crop_plan_sums_its_crops(db_client, farmer):
    body = db_client.post(CALC, headers=farmer.headers, json=calc_body(item_body(), ragi_body(), land=10)).json()
    assert [i["crop_name"] for i in body["items"]] == ["Tomato", "Ragi"]
    assert body["totals"]["cost"]["expected"] == sum(i["cost"]["expected"] for i in body["items"])
    assert body["totals"]["revenue"]["expected"] == pytest.approx(sum(i["revenue"]["expected"] for i in body["items"]))
    assert body["totals"]["area_sown_acres"] == 6


def test_exceeding_land_is_reported_as_infeasible_not_as_an_error(db_client, farmer):
    r = db_client.post(
        CALC,
        headers=farmer.headers,
        json=calc_body(item_body(area_acres=3), item_body(crop_name="B", area_acres=3), land=5),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["feasible"] is False
    (f,) = [f for f in body["findings"] if f["code"] == "land_exceeded"]
    assert f["severity"] == "hard" and f["details"] == {"peak_acres": 6, "available_acres": 5}
    assert body["land"]["first_over_limit_on"] == "2026-11-01"


def test_exceeding_budget_is_reported_as_infeasible(db_client, farmer):
    body = db_client.post(CALC, headers=farmer.headers, json=calc_body(budget_inr=50000)).json()
    assert body["feasible"] is False and body["budget"]["headroom_expected"] == -37000
    assert [f["code"] for f in body["findings"] if f["severity"] == "hard"] == ["budget_exceeded"]


def test_budget_exactly_equal_to_cost_is_feasible_with_a_warning(db_client, farmer):
    body = db_client.post(CALC, headers=farmer.headers, json=calc_body(budget_inr=87000)).json()
    assert body["feasible"] is True and "budget_at_risk" in [f["code"] for f in body["findings"]]


def test_land_is_checked_over_time_not_just_in_total(db_client, farmer):
    two = calc_body(ragi_body(), item_body(area_acres=4), land=5)  # 8 acres sown in total, never more than 4 at once
    body = db_client.post(CALC, headers=farmer.headers, json=two).json()
    assert (
        body["feasible"] is True and body["totals"]["area_sown_acres"] == 8 and body["land"]["peak_in_use_acres"] == 4
    )


def test_staggered_planting_changes_land_and_income_timing(db_client, farmer):
    stagger = item_body(area_acres=3, batches=3, batch_interval_days=100, duration_days=60, harvest_window_days=10)
    body = db_client.post(CALC, headers=farmer.headers, json=calc_body(stagger, land=3)).json()
    assert body["land"]["peak_in_use_acres"] == 1  # one acre at a time
    assert [b["sowing_date"] for b in body["items"][0]["batches"]] == ["2026-11-01", "2027-02-09", "2027-05-20"]
    c = body["continuity"]  # harvests: Dec 31-Jan 9, Apr 10-19, Jul 19-28
    assert c["income_months"] == 4 and c["level"] == "gapped"
    assert c["gap_month_list"] == ["2027-02", "2027-03", "2027-05", "2027-06"] and c["longest_gap_months"] == 2
    assert c["advice"]


def test_every_optional_input_is_accepted(db_client, farmer):
    full = item_body(
        water_kl_per_acre=40,
        demand_level="high",
        demand_quantity_kg=20000,
        declared_risk="low",
        estimate_basis="own_records",
        cost={**item_body()["cost"], "overrun_pct": 15},
    )
    body = db_client.post(
        CALC,
        headers=farmer.headers,
        json=calc_body(
            full, season="rabi", budget_inr=150000, available_water_kl=500, available_labour_person_days=400
        ),
    ).json()
    assert body["items"][0]["overrun_pct"] == 15 and body["items"][0]["demand_limited"] is True
    assert body["water"]["required"] == 80 and body["labour"]["required"] == 120 and body["budget"]["budget"] == 150000
    assert body["items"][0]["sold_kg"]["expected"] == 20000


def test_calculate_stores_nothing(db_client, db_container, farmer):
    db_client.post(CALC, headers=farmer.headers, json=calc_body())
    with db_container.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM crop_plans")) == 0
        assert conn.scalar(text("SELECT count(*) FROM crop_plan_items")) == 0


# ------------------------------------------------------------- invalid input


def with_item(**changes):
    return calc_body(item_body(**changes))


@pytest.mark.parametrize(
    ("body", "field"),
    [
        (with_item(yield_per_acre_kg={"low": 9000, "expected": 8000, "high": 12000}), "items.0.yield_per_acre_kg"),
        (with_item(yield_per_acre_kg={"low": 1, "expected": 5, "high": 4}), "items.0.yield_per_acre_kg"),
        (with_item(yield_per_acre_kg={"low": 0, "expected": 0, "high": 0}), "items.0.yield_per_acre_kg.expected"),
        (with_item(yield_per_acre_kg={"low": -1, "expected": 5, "high": 9}), "items.0.yield_per_acre_kg.low"),
        (with_item(price_per_kg={"low": 20, "expected": 12, "high": 18}), "items.0.price_per_kg"),
        (with_item(price_per_kg={"low": 8, "expected": 12.345, "high": 18}), "items.0.price_per_kg.expected"),
        (with_item(area_acres=0), "items.0.area_acres"),
        (with_item(area_acres=-3), "items.0.area_acres"),
        (with_item(area_acres=1.2345), "items.0.area_acres"),
        (with_item(duration_days=0), "items.0.duration_days"),
        (with_item(duration_days=None), "items.0"),
        (with_item(crop_name=None), "items.0"),
        (with_item(crop_name="   "), "items.0.crop_name"),
        (with_item(harvest_window_days=0), "items.0.harvest_window_days"),
        (with_item(harvest_window_days=400), "items.0.harvest_window_days"),
        (with_item(batches=0), "items.0.batches"),
        (with_item(batches=13, batch_interval_days=10), "items.0.batches"),
        (with_item(batches=3), "items.0"),  # interval missing
        (with_item(batches=3, batch_interval_days=0), "items.0.batch_interval_days"),
        (with_item(area_acres=0.005, batches=12, batch_interval_days=5), "items.0"),  # batches under 0.001 acre
        (with_item(cost={"seed_per_acre": -1}), "items.0.cost.seed_per_acre"),
        (with_item(cost={"overrun_pct": -5}), "items.0.cost.overrun_pct"),
        (with_item(cost={"overrun_pct": 501}), "items.0.cost.overrun_pct"),
        (with_item(cost={"fixed_cost": "lots"}), "items.0.cost.fixed_cost"),
        (with_item(demand_quantity_kg=0), "items.0.demand_quantity_kg"),
        (with_item(water_kl_per_acre=-1), "items.0.water_kl_per_acre"),
        (with_item(demand_level="enormous"), "items.0.demand_level"),
        (with_item(declared_risk="reckless"), "items.0.declared_risk"),
        (with_item(estimate_basis="vibes"), "items.0.estimate_basis"),
        (with_item(sowing_date="not-a-date"), "items.0.sowing_date"),
        (with_item(sowing_date="1999-12-31"), "items.0"),
        (with_item(surprise=1), "items.0.surprise"),
        (with_item(crop_id="7d6e2b7a-8f3a-4c43-9b8a-0a3a7a0d5a11"), "items.0.crop_id"),  # no catalog in stateless mode
        (calc_body(land=0), "available_land_acres"),
        (calc_body(land=-1), "available_land_acres"),
        (calc_body(budget_inr=0), "budget_inr"),
        (calc_body(budget_inr=-100), "budget_inr"),
        (calc_body(available_water_kl=0), "available_water_kl"),
        (calc_body(available_labour_person_days=-1), "available_labour_person_days"),
        (calc_body(season="monsoon"), "season"),
        ({"items": [item_body()]}, "available_land_acres"),
        ({"available_land_acres": 5}, "items"),
        (calc_body(*[]) | {"items": []}, "items"),
        (calc_body(*[item_body() for _ in range(31)]), "items"),
    ],
)
def test_invalid_calculator_inputs_are_rejected(db_client, farmer, body, field):
    r = db_client.post(CALC, headers=farmer.headers, json=body)
    found = errors(r)
    assert any(f == field or f.startswith(field + ".") for f in found), (field, found)


def test_error_responses_use_the_standard_envelope_and_never_echo_values(db_client, farmer):
    r = db_client.post(CALC, headers=farmer.headers, json=with_item(crop_name="X" * 81, surprise="secret-value-123"))
    assert set(r.json()) == {"error"} and "secret-value-123" not in r.text


def test_malformed_json_is_a_validation_error(db_client, farmer):
    r = db_client.post(CALC, headers={**farmer.headers, "Content-Type": "application/json"}, content="{nope")
    assert r.status_code == 422 and r.json()["error"]["code"] == "request_validation_error"


def test_a_failed_request_changes_nothing_and_a_retry_works(db_client, farmer):
    bad = copy.deepcopy(calc_body())
    bad["items"][0]["area_acres"] = 0
    assert db_client.post(CALC, headers=farmer.headers, json=bad).status_code == 422
    assert db_client.post(CALC, headers=farmer.headers, json=calc_body()).status_code == 200


# ------------------------------------------------------------------ allocation


def suggest_body(*candidates, land=10, **overrides):
    body = {"available_land_acres": land, "candidates": list(candidates)}
    body.update(overrides)
    return body


def test_suggest_allocation_splits_land_and_names_the_binding_limit(db_client, farmer):
    tomato = candidate_body("Tomato")
    ragi = candidate_body(
        "Ragi",
        sowing_date="2026-06-15",
        duration_days=120,
        harvest_window_days=15,
        yield_per_acre_kg={"low": 600, "expected": 900, "high": 1200},
        price_per_kg={"low": 25, "expected": 32, "high": 40},
        cost={"seed_per_acre": 800},
    )
    r = db_client.post(SUGGEST, headers=farmer.headers, json=suggest_body(tomato, ragi, land=6, max_crop_share_pct=50))
    assert r.status_code == 200
    body = r.json()
    assert body["rank_by"] == "margin_per_acre" and body["ranking"][0] == 0  # tomato earns more per acre
    by_name = {a["crop_name"]: a for a in body["allocations"]}
    assert by_name["Tomato"]["area_acres"] == 3 and by_name["Tomato"]["limited_by"] == "max_crop_share"
    assert all(a["reason"] for a in body["allocations"]) and body["notes"]
    assert body["plan"]["feasible"] is True  # the suggestion is evaluated for you


def test_suggested_items_can_be_fed_straight_back_into_the_calculator(db_client, farmer):
    req = suggest_body(candidate_body("Tomato"), land=4, budget_inr=200000)
    suggestion = db_client.post(SUGGEST, headers=farmer.headers, json=req).json()
    again = db_client.post(
        CALC,
        headers=farmer.headers,
        json={"available_land_acres": 4, "budget_inr": 200000, "items": suggestion["suggested_items"]},
    )
    assert again.status_code == 200 and again.json() == suggestion["plan"]  # same engine, same answer


def test_budget_limits_the_suggestion(db_client, farmer):
    body = db_client.post(
        SUGGEST,
        headers=farmer.headers,
        json=suggest_body(candidate_body("Tomato", cost={"seed_per_acre": 40000}), land=10, budget_inr=100000),
    ).json()
    (a,) = body["allocations"]
    assert a["area_acres"] == 2.5 and a["limited_by"] == "budget"
    assert body["plan"]["budget"]["expected_cost"] <= 100000


def test_unprofitable_candidates_are_excluded_with_reasons(db_client, farmer):
    loser = candidate_body("Loser", price_per_kg={"low": 1, "expected": 2, "high": 3})
    body = db_client.post(SUGGEST, headers=farmer.headers, json=suggest_body(candidate_body("Tomato"), loser)).json()
    assert [e["code"] for e in body["excluded"]] == ["non_positive_margin"] and body["excluded"][0][
        "crop_name"
    ] == "Loser"


def test_nothing_allocatable_returns_an_empty_suggestion(db_client, farmer):
    loser = candidate_body("Loser", price_per_kg={"low": 1, "expected": 2, "high": 3})
    body = db_client.post(SUGGEST, headers=farmer.headers, json=suggest_body(loser)).json()
    assert body["allocations"] == [] and body["suggested_items"] == [] and body["plan"] is None


def test_return_on_cost_ranking_is_selectable(db_client, farmer):
    pricey = candidate_body(
        "Pricey", price_per_kg={"low": 30, "expected": 40, "high": 50}, cost={"seed_per_acre": 200000}
    )
    lean = candidate_body("Lean")
    by_roi = db_client.post(
        SUGGEST, headers=farmer.headers, json=suggest_body(pricey, lean, rank_by="return_on_cost")
    ).json()
    assert by_roi["rank_by"] == "return_on_cost" and by_roi["ranking"][0] == 1  # Lean has the better return on cost


@pytest.mark.parametrize(
    ("body", "field"),
    [
        (suggest_body(), "candidates"),
        (suggest_body(candidate_body(), land=0), "available_land_acres"),
        (suggest_body(candidate_body(), max_crop_share_pct=0), "max_crop_share_pct"),
        (suggest_body(candidate_body(), max_crop_share_pct=101), "max_crop_share_pct"),
        (suggest_body(candidate_body(), rank_by="vibes"), "rank_by"),
        (suggest_body(candidate_body(), budget_inr=-1), "budget_inr"),
        (suggest_body(candidate_body(min_area_acres=2, max_area_acres=1)), "candidates.0"),
        (suggest_body(candidate_body(min_area_acres=0)), "candidates.0.min_area_acres"),
        (suggest_body(candidate_body(duration_days=None)), "candidates.0"),
        (suggest_body(candidate_body(area_acres=2)), "candidates.0.area_acres"),  # the allocator decides the area
        (suggest_body(*[candidate_body(f"C{i}") for i in range(21)]), "candidates"),
    ],
)
def test_invalid_allocation_requests_are_rejected(db_client, farmer, body, field):
    found = errors(db_client.post(SUGGEST, headers=farmer.headers, json=body))
    assert any(f == field or f.startswith(field + ".") for f in found), (field, found)


def test_allocation_is_deterministic(db_client, farmer):
    req = suggest_body(candidate_body("A"), candidate_body("B"), candidate_body("C"), land=7, max_crop_share_pct=40)
    assert (
        db_client.post(SUGGEST, headers=farmer.headers, json=req).json()
        == db_client.post(SUGGEST, headers=farmer.headers, json=req).json()
    )


# ---------------------------------------------------------------- access


@pytest.mark.parametrize("url", [CALC, SUGGEST])
def test_planning_tools_are_farmer_only(db_client, farmer, buyer, admin, url):
    body = calc_body() if url == CALC else suggest_body(candidate_body())
    assert db_client.post(url, json=body).status_code == 401
    assert db_client.post(url, headers=buyer.headers, json=body).status_code == 403
    assert db_client.post(url, headers=admin.headers, json=body).status_code == 403
    assert db_client.post(url, headers=farmer.headers, json=body).status_code == 200
