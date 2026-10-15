"""The farmer-buyer scenario of the manual phone test guide (docs/MANUAL_TEST_FARMER_BUYER.md), with SEPARATE farmer
accounts and the same simulated predictor the isolated manual-test server uses (`demo_scripted`: the farmer's own
estimate x area, exactly). If these numbers change, the guide's expected results must change with them.

Tomato farmer 1: 100 kg, tomato farmer 2: 150 kg, onion farmer: 200 kg; buyer: tomato, grade A, one delivery day.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.providers.prediction.demo import DemoScriptedPredictor
from tests.conftest import Actor, bearer, days_from_today, predict

pytestmark = pytest.mark.integration
API = "/api/v1"
HARVEST_IN_DAYS = 36  # "20 November" seen from the test date


@dataclass
class Grower:
    actor: Actor
    cycle_id: str
    lot_id: str


def _get(client, actor, path, **params):
    r = client.get(f"{API}{path}", headers=actor.headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _estimate(kg: float) -> dict:
    return {"farmer_estimate_per_acre": {"low": kg, "expected": kg, "high": kg}}


@pytest.fixture
def world(db_client, db_container, api, admin, ref_crop, register_farmer, register_buyer):
    db_container.predictor = DemoScriptedPredictor()
    onion = api.crop(admin, name="Onion", typical_duration_days=120, reference_yield_kg_per_acre=8000)

    def grower(phone: str, crop: dict, kg: float, *, offer: bool = True) -> Grower:
        data = register_farmer(phone)
        actor = Actor(bearer(data["tokens"]["access_token"]), data["user"]["id"], "farmer")
        farm = api.farm(actor, name=f"Test farm {phone[-2:]}", latitude=12.30, longitude=76.64, total_area_acres=2)
        plot = api.plot(actor, farm["id"], area_acres=1)
        cycle = api.cycle(
            actor,
            plot["id"],
            crop["id"],
            status="growing",
            area_acres=1,
            sowing_date=days_from_today(-60),
            expected_harvest_date=days_from_today(HARVEST_IN_DAYS),
        )
        predict(db_client, actor, cycle["id"], _estimate(kg))
        lot = _get(db_client, actor, "/inventory/lots")["items"][0]
        if offer:  # Harvest screen: "Offer to buyers" on, expected grade A
            r = db_client.patch(
                f"{API}/inventory/lots/{lot['id']}",
                headers=actor.headers,
                json={"pool_eligible": True, "expected_grade": "A"},
            )
            assert r.status_code == 200, r.text
        return Grower(actor, cycle["id"], lot["id"])

    data = register_buyer("9123400001")
    buyer = Actor(bearer(data["tokens"]["access_token"]), data["user"]["id"], "buyer")
    return {
        "t1": grower("9876500001", ref_crop, 100),
        "t2": grower("9876500002", ref_crop, 150),
        "onion": grower("9876500003", onion, 200),
        "buyer": buyer,
        "tomato": ref_crop,
        "grower": grower,
    }


def _demand(client, buyer, crop_id, qty):
    day = days_from_today(HARVEST_IN_DAYS)
    r = client.post(
        f"{API}/buyer-demands",
        headers=buyer.headers,
        json={"crop_id": crop_id, "quantity_kg": qty, "min_grade": "A", "window_start": day, "window_end": day},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _pool_and_order(client, buyer, demand_id, tag):
    pool = client.post(
        f"{API}/buyer-demands/{demand_id}/pool", headers={**buyer.headers, "Idempotency-Key": f"p-{tag}"}, json={}
    )
    assert pool.status_code in (200, 201), pool.text
    order = client.post(
        f"{API}/orders", headers={**buyer.headers, "Idempotency-Key": f"o-{tag}"}, json={"pool_id": pool.json()["id"]}
    )
    assert order.status_code == 201, order.text
    return pool.json(), order.json()


def _pending(client, grower):
    return _get(client, grower.actor, "/participations", status="pending")["items"]


def _accept_all(client, grower):
    for p in _pending(client, grower):
        assert client.post(f"{API}/participations/{p['id']}/accept", headers=grower.actor.headers).status_code == 200


def _lot(client, grower):
    return _get(client, grower.actor, f"/inventory/lots/{grower.lot_id}")


def test_200_kg_demand_uses_only_the_two_tomato_farms_and_reserves_only_200_kg(db_client, world):
    t1, t2, onion, buyer = world["t1"], world["t2"], world["onion"], world["buyer"]
    demand = _demand(db_client, buyer, world["tomato"]["id"], 200)

    m = _get(db_client, buyer, f"/buyer-demands/{demand['id']}/matches")
    assert (m["eligible_supply_kg"], m["eligible_count"], m["shortfall_kg"]) == (250, 2, 0)
    assert onion.lot_id not in {x["lot_id"] for x in m["matches"]}  # onion is never a tomato candidate
    assert _get(db_client, onion.actor, "/market/opportunities") == []  # nor told about the tomato demand

    pool, order = _pool_and_order(db_client, buyer, demand["id"], "200")
    assert (pool["allocated_kg"], pool["unfilled_kg"], pool["status"]) == (200, 0, "filled")
    assert sum(a["quantity_kg"] for a in pool["allocations"]) == 200  # not the whole 250
    # greedy: the larger lot first (it covers more of the need), the rest from the smaller one
    assert (_lot(db_client, t2)["committed_kg"], _lot(db_client, t1)["committed_kg"]) == (150, 50)
    assert _lot(db_client, t1)["available_kg"] == 50
    assert _lot(db_client, onion)["committed_kg"] == 0

    # placed, not confirmed: farmers must accept first
    assert order["status"] == "placed"
    assert (order["confirmed_kg"], order["awaiting_kg"], order["uncovered_kg"]) == (0, 200, 0)
    assert [p["quantity_kg"] for p in _pending(db_client, t1)] == [50]
    assert [p["quantity_kg"] for p in _pending(db_client, t2)] == [150]
    assert _pending(db_client, onion) == []

    _accept_all(db_client, t1)
    half = _get(db_client, buyer, f"/orders/{order['id']}")
    assert (half["status"], half["confirmed_kg"], half["awaiting_kg"]) == ("placed", 50, 150)
    _accept_all(db_client, t2)
    done = _get(db_client, buyer, f"/orders/{order['id']}")
    assert (done["status"], done["confirmed_kg"], done["awaiting_kg"], done["uncovered_kg"]) == ("confirmed", 200, 0, 0)
    seen_by_t2 = _get(db_client, t2.actor, "/participations")["items"]
    assert [(p["status"], p["quantity_kg"]) for p in seen_by_t2] == [("accepted", 150)]

    # cancelling releases everything (the guide does this before the 300 kg part)
    assert db_client.post(f"{API}/orders/{order['id']}/cancel", headers=buyer.headers, json={}).status_code == 200
    assert (_lot(db_client, t1)["available_kg"], _lot(db_client, t2)["available_kg"]) == (100, 150)
    assert [p["status"] for p in _get(db_client, t1.actor, "/participations")["items"]] == ["withdrawn"]


def test_300_kg_demand_shows_50_kg_short_until_new_supply_is_found_and_accepted_then_a_drop(db_client, world):
    t1, t2, onion, buyer = world["t1"], world["t2"], world["onion"], world["buyer"]
    demand = _demand(db_client, buyer, world["tomato"]["id"], 300)

    m = _get(db_client, buyer, f"/buyer-demands/{demand['id']}/matches")
    assert (m["eligible_supply_kg"], m["need_kg"], m["shortfall_kg"]) == (250, 300, 50)

    pool, order = _pool_and_order(db_client, buyer, demand["id"], "300")
    assert (pool["allocated_kg"], pool["unfilled_kg"], pool["status"]) == (250, 50, "partial")
    _accept_all(db_client, t1)
    _accept_all(db_client, t2)
    o = _get(db_client, buyer, f"/orders/{order['id']}")
    # every farmer asked has accepted, but 50 kg has no supplier: NOT confirmed
    assert (o["status"], o["confirmed_kg"], o["awaiting_kg"], o["uncovered_kg"]) == ("placed", 250, 0, 50)

    # a 4th tomato farmer offers 50 kg: the short pool is topped up as soon as the lot is offered
    t4 = world["grower"]("9876500004", world["tomato"], 50)
    (top_up,) = [e for e in _get(db_client, buyer, f"/pools/{pool['id']}/events") if e["trigger"] == "supply_added"]
    assert (top_up["outcome"], top_up["topped_up_kg"], top_up["trigger_ref"]) == ("top_up", 50, t4.lot_id)
    assert "New supply found for your demand" in [n["title"] for n in _get(db_client, buyer, "/notifications")["items"]]
    # the buyer's "Check for new supply" afterwards finds nothing more (and does not double-allocate)
    ev = db_client.post(
        f"{API}/pools/{pool['id']}/rebalance", headers={**buyer.headers, "Idempotency-Key": "check-1"}
    ).json()
    assert (ev["outcome"], ev["topped_up_kg"]) == ("no_change", 0)
    p = _get(db_client, buyer, f"/pools/{pool['id']}")
    assert (p["allocated_kg"], p["unfilled_kg"], p["status"]) == (300, 0, "filled")
    o = _get(db_client, buyer, f"/orders/{order['id']}")
    assert (o["status"], o["confirmed_kg"], o["awaiting_kg"], o["uncovered_kg"]) == ("placed", 250, 50, 0)
    assert [x["quantity_kg"] for x in _pending(db_client, t4)] == [50]
    _accept_all(db_client, t4)
    o = _get(db_client, buyer, f"/orders/{order['id']}")
    assert (o["status"], o["confirmed_kg"]) == ("confirmed", 300)

    # farmer 2 lowers the prediction 150 -> 120: history kept, exact 30 kg shortage, no onion "replacement"
    predict(db_client, t2.actor, t2.cycle_id, _estimate(120))
    history = _get(db_client, t2.actor, f"/crop-cycles/{t2.cycle_id}/predictions")["items"]
    assert sorted(h["version"] for h in history) == [1, 2]
    assert _lot(db_client, t2)["committable_kg"] == 120
    p = _get(db_client, buyer, f"/pools/{pool['id']}")
    assert (p["allocated_kg"], p["unfilled_kg"], p["shortage_kg"], p["status"]) == (270, 30, 30, "at_risk")
    assert _lot(db_client, onion)["committed_kg"] == 0
    events = _get(db_client, buyer, f"/pools/{pool['id']}/events")
    assert (events[-1]["shortage_kg"], events[-1]["unresolved_kg"], events[-1]["outcome"]) == (30, 30, "none")
    o = _get(db_client, buyer, f"/orders/{order['id']}")
    assert (o["status"], o["confirmed_kg"], o["uncovered_kg"]) == ("placed", 270, 30)
    by_farm = {i["lot_id"]: (i["quantity_kg"], i["status"]) for i in o["items"]}
    assert by_farm[t1.lot_id] == (100, "accepted")  # other farmers' confirmed commitments are untouched
    assert by_farm[t2.lot_id] == (120, "accepted")
    titles = [n["title"] for n in _get(db_client, t2.actor, "/notifications")["items"]]
    assert "Requested quantity reduced" in titles
    buyer_titles = [n["title"] for n in _get(db_client, buyer, "/notifications")["items"]]
    assert "Supply shortage not fully covered" in buyer_titles

    # farmer 4 raises their prediction 50 -> 80: the pool is topped up automatically, but farmer 4 must re-accept
    predict(db_client, t4.actor, t4.cycle_id, _estimate(80))
    p = _get(db_client, buyer, f"/pools/{pool['id']}")
    assert (p["allocated_kg"], p["unfilled_kg"]) == (300, 0)
    o = _get(db_client, buyer, f"/orders/{order['id']}")
    assert (o["status"], o["confirmed_kg"], o["awaiting_kg"]) == ("placed", 220, 80)
