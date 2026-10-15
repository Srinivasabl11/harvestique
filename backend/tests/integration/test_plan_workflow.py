"""The income-planner journey the app uses: create (linked to a farm) -> add crops -> evaluate -> edit -> reopen.

Numbers are the hand-checked tomato example (tests/planning_factory.py): 2 acres, expected cost 87,000 (high 95,700
with the 10% medium-risk overrun), revenue 128,000 / 288,000 / 576,000, margin 32,300 / 201,000 / 489,000.
"""

from __future__ import annotations

import pytest

from tests.planning_factory import item_body, ragi_body

pytestmark = pytest.mark.integration
PLANS = "/api/v1/crop-plans"


def code(response) -> str:
    return response.json()["error"]["code"]


def test_full_planner_journey_with_known_numbers(db_client, farmer, farm):
    h = farmer.headers
    # create, linked to a farm: land defaults to the farm's 10 acres
    plan = db_client.post(PLANS, headers=h, json={"name": "Kharif 2026", "farm_id": farm["id"]}).json()
    assert plan["available_land_acres"] == 10 and plan["items"] == []

    # add the worked tomato example
    added = db_client.post(f"{PLANS}/{plan['id']}/items", headers=h, json=item_body())
    assert added.status_code == 201, added.text
    t = db_client.get(f"{PLANS}/{plan['id']}/evaluation", headers=h).json()["totals"]
    assert t["cost"] == {"low": 87000, "expected": 87000, "high": 95700}
    assert t["revenue"] == {"low": 128000, "expected": 288000, "high": 576000}
    assert t["margin"] == {"low": 32300, "expected": 201000, "high": 489000}

    # a second crop: totals are the sum of both crops' results
    db_client.post(f"{PLANS}/{plan['id']}/items", headers=h, json=ragi_body())
    ev = db_client.get(f"{PLANS}/{plan['id']}/evaluation", headers=h).json()
    assert ev["totals"]["revenue"]["expected"] == sum(i["revenue"]["expected"] for i in ev["items"])
    assert ev["totals"]["cost"]["expected"] == sum(i["cost"]["expected"] for i in ev["items"])
    ragi = ev["items"][1]
    # ragi: 4 acres x 900 kg x 32 INR = 115,200; cost (800 + 2,500 + 15 x 400) x 4 = 37,200
    assert ragi["revenue"]["expected"] == 115200 and ragi["cost"]["expected"] == 37200

    # edit the tomato price: expected revenue 2 x 12,000 x 15 = 360,000; margin 360,000 - 87,000
    tomato_id = db_client.get(f"{PLANS}/{plan['id']}", headers=h).json()["items"][0]["id"]
    r = db_client.patch(
        f"/api/v1/crop-plan-items/{tomato_id}", headers=h, json={"price_per_kg": {"low": 8, "expected": 15, "high": 18}}
    )
    assert r.status_code == 200, r.text
    ev = db_client.get(f"{PLANS}/{plan['id']}/evaluation", headers=h).json()
    assert ev["items"][0]["revenue"]["expected"] == 360000 and ev["items"][0]["margin"]["expected"] == 273000

    # reopen: the inputs persisted, and deleting a crop updates the totals
    reopened = db_client.get(f"{PLANS}/{plan['id']}", headers=h).json()
    assert [i["crop_name"] for i in reopened["items"]] == ["Tomato", "Ragi"]
    assert reopened["items"][0]["price_per_kg"] == {"low": 8, "expected": 15, "high": 18}
    assert db_client.delete(f"/api/v1/crop-plan-items/{tomato_id}", headers=h).status_code == 204
    t = db_client.get(f"{PLANS}/{plan['id']}/evaluation", headers=h).json()["totals"]
    assert t["revenue"]["expected"] == 115200 and t["cost"]["expected"] == 37200


def test_the_same_crop_and_sowing_date_cannot_be_added_twice(db_client, farmer):
    h = farmer.headers
    plan = db_client.post(
        PLANS, headers=h, json={"name": "P", "available_land_acres": 5, "items": [item_body()]}
    ).json()
    r = db_client.post(f"{PLANS}/{plan['id']}/items", headers=h, json=item_body(crop_name="tomato "))
    assert r.status_code == 409 and code(r) == "duplicate_plan_item"
    assert "tomato sown on 2026-11-01" in r.json()["error"]["message"].lower()
    # another sowing date is a separate entry
    assert (
        db_client.post(f"{PLANS}/{plan['id']}/items", headers=h, json=item_body(sowing_date="2026-12-01")).status_code
        == 201
    )
    assert len(db_client.get(f"{PLANS}/{plan['id']}", headers=h).json()["items"]) == 2


def test_duplicates_are_rejected_on_create_and_on_edit(db_client, farmer):
    h = farmer.headers
    r = db_client.post(
        PLANS, headers=h, json={"name": "Dup", "available_land_acres": 5, "items": [item_body(), item_body()]}
    )
    assert r.status_code == 409 and code(r) == "duplicate_plan_item"
    assert db_client.get(PLANS, headers=h).json()["total"] == 0  # nothing half-saved

    plan = db_client.post(
        PLANS,
        headers=h,
        json={"name": "Two", "available_land_acres": 5, "items": [item_body(), item_body(sowing_date="2026-12-01")]},
    ).json()
    second = plan["items"][1]["id"]
    r = db_client.patch(f"/api/v1/crop-plan-items/{second}", headers=h, json={"sowing_date": "2026-11-01"})
    assert r.status_code == 409 and code(r) == "duplicate_plan_item"
    assert db_client.get(f"/api/v1/crop-plan-items/{second}", headers=h).json()["sowing_date"] == "2026-12-01"
