"""Saved planning scenarios: CRUD, ownership, catalog/farm links, evaluation, comparison, duplication."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.planning_factory import calc_body, item_body, ragi_body

pytestmark = pytest.mark.integration
PLANS = "/api/v1/crop-plans"
CALC = "/api/v1/planning/calculate"


def plan_url(plan_id: str, suffix: str = "") -> str:
    return f"{PLANS}/{plan_id}{suffix}"


def item_url(item_id: str) -> str:
    return f"/api/v1/crop-plan-items/{item_id}"


def code(response) -> str:
    return response.json()["error"]["code"]


def make_plan(client, actor, name="Rabi plan", land=5, items=(), **extra):
    r = client.post(
        PLANS, headers=actor.headers, json={"name": name, "available_land_acres": land, "items": list(items), **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def plan(db_client, farmer):
    return make_plan(db_client, farmer, items=[item_body()])


# ------------------------------------------------------------------- create


def test_create_plan_with_items(db_client, farmer):
    r = db_client.post(
        PLANS,
        headers=farmer.headers,
        json={
            "name": "Kharif 2026",
            "description": "Main season",
            "season": "kharif",
            "available_land_acres": 6,
            "budget_inr": 250000,
            "available_water_kl": 900,
            "available_labour_person_days": 500,
            "items": [item_body(), ragi_body()],
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Kharif 2026" and body["season"] == "kharif" and body["budget_inr"] == 250000
    assert [i["crop_name"] for i in body["items"]] == ["Tomato", "Ragi"] and [i["position"] for i in body["items"]] == [
        0,
        1,
    ]
    first = body["items"][0]
    assert first["yield_per_acre_kg"] == {"low": 8000, "expected": 12000, "high": 16000}
    assert first["cost"]["labour_person_days_per_acre"] == 60 and first["cost"]["fixed_cost"] == 5000
    assert first["plan_id"] == body["id"] and first["crop_id"] is None


def test_create_plan_without_items(db_client, farmer):
    body = make_plan(db_client, farmer)
    assert body["items"] == [] and body["season"] == "year_round" and body["budget_inr"] is None


def test_catalog_crop_supplies_name_and_duration(db_client, api, farmer, crop):
    item = item_body()
    for key in ("crop_name", "duration_days"):
        del item[key]
    item["crop_id"] = crop["id"]  # catalog: Tomato, 100 days
    plan = make_plan(db_client, farmer, items=[item])
    saved = plan["items"][0]
    assert saved["crop_id"] == crop["id"] and saved["crop_name"] == "Tomato" and saved["duration_days"] == 100


def test_explicit_values_override_the_catalog_defaults(db_client, farmer, crop):
    saved = make_plan(
        db_client, farmer, items=[item_body(crop_id=crop["id"], crop_name="Hybrid tomato", duration_days=120)]
    )["items"][0]
    assert saved["crop_name"] == "Hybrid tomato" and saved["duration_days"] == 120 and saved["crop_id"] == crop["id"]


def test_unknown_or_inactive_catalog_crop_is_rejected(db_client, farmer, admin, crop):
    body = {
        "name": "P",
        "available_land_acres": 5,
        "items": [item_body(crop_id="7d6e2b7a-8f3a-4c43-9b8a-0a3a7a0d5a11")],
    }
    r = db_client.post(PLANS, headers=farmer.headers, json=body)
    assert r.status_code == 422 and code(r) == "crop_not_found"
    db_client.patch(f"/api/v1/crops/{crop['id']}", headers=admin.headers, json={"is_active": False})
    r = db_client.post(PLANS, headers=farmer.headers, json={**body, "items": [item_body(crop_id=crop["id"])]})
    assert r.status_code == 422 and code(r) == "crop_inactive"


def test_failed_creation_leaves_nothing_behind(db_client, db_container, farmer):
    bad = db_client.post(
        PLANS,
        headers=farmer.headers,
        json={
            "name": "P",
            "available_land_acres": 5,
            "items": [item_body(), item_body(crop_id="7d6e2b7a-8f3a-4c43-9b8a-0a3a7a0d5a11")],
        },
    )
    assert bad.status_code == 422
    with db_container.engine.connect() as conn:
        assert (
            conn.scalar(text("SELECT count(*) FROM crop_plans")) == 0
            and conn.scalar(text("SELECT count(*) FROM crop_plan_items")) == 0
        )


@pytest.mark.parametrize(
    "body",
    [
        {"available_land_acres": 5},  # no name
        {"name": "P"},  # neither land nor farm
        {"name": "P", "available_land_acres": 0},
        {"name": "P", "available_land_acres": 5, "budget_inr": 0},
        {"name": "P", "available_land_acres": 5, "season": "monsoon"},
        {"name": "  ", "available_land_acres": 5},
        {"name": "P", "available_land_acres": 5, "owner_id": "x"},
        {"name": "P", "available_land_acres": 5, "items": [item_body(area_acres=0)]},
        {"name": "P", "available_land_acres": 5, "items": [{"crop_name": "Tomato"}]},
        {
            "name": "P",
            "available_land_acres": 5,
            "items": [item_body(crop_name=None, duration_days=None)],
        },  # no crop at all
        {"name": "P", "available_land_acres": 5, "items": [item_body()] * 31},
    ],
)
def test_invalid_plans_are_rejected(db_client, farmer, body):
    r = db_client.post(PLANS, headers=farmer.headers, json=body)
    assert r.status_code == 422 and code(r) == "request_validation_error"


def test_plan_names_are_unique_per_farmer_case_insensitively(db_client, farmer, other_farmer):
    make_plan(db_client, farmer, name="Plan A")
    r = db_client.post(PLANS, headers=farmer.headers, json={"name": "plan a", "available_land_acres": 1})
    assert r.status_code == 409 and code(r) == "plan_name_taken"
    assert make_plan(db_client, other_farmer, name="Plan A")["id"]  # another farmer may reuse it


# ------------------------------------------------------------------ farm link


def test_land_defaults_to_the_linked_farms_area(db_client, farmer, farm):
    r = db_client.post(PLANS, headers=farmer.headers, json={"name": "P", "farm_id": farm["id"]})
    assert (
        r.status_code == 201
        and r.json()["available_land_acres"] == farm["total_area_acres"]
        and r.json()["farm_id"] == farm["id"]
    )


def test_available_land_cannot_exceed_the_farm(db_client, farmer, farm):
    over = db_client.post(
        PLANS, headers=farmer.headers, json={"name": "P", "farm_id": farm["id"], "available_land_acres": 10.001}
    )
    assert over.status_code == 422 and code(over) == "plan_land_exceeds_farm"
    ok = db_client.post(
        PLANS, headers=farmer.headers, json={"name": "P", "farm_id": farm["id"], "available_land_acres": 10}
    )
    assert ok.status_code == 201


def test_cannot_link_someone_elses_farm(db_client, api, farmer, other_farmer):
    theirs = api.farm(other_farmer, name="Theirs")
    r = db_client.post(
        PLANS, headers=farmer.headers, json={"name": "P", "farm_id": theirs["id"], "available_land_acres": 1}
    )
    assert r.status_code == 422 and code(r) == "farm_not_found"  # indistinguishable from a farm that does not exist


def test_a_farm_with_plans_cannot_be_deleted(db_client, farmer, farm):
    db_client.post(PLANS, headers=farmer.headers, json={"name": "P", "farm_id": farm["id"]})
    r = db_client.delete(f"/api/v1/farms/{farm['id']}", headers=farmer.headers)
    assert r.status_code == 409 and code(r) == "farm_not_empty"


def test_filter_plans_by_farm(db_client, api, farmer, farm):
    make_plan(db_client, farmer, name="Free-standing")
    linked = db_client.post(PLANS, headers=farmer.headers, json={"name": "On farm", "farm_id": farm["id"]}).json()
    only = db_client.get(PLANS, headers=farmer.headers, params={"farm_id": farm["id"]}).json()
    assert [p["id"] for p in only["items"]] == [linked["id"]] and db_client.get(PLANS, headers=farmer.headers).json()[
        "total"
    ] == 2


# --------------------------------------------------------------- read / list


def test_get_plan_returns_inputs_not_results(db_client, farmer, plan):
    body = db_client.get(plan_url(plan["id"]), headers=farmer.headers).json()
    assert body == plan and "totals" not in body and "risk" not in body


def test_list_is_scoped_summarised_and_paginated(db_client, farmer, other_farmer):
    for name in ("A", "B", "C"):
        make_plan(db_client, farmer, name=name, items=[item_body()])
    make_plan(db_client, other_farmer, name="Not mine")
    page = db_client.get(PLANS, headers=farmer.headers, params={"limit": 2}).json()
    assert (
        page["total"] == 3
        and len(page["items"]) == 2
        and "items" not in page["items"][0]
        and page["items"][0]["item_count"] == 1
    )
    assert "Not mine" not in {p["name"] for p in db_client.get(PLANS, headers=farmer.headers).json()["items"]}


# ----------------------------------------------------------------- ownership


def test_other_farmers_cannot_see_or_touch_a_plan(db_client, plan, other_farmer):
    h, pid = other_farmer.headers, plan["id"]
    item_id = plan["items"][0]["id"]
    checks = [
        db_client.get(plan_url(pid), headers=h),
        db_client.patch(plan_url(pid), headers=h, json={"name": "Hacked"}),
        db_client.delete(plan_url(pid), headers=h),
        db_client.get(plan_url(pid, "/evaluation"), headers=h),
        db_client.post(plan_url(pid, "/duplicate"), headers=h, json={"name": "Copy"}),
        db_client.post(plan_url(pid, "/items"), headers=h, json=item_body()),
        db_client.get(item_url(item_id), headers=h),
        db_client.patch(item_url(item_id), headers=h, json={"notes": "x"}),
        db_client.delete(item_url(item_id), headers=h),
    ]
    assert [r.status_code for r in checks] == [404] * len(checks)


def test_a_failed_attack_changes_nothing(db_client, farmer, plan, other_farmer):
    db_client.patch(plan_url(plan["id"]), headers=other_farmer.headers, json={"name": "Hacked"})
    db_client.delete(plan_url(plan["id"]), headers=other_farmer.headers)
    assert db_client.get(plan_url(plan["id"]), headers=farmer.headers).json()["name"] == "Rabi plan"


# -------------------------------------------------------------------- update


def test_update_plan_constraints(db_client, farmer, plan):
    r = db_client.patch(
        plan_url(plan["id"]), headers=farmer.headers, json={"budget_inr": 90000, "season": "rabi", "name": "Renamed"}
    )
    assert r.status_code == 200 and (r.json()["budget_inr"], r.json()["season"], r.json()["name"]) == (
        90000,
        "rabi",
        "Renamed",
    )
    cleared = db_client.patch(plan_url(plan["id"]), headers=farmer.headers, json={"budget_inr": None})
    assert cleared.json()["budget_inr"] is None  # None = no budget limit


@pytest.mark.parametrize("field", ["name", "season", "available_land_acres"])
def test_required_plan_fields_cannot_be_nulled(db_client, farmer, plan, field):
    assert db_client.patch(plan_url(plan["id"]), headers=farmer.headers, json={field: None}).status_code == 422


def test_update_revalidates_the_farm_link(db_client, farmer, farm, plan):
    linked = db_client.patch(plan_url(plan["id"]), headers=farmer.headers, json={"farm_id": farm["id"]})
    assert linked.status_code == 200 and linked.json()["available_land_acres"] == 5
    over = db_client.patch(plan_url(plan["id"]), headers=farmer.headers, json={"available_land_acres": 11})
    assert over.status_code == 422 and code(over) == "plan_land_exceeds_farm"
    unlinked = db_client.patch(
        plan_url(plan["id"]), headers=farmer.headers, json={"farm_id": None, "available_land_acres": 11}
    )
    assert unlinked.status_code == 200


def test_rename_conflict(db_client, farmer, plan):
    make_plan(db_client, farmer, name="Other")
    assert db_client.patch(plan_url(plan["id"]), headers=farmer.headers, json={"name": "OTHER"}).status_code == 409


def test_shrinking_land_below_the_crops_is_allowed_but_flagged(db_client, farmer, plan):
    """Plans are scenarios: an over-committed one is saved and reported infeasible, not refused."""
    assert (
        db_client.patch(plan_url(plan["id"]), headers=farmer.headers, json={"available_land_acres": 1}).status_code
        == 200
    )
    evaluation = db_client.get(plan_url(plan["id"], "/evaluation"), headers=farmer.headers).json()
    assert evaluation["feasible"] is False and "land_exceeded" in [f["code"] for f in evaluation["findings"]]


# ---------------------------------------------------------------- evaluation


def test_evaluation_equals_the_stateless_calculator(db_client, farmer):
    saved = make_plan(db_client, farmer, land=10, budget_inr=300000, items=[item_body(), ragi_body()])
    from_saved = db_client.get(plan_url(saved["id"], "/evaluation"), headers=farmer.headers).json()
    direct = db_client.post(
        CALC, headers=farmer.headers, json=calc_body(item_body(), ragi_body(), land=10, budget_inr=300000)
    ).json()
    assert from_saved == direct


def test_evaluation_reflects_edits_immediately(db_client, farmer, plan):
    before = db_client.get(plan_url(plan["id"], "/evaluation"), headers=farmer.headers).json()["totals"]["cost"][
        "expected"
    ]
    db_client.patch(item_url(plan["items"][0]["id"]), headers=farmer.headers, json={"area_acres": 1})
    after = db_client.get(plan_url(plan["id"], "/evaluation"), headers=farmer.headers).json()["totals"]["cost"][
        "expected"
    ]
    assert (before, after) == (87000, 46000)  # 41,000 x 1 acre + 5,000 fixed


def test_empty_plan_cannot_be_evaluated(db_client, farmer):
    empty = make_plan(db_client, farmer, name="Empty")
    r = db_client.get(plan_url(empty["id"], "/evaluation"), headers=farmer.headers)
    assert r.status_code == 409 and code(r) == "plan_has_no_items"


def test_catalog_season_feeds_the_evaluation(db_client, api, farmer, admin):
    kharif = api.crop(admin, name="Cotton", category="cash_crop", season="kharif")
    plan = make_plan(
        db_client, farmer, season="rabi", items=[item_body(crop_id=kharif["id"], sowing_date="2026-11-01")]
    )
    findings = db_client.get(plan_url(plan["id"], "/evaluation"), headers=farmer.headers).json()["findings"]
    assert "crop_season_mismatch" in [f["code"] for f in findings]


def test_infeasible_plans_are_still_saved_and_evaluated(db_client, farmer):
    over = make_plan(db_client, farmer, land=1, budget_inr=1000, items=[item_body(area_acres=4)])
    body = db_client.get(plan_url(over["id"], "/evaluation"), headers=farmer.headers).json()
    assert body["feasible"] is False and {"land_exceeded", "budget_exceeded"} <= {f["code"] for f in body["findings"]}


# --------------------------------------------------------------------- items


def test_add_item(db_client, farmer, plan):
    r = db_client.post(plan_url(plan["id"], "/items"), headers=farmer.headers, json=ragi_body())
    assert r.status_code == 201 and r.json()["position"] == 1 and r.json()["crop_name"] == "Ragi"
    assert [i["crop_name"] for i in db_client.get(plan_url(plan["id"]), headers=farmer.headers).json()["items"]] == [
        "Tomato",
        "Ragi",
    ]


def test_plan_holds_at_most_30_crops(db_client, farmer):
    # distinct sowing dates: identical crop + date would be a duplicate entry
    full = make_plan(db_client, farmer, items=[item_body(sowing_date=f"2026-11-{d:02d}") for d in range(1, 31)])
    r = db_client.post(plan_url(full["id"], "/items"), headers=farmer.headers, json=item_body(sowing_date="2026-12-01"))
    assert r.status_code == 409 and code(r) == "too_many_items"


@pytest.mark.parametrize(
    "bad",
    [
        item_body(yield_per_acre_kg={"low": 9, "expected": 5, "high": 12}),
        item_body(area_acres=-1),
        item_body(batches=4),
        item_body(cost={"fixed_cost": -5}),
        item_body(price_per_kg={"low": 1, "expected": 0, "high": 2}),
    ],
)
def test_invalid_items_are_rejected_and_not_stored(db_client, farmer, plan, bad):
    assert db_client.post(plan_url(plan["id"], "/items"), headers=farmer.headers, json=bad).status_code == 422
    assert len(db_client.get(plan_url(plan["id"]), headers=farmer.headers).json()["items"]) == 1


def test_get_update_and_delete_item(db_client, farmer, plan):
    iid = plan["items"][0]["id"]
    assert db_client.get(item_url(iid), headers=farmer.headers).json()["id"] == iid
    r = db_client.patch(
        item_url(iid),
        headers=farmer.headers,
        json={
            "area_acres": 1.5,
            "yield_per_acre_kg": {"low": 7000, "expected": 11000, "high": 15000},
            "cost": {"seed_per_acre": 100},
            "demand_quantity_kg": 9000,
            "notes": "Revised",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert (
        body["area_acres"] == 1.5
        and body["yield_per_acre_kg"]["expected"] == 11000
        and body["demand_quantity_kg"] == 9000
    )
    assert (
        body["cost"]["seed_per_acre"] == 100 and body["cost"]["fertilizer_per_acre"] == 0
    )  # the cost block is replaced whole
    assert body["price_per_kg"]["expected"] == 12 and body["crop_name"] == "Tomato"  # untouched fields survive
    assert db_client.delete(item_url(iid), headers=farmer.headers).status_code == 204
    assert db_client.get(item_url(iid), headers=farmer.headers).status_code == 404
    assert db_client.get(plan_url(plan["id"]), headers=farmer.headers).json()["items"] == []


def test_clearing_nullable_item_fields(db_client, farmer):
    plan = make_plan(db_client, farmer, items=[item_body(demand_quantity_kg=5000, water_kl_per_acre=30)])
    iid = plan["items"][0]["id"]
    r = db_client.patch(
        item_url(iid), headers=farmer.headers, json={"demand_quantity_kg": None, "water_kl_per_acre": None}
    )
    assert r.json()["demand_quantity_kg"] is None and r.json()["water_kl_per_acre"] is None


@pytest.mark.parametrize(
    "field",
    [
        "crop_name",
        "area_acres",
        "sowing_date",
        "duration_days",
        "yield_per_acre_kg",
        "price_per_kg",
        "cost",
        "batches",
        "demand_level",
    ],
)
def test_required_item_fields_cannot_be_nulled(db_client, farmer, plan, field):
    assert (
        db_client.patch(item_url(plan["items"][0]["id"]), headers=farmer.headers, json={field: None}).status_code == 422
    )


def test_an_update_that_would_make_the_item_unusable_is_rejected_and_not_applied(db_client, farmer, plan):
    iid = plan["items"][0]["id"]
    r = db_client.patch(item_url(iid), headers=farmer.headers, json={"batches": 3})  # no interval stored
    assert r.status_code == 422 and code(r) == "batch_interval_required"
    assert db_client.get(item_url(iid), headers=farmer.headers).json()["batches"] == 1
    assert db_client.get(plan_url(plan["id"], "/evaluation"), headers=farmer.headers).status_code == 200
    ok = db_client.patch(item_url(iid), headers=farmer.headers, json={"batches": 3, "batch_interval_days": 20})
    assert ok.status_code == 200 and ok.json()["batches"] == 3


def test_relinking_an_item_to_a_catalog_crop(db_client, api, farmer, admin, plan):
    iid = plan["items"][0]["id"]
    onion = api.crop(admin, name="Onion", typical_duration_days=120)
    linked = db_client.patch(item_url(iid), headers=farmer.headers, json={"crop_id": onion["id"]}).json()
    assert linked["crop_id"] == onion["id"] and linked["crop_name"] == "Onion" and linked["duration_days"] == 100
    unlinked = db_client.patch(item_url(iid), headers=farmer.headers, json={"crop_id": None}).json()
    assert unlinked["crop_id"] is None and unlinked["crop_name"] == "Onion"
    missing = db_client.patch(
        item_url(iid), headers=farmer.headers, json={"crop_id": "7d6e2b7a-8f3a-4c43-9b8a-0a3a7a0d5a11"}
    )
    assert missing.status_code == 422 and code(missing) == "crop_not_found"


def test_item_cannot_be_moved_to_another_plan(db_client, farmer, plan):
    assert (
        db_client.patch(
            item_url(plan["items"][0]["id"]),
            headers=farmer.headers,
            json={"plan_id": "7d6e2b7a-8f3a-4c43-9b8a-0a3a7a0d5a11"},
        ).status_code
        == 422
    )


# ------------------------------------------------------------ catalog protection


def test_a_crop_used_by_a_plan_cannot_be_deleted(db_client, farmer, admin, crop):
    plan = make_plan(db_client, farmer, items=[item_body(crop_id=crop["id"])])
    r = db_client.delete(f"/api/v1/crops/{crop['id']}", headers=admin.headers)
    assert r.status_code == 409 and code(r) == "crop_in_use"
    db_client.delete(plan_url(plan["id"]), headers=farmer.headers)
    assert db_client.delete(f"/api/v1/crops/{crop['id']}", headers=admin.headers).status_code == 204


# ------------------------------------------------------------------ delete plan


def test_deleting_a_plan_deletes_its_items(db_client, db_container, farmer, plan):
    assert db_client.delete(plan_url(plan["id"]), headers=farmer.headers).status_code == 204
    assert db_client.get(plan_url(plan["id"]), headers=farmer.headers).status_code == 404
    with db_container.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM crop_plan_items")) == 0


# -------------------------------------------------------------------- compare


def test_compare_ranks_feasible_plans_by_expected_margin(db_client, farmer):
    small = make_plan(db_client, farmer, name="Small", items=[item_body(area_acres=1)])
    big = make_plan(db_client, farmer, name="Big", items=[item_body(area_acres=3)])
    r = db_client.get(
        f"{PLANS}/compare", headers=farmer.headers, params=[("plan_id", small["id"]), ("plan_id", big["id"])]
    )
    assert r.status_code == 200
    body = r.json()
    assert [row["name"] for row in body["rows"]] == ["Small", "Big"]  # the order requested
    assert body["best_expected_margin_plan_id"] == big["id"] and "not guarantees" in body["note"]
    row = body["rows"][1]
    assert row["feasible"] is True and row["margin"]["expected"] > body["rows"][0]["margin"]["expected"]
    assert {"cost", "revenue", "margin", "risk", "confidence", "planning_period", "continuity"} <= set(row)


def test_an_infeasible_plan_is_never_the_best(db_client, farmer):
    fits = make_plan(db_client, farmer, name="Fits", land=3, items=[item_body(area_acres=1)])
    greedy = make_plan(
        db_client, farmer, name="Greedy", land=1, items=[item_body(area_acres=5)]
    )  # bigger margin, but over the land
    body = db_client.get(
        f"{PLANS}/compare", headers=farmer.headers, params=[("plan_id", fits["id"]), ("plan_id", greedy["id"])]
    ).json()
    rows = {r["name"]: r for r in body["rows"]}
    assert rows["Greedy"]["feasible"] is False and rows["Greedy"]["hard_findings"] == 1
    assert rows["Greedy"]["margin"]["expected"] > rows["Fits"]["margin"]["expected"]
    assert body["best_expected_margin_plan_id"] == fits["id"]


def test_compare_with_no_feasible_plan_names_no_winner(db_client, farmer):
    a = make_plan(db_client, farmer, name="A", land=1, items=[item_body(area_acres=5)])
    b = make_plan(db_client, farmer, name="B", land=1, items=[item_body(area_acres=6)])
    body = db_client.get(
        f"{PLANS}/compare", headers=farmer.headers, params=[("plan_id", a["id"]), ("plan_id", b["id"])]
    ).json()
    assert body["best_expected_margin_plan_id"] is None


def test_compare_validation(db_client, farmer, other_farmer, plan):
    mine = make_plan(db_client, farmer, name="Second", items=[item_body()])
    empty = make_plan(db_client, farmer, name="Empty")
    theirs = make_plan(db_client, other_farmer, name="Theirs", items=[item_body()])
    q = lambda *ids: [("plan_id", i) for i in ids]  # noqa: E731
    assert (
        db_client.get(f"{PLANS}/compare", headers=farmer.headers, params=q(plan["id"])).status_code == 422
    )  # need two
    same = db_client.get(f"{PLANS}/compare", headers=farmer.headers, params=q(plan["id"], plan["id"]))
    assert same.status_code == 422 and code(same) == "compare_needs_two"
    assert (
        db_client.get(f"{PLANS}/compare", headers=farmer.headers, params=q(plan["id"], theirs["id"])).status_code == 404
    )
    assert (
        db_client.get(
            f"{PLANS}/compare", headers=farmer.headers, params=q(plan["id"], mine["id"], empty["id"])
        ).status_code
        == 409
    )
    six = [make_plan(db_client, farmer, name=f"P{i}", items=[item_body()])["id"] for i in range(5)] + [plan["id"]]
    assert db_client.get(f"{PLANS}/compare", headers=farmer.headers, params=q(*six)).status_code == 422  # at most five


# ------------------------------------------------------------------ duplicate


def test_duplicate_copies_the_plan_and_its_items(db_client, farmer, plan):
    r = db_client.post(
        plan_url(plan["id"], "/duplicate"), headers=farmer.headers, json={"name": "What if budget is cut"}
    )
    assert r.status_code == 201
    copy = r.json()
    assert copy["id"] != plan["id"] and copy["name"] == "What if budget is cut"
    assert (
        copy["items"][0]["id"] != plan["items"][0]["id"]
        and copy["items"][0]["yield_per_acre_kg"] == plan["items"][0]["yield_per_acre_kg"]
    )
    assert {k: v for k, v in copy.items() if k not in {"id", "name", "items", "created_at", "updated_at"}} == {
        k: v for k, v in plan.items() if k not in {"id", "name", "items", "created_at", "updated_at"}
    }


def test_a_duplicate_is_independent_of_the_original(db_client, farmer, plan):
    copy = db_client.post(plan_url(plan["id"], "/duplicate"), headers=farmer.headers, json={"name": "Copy"}).json()
    db_client.patch(item_url(copy["items"][0]["id"]), headers=farmer.headers, json={"area_acres": 0.5})
    db_client.patch(plan_url(copy["id"]), headers=farmer.headers, json={"budget_inr": 10000})
    original = db_client.get(plan_url(plan["id"]), headers=farmer.headers).json()
    assert original["items"][0]["area_acres"] == 2 and original["budget_inr"] is None


def test_duplicate_name_must_be_new(db_client, farmer, plan):
    assert (
        db_client.post(
            plan_url(plan["id"], "/duplicate"), headers=farmer.headers, json={"name": "rabi PLAN"}
        ).status_code
        == 409
    )
