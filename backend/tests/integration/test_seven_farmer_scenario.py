"""Buyer-demand-first matching with seven farmers in different Karnataka villages, through the real APIs and
PostgreSQL. Separate farmer accounts; the simulated predictor (`demo_scripted`) echoes each farmer's own estimate
exactly, so "150 kg" stays 150 kg (production lots offer only the cautious p10 of a real prediction).

| Farmer | Crop | kg |  A Tomato 150, B Tomato 200, C Onion 300, D Potato 250, E Chilli 100, F Tomato 100,
G Cabbage 200. A Bengaluru hotel wants 500 kg of tomato: 450 kg eligible, 50 kg short, partial.

Both entry points must end in the same state: farmers first then the buyer (test A), or the buyer first then the
farmers (test B).
"""

from __future__ import annotations

import contextlib
import threading
import uuid
from dataclasses import dataclass

import pytest

from app.composition import build_marketplace_service
from app.providers.prediction.demo import DemoScriptedPredictor
from app.repositories.pooling import PoolingRepository
from tests.conftest import Actor, bearer, days_from_today, predict

pytestmark = pytest.mark.integration
API = "/api/v1"
HARVEST_IN_DAYS = 36
BENGALURU = (12.9716, 77.5946)
# (farmer, crop key, kg, village coordinates)
SEVEN = (
    ("A", "tomato", 150, (13.1360, 78.1290)),  # Kolar
    ("B", "tomato", 200, (13.3409, 77.1010)),  # Tumakuru
    ("C", "onion", 300, (14.4644, 75.9218)),  # Davanagere
    ("D", "potato", 250, (13.0033, 76.1004)),  # Hassan
    ("E", "chilli", 100, (15.3647, 75.1240)),  # Hubballi
    ("F", "tomato", 100, (13.4355, 77.7315)),  # Chikkaballapur
    ("G", "cabbage", 200, (12.2958, 76.6394)),  # Mysuru
)


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
def market(db_client, db_container, api, admin, ref_crop, register_farmer, register_buyer):
    db_container.predictor = DemoScriptedPredictor()
    crops = {"tomato": ref_crop}
    for key, name in (("onion", "Onion"), ("potato", "Potato"), ("chilli", "Chilli"), ("cabbage", "Cabbage")):
        crops[key] = api.crop(admin, name=name, typical_duration_days=100, reference_yield_kg_per_acre=8000)
    phones = iter(f"98765{n:05d}" for n in range(100, 200))

    def grower(crop: str, kg: float, where=(12.30, 76.64), *, grade: str = "A", offer: bool = True) -> Grower:
        data = register_farmer(next(phones))
        actor = Actor(bearer(data["tokens"]["access_token"]), data["user"]["id"], "farmer")
        farm = api.farm(actor, name="Village farm", latitude=where[0], longitude=where[1], total_area_acres=2)
        plot = api.plot(actor, farm["id"], area_acres=1)
        cycle = api.cycle(
            actor,
            plot["id"],
            crops[crop]["id"],
            status="growing",
            area_acres=1,
            sowing_date=days_from_today(-60),
            expected_harvest_date=days_from_today(HARVEST_IN_DAYS),
        )
        predict(db_client, actor, cycle["id"], _estimate(kg))
        (lot,) = _get(db_client, actor, "/inventory/lots")["items"]
        if offer:  # Harvest screen: "Offer to buyers (harvest pools)"
            r = db_client.patch(
                f"{API}/inventory/lots/{lot['id']}",
                headers=actor.headers,
                json={"pool_eligible": True, "expected_grade": grade},
            )
            assert r.status_code == 200, r.text
        return Grower(actor, cycle["id"], lot["id"])

    def seven() -> dict[str, Grower]:
        return {name: grower(crop, kg, where) for name, crop, kg, where in SEVEN}

    def buyer(phone: str = "9123400101") -> Actor:
        data = register_buyer(phone)
        return Actor(bearer(data["tokens"]["access_token"]), data["user"]["id"], "buyer")

    return {"crops": crops, "grower": grower, "seven": seven, "buyer": buyer}


def _demand(client, buyer, crop_id, qty, **kw):
    day = days_from_today(HARVEST_IN_DAYS)
    body = {"crop_id": crop_id, "quantity_kg": qty, "min_grade": "A", "window_start": day, "window_end": day, **kw}
    r = client.post(f"{API}/buyer-demands", headers=buyer.headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _pool(client, buyer, demand_id, key):
    r = client.post(f"{API}/buyer-demands/{demand_id}/pool", headers={**buyer.headers, "Idempotency-Key": key}, json={})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _order(client, buyer, pool_id, key):
    r = client.post(f"{API}/orders", headers={**buyer.headers, "Idempotency-Key": key}, json={"pool_id": pool_id})
    assert r.status_code == 201, r.text
    return r.json()


def _accept_all(client, grower):
    for p in _get(client, grower.actor, "/participations", status="pending")["items"]:
        assert client.post(f"{API}/participations/{p['id']}/accept", headers=grower.actor.headers).status_code == 200


def _lot(client, grower):
    return _get(client, grower.actor, f"/inventory/lots/{grower.lot_id}")


def _allocations(pool, farms):
    by_lot = {a["lot_id"]: a["quantity_kg"] for a in pool["allocations"] if a["quantity_kg"] > 0}
    return {name: by_lot[g.lot_id] for name, g in farms.items() if g.lot_id in by_lot}


# ======================================================== the scenario itself
def test_a_farmers_first_then_buyer_450_of_500_kg_with_a_50_kg_shortage(db_client, market):
    farms = market["seven"]()
    buyer = market["buyer"]()
    tomato = market["crops"]["tomato"]["id"]

    demand = _demand(db_client, buyer, tomato, 500)
    # the creation response already carries the real matching result (nothing reserved yet)
    assert (demand["stage"], demand["matched_kg"], demand["shortage_kg"]) == ("partially_matched", 450, 50)
    assert demand["pool_id"] is None and demand["order_id"] is None

    m = _get(db_client, buyer, f"/buyer-demands/{demand['id']}/matches")
    assert (m["need_kg"], m["eligible_supply_kg"], m["shortage_kg"], m["shortfall_kg"]) == (500, 450, 50, 50)
    assert (m["fulfilment"], m["eligible_count"]) == ("partial", 3)
    listed = {x["lot_id"] for x in m["matches"]}
    assert listed == {farms[n].lot_id for n in "ABF"}  # onion, potato, chilli and cabbage never appear
    assert "create_pool" in m["next_steps"] and "wait_for_supply" in m["next_steps"]
    assert any("Shortage 50 kg" in line for line in m["explanation"])
    for name in "CDEG":  # other crops' farmers are not told about a tomato demand
        assert _get(db_client, farms[name].actor, "/market/opportunities") == []
    assert len(_get(db_client, farms["A"].actor, "/market/opportunities")) == 1

    pool = _pool(db_client, buyer, demand["id"], "seven-a")
    assert (pool["allocated_kg"], pool["unfilled_kg"], pool["status"]) == (450, 50, "partial")
    assert _allocations(pool, farms) == {"A": 150, "B": 200, "F": 100}
    order = _order(db_client, buyer, pool["id"], "seven-a")
    assert (order["status"], order["confirmed_kg"], order["awaiting_kg"], order["uncovered_kg"]) == (
        "placed",
        0,
        450,
        50,
    )
    assert _get(db_client, buyer, f"/buyer-demands/{demand['id']}")["stage"] == "awaiting_farmer_confirmation"
    for name in "ABF":
        _accept_all(db_client, farms[name])
    o = _get(db_client, buyer, f"/orders/{order['id']}")
    # every farmer asked has accepted, but 50 kg has no supplier: partial, never "confirmed"
    assert (o["status"], o["confirmed_kg"], o["uncovered_kg"]) == ("placed", 450, 50)
    d = _get(db_client, buyer, f"/buyer-demands/{demand['id']}")
    assert (d["allocated_kg"], d["remaining_kg"]) == (450, 50)
    for name in "CDEG":
        assert _lot(db_client, farms[name])["committed_kg"] == 0
    a_lot = _lot(db_client, farms["A"])
    assert (a_lot["committed_kg"], a_lot["available_kg"], a_lot["confirmed_kg"]) == (150, 0, 150)

    # an onion farmer with plenty of supply never resolves a tomato shortage
    market["grower"]("onion", 1000)
    assert _get(db_client, buyer, f"/pools/{pool['id']}")["unfilled_kg"] == 50

    # an eighth farmer offers 60 kg of tomato: exactly the missing 50 kg is proposed, they keep 10 kg
    h = market["grower"]("tomato", 60)
    p = _get(db_client, buyer, f"/pools/{pool['id']}")
    assert (p["allocated_kg"], p["unfilled_kg"], p["status"]) == (500, 0, "filled")
    h_lot = _lot(db_client, h)
    assert (h_lot["committed_kg"], h_lot["available_kg"], h_lot["awaiting_confirmation_kg"]) == (50, 10, 50)
    o = _get(db_client, buyer, f"/orders/{order['id']}")
    assert (o["status"], o["confirmed_kg"], o["awaiting_kg"], o["uncovered_kg"]) == ("placed", 450, 50, 0)
    _accept_all(db_client, h)
    o = _get(db_client, buyer, f"/orders/{order['id']}")
    assert (o["status"], o["confirmed_kg"]) == ("confirmed", 500)
    assert _get(db_client, buyer, f"/buyer-demands/{demand['id']}")["stage"] == "confirmed"


def test_b_buyer_first_then_farmers_reaches_the_same_state(db_client, market):
    buyer = market["buyer"]()
    tomato = market["crops"]["tomato"]["id"]

    demand = _demand(db_client, buyer, tomato, 500)
    assert (demand["stage"], demand["matched_kg"], demand["shortage_kg"]) == ("no_matching_supply", 0, 500)
    m = _get(db_client, buyer, f"/buyer-demands/{demand['id']}/matches")
    assert (m["fulfilment"], m["eligible_supply_kg"], m["shortage_kg"]) == ("none", 0, 500)
    assert "create_pool" not in m["next_steps"] and "wait_for_supply" in m["next_steps"]

    # the buyer keeps the demand actionable: a pool with nothing in it yet, waiting for supply
    pool = _pool(db_client, buyer, demand["id"], "seven-b")
    assert (pool["allocated_kg"], pool["status"]) == (0, "unfilled")
    assert _get(db_client, buyer, f"/buyer-demands/{demand['id']}")["stage"] == "no_matching_supply"

    farms = market["seven"]()  # each tomato lot tops the pool up the moment its farmer offers it
    p = _get(db_client, buyer, f"/pools/{pool['id']}")
    assert (p["allocated_kg"], p["unfilled_kg"], p["status"]) == (450, 50, "partial")
    assert _allocations(p, farms) == {"A": 150, "B": 200, "F": 100}  # the same split as farmers-first
    events = _get(db_client, buyer, f"/pools/{pool['id']}/events")
    assert sorted(e["trigger_ref"] for e in events if e["trigger"] == "supply_added") == sorted(
        farms[n].lot_id for n in "ABF"
    )
    assert all(e["outcome"] == "top_up" for e in events)
    for name in "CDEG":
        assert _lot(db_client, farms[name])["committed_kg"] == 0

    d = _get(db_client, buyer, f"/buyer-demands/{demand['id']}")
    assert (d["stage"], d["allocated_kg"], d["remaining_kg"]) == ("partially_matched", 450, 50)
    order = _order(db_client, buyer, pool["id"], "seven-b")
    for name in "ABF":
        _accept_all(db_client, farms[name])
    o = _get(db_client, buyer, f"/orders/{order['id']}")
    assert (o["status"], o["confirmed_kg"], o["uncovered_kg"]) == ("placed", 450, 50)


def test_b_open_demand_is_rematched_live_as_farmers_register(db_client, market):
    buyer = market["buyer"]()
    tomato = market["crops"]["tomato"]["id"]
    demand = _demand(db_client, buyer, tomato, 500)
    seen = []
    for name, crop, kg, where in SEVEN:
        market["grower"](crop, kg, where)
        d = _get(db_client, buyer, f"/buyer-demands/{demand['id']}")
        seen.append((name, d["stage"], d["matched_kg"], d["shortage_kg"]))
    assert seen == [
        ("A", "partially_matched", 150, 350),
        ("B", "partially_matched", 350, 150),
        ("C", "partially_matched", 350, 150),  # onion changes nothing
        ("D", "partially_matched", 350, 150),
        ("E", "partially_matched", 350, 150),
        ("F", "partially_matched", 450, 50),
        ("G", "partially_matched", 450, 50),
    ]
    market["grower"]("tomato", 50)
    d = _get(db_client, buyer, f"/buyer-demands/{demand['id']}")
    assert (d["stage"], d["matched_kg"], d["shortage_kg"]) == ("matching_supply_available", 500, 0)
    assert d["pool_id"] is None and d["allocated_kg"] is None  # matching alone reserves nothing


# ======================================================= eligibility filters
def test_full_supply_has_zero_shortage_and_unsuitable_supply_is_excluded_with_reasons(db_client, market):
    g = market["grower"]
    g("tomato", 300)
    late = g("tomato", 400, offer=True)
    low = g("tomato", 400, grade="C")
    far = g("tomato", 400, where=(15.85, 74.50))  # Belagavi, ~450 km from Bengaluru
    hidden = g("tomato", 400, offer=False)
    buyer = market["buyer"]()
    tomato = market["crops"]["tomato"]["id"]
    # the "late" lot's harvest window is moved away from the delivery day
    r = db_client.patch(
        f"{API}/crop-cycles/{late.cycle_id}",
        headers=late.actor.headers,
        json={"expected_harvest_date": days_from_today(90)},
    )
    assert r.status_code == 200, r.text
    predict(db_client, late.actor, late.cycle_id, _estimate(400))

    demand = _demand(
        db_client,
        buyer,
        tomato,
        300,
        latitude=BENGALURU[0],
        longitude=BENGALURU[1],
        max_distance_km=200,
    )
    m = _get(db_client, buyer, f"/buyer-demands/{demand['id']}/matches")
    assert (m["fulfilment"], m["eligible_supply_kg"], m["shortage_kg"], m["eligible_count"]) == ("full", 300, 0, 1)
    reasons = {x["lot_id"]: set(x["reasons"]) for x in m["matches"] if not x["eligible"]}
    assert "window_no_overlap" in reasons[late.lot_id]
    assert "grade_below_minimum" in reasons[low.lot_id]
    assert "too_far" in reasons[far.lot_id]
    assert "not_opted_in" in reasons[hidden.lot_id]
    assert demand["stage"] == "matching_supply_available"
    assert {"revise_dates", "accept_lower_grade", "widen_distance"}.isdisjoint(m["next_steps"])  # met in full

    big = _demand(db_client, buyer, tomato, 1000, latitude=BENGALURU[0], longitude=BENGALURU[1], max_distance_km=200)
    m = _get(db_client, buyer, f"/buyer-demands/{big['id']}/matches")
    assert (m["fulfilment"], m["shortage_kg"]) == ("partial", 700)
    assert {"revise_dates", "accept_lower_grade", "widen_distance", "choose_other_crop"} <= set(m["next_steps"])
    assert set(m["excluded_reasons"]) >= {"window_no_overlap", "grade_below_minimum", "too_far", "not_opted_in"}


def test_supply_that_does_not_fit_a_short_pool_does_not_top_it_up(db_client, market):
    g = market["grower"]
    a = g("tomato", 150)
    buyer = market["buyer"]()
    demand = _demand(db_client, buyer, market["crops"]["tomato"]["id"], 500)
    pool = _pool(db_client, buyer, demand["id"], "fit")
    assert pool["allocated_kg"] == 150
    g("tomato", 400, grade="C")  # below the buyer's grade A
    g("onion", 400)
    p = _get(db_client, buyer, f"/pools/{pool['id']}")
    assert (p["allocated_kg"], p["unfilled_kg"]) == (150, 350)
    assert [e["trigger"] for e in _get(db_client, buyer, f"/pools/{pool['id']}/events")] == []  # no noise events
    assert _lot(db_client, a)["committed_kg"] == 150


# ================================================== prediction falls (section 8)
def test_prediction_drop_150_to_80_is_replaced_by_a_farmer_with_70_kg(db_client, market):
    g = market["grower"]
    a, b, c = g("tomato", 150), g("tomato", 200), g("tomato", 150)
    buyer = market["buyer"]()
    demand = _demand(db_client, buyer, market["crops"]["tomato"]["id"], 500)
    pool = _pool(db_client, buyer, demand["id"], "drop")
    order = _order(db_client, buyer, pool["id"], "drop")
    for x in (a, b, c):
        _accept_all(db_client, x)
    assert _get(db_client, buyer, f"/orders/{order['id']}")["status"] == "confirmed"

    # no spare supply yet: the 70 kg reduction is exact and stays visible
    predict(db_client, c.actor, c.cycle_id, _estimate(80))
    history = _get(db_client, c.actor, f"/crop-cycles/{c.cycle_id}/predictions")["items"]
    assert sorted(h["version"] for h in history) == [1, 2]  # history kept
    p = _get(db_client, buyer, f"/pools/{pool['id']}")
    assert (p["allocated_kg"], p["shortage_kg"], p["status"]) == (430, 70, "at_risk")
    (ev,) = _get(db_client, buyer, f"/pools/{pool['id']}/events")
    assert (ev["shortage_kg"], ev["replaced_kg"], ev["unresolved_kg"], ev["outcome"]) == (70, 0, 70, "none")
    assert _get(db_client, buyer, f"/buyer-demands/{demand['id']}")["stage"] == "reallocation_required"
    o = _get(db_client, buyer, f"/orders/{order['id']}")
    by_lot = {i["lot_id"]: (i["quantity_kg"], i["status"]) for i in o["items"]}
    assert by_lot[a.lot_id] == (150, "accepted") and by_lot[b.lot_id] == (200, "accepted")  # untouched
    assert by_lot[c.lot_id] == (80, "accepted")

    # a farmer with exactly 70 kg offers it: proposed as the replacement, awaiting their acceptance
    d = g("tomato", 70)
    p = _get(db_client, buyer, f"/pools/{pool['id']}")
    assert (p["allocated_kg"], p["shortage_kg"], p["unfilled_kg"]) == (500, 0, 0)
    o = _get(db_client, buyer, f"/orders/{order['id']}")
    assert (o["status"], o["confirmed_kg"], o["awaiting_kg"]) == ("placed", 430, 70)
    _accept_all(db_client, d)
    assert _get(db_client, buyer, f"/orders/{order['id']}")["status"] == "confirmed"


# ============================================ cancellation, safety, isolation
def test_cancel_releases_reserved_supply_exactly_once(db_client, market):
    a = market["grower"]("tomato", 150)
    buyer = market["buyer"]()
    demand = _demand(db_client, buyer, market["crops"]["tomato"]["id"], 100)
    order = _order(db_client, buyer, _pool(db_client, buyer, demand["id"], "c")["id"], "c")
    assert (_lot(db_client, a)["committed_kg"], _lot(db_client, a)["available_kg"]) == (100, 50)
    assert db_client.post(f"{API}/orders/{order['id']}/cancel", headers=buyer.headers).status_code == 200
    assert db_client.post(f"{API}/orders/{order['id']}/cancel", headers=buyer.headers).status_code == 409
    lot = _lot(db_client, a)
    assert (lot["committed_kg"], lot["available_kg"], lot["awaiting_confirmation_kg"]) == (0, 150, 0)
    assert _get(db_client, buyer, f"/buyer-demands/{demand['id']}")["stage"] == "cancelled"


def test_repeated_opt_in_and_retried_requests_never_double_allocate(db_client, market):
    buyer = market["buyer"]()
    demand = _demand(db_client, buyer, market["crops"]["tomato"]["id"], 500)
    pool = _pool(db_client, buyer, demand["id"], "rep")
    assert _pool(db_client, buyer, demand["id"], "rep")["id"] == pool["id"]  # retried pool creation
    a = market["grower"]("tomato", 150)
    for _ in range(2):  # the app retries the same toggle
        r = db_client.patch(
            f"{API}/inventory/lots/{a.lot_id}",
            headers=a.actor.headers,
            json={"pool_eligible": True, "expected_grade": "A"},
        )
        assert r.status_code == 200 and r.json()["committed_kg"] == 150
    p = _get(db_client, buyer, f"/pools/{pool['id']}")
    assert p["allocated_kg"] == 150 and len(_get(db_client, buyer, f"/pools/{pool['id']}/events")) == 1


def test_concurrent_buyers_cannot_oversell_the_same_tomato_supply(db_container, db_client, market, monkeypatch):
    for _name, crop, kg, where in SEVEN:
        market["grower"](crop, kg, where)
    b1, b2 = market["buyer"]("9123400201"), market["buyer"]("9123400202")
    tomato = market["crops"]["tomato"]["id"]
    d1, d2 = _demand(db_client, b1, tomato, 300), _demand(db_client, b2, tomato, 300)
    barrier = threading.Barrier(2, timeout=1.5)
    original = PoolingRepository.lots_for_crop

    def rendezvous(self, crop_id, *, lock):  # type: ignore[no-untyped-def]
        if lock:
            with contextlib.suppress(threading.BrokenBarrierError):
                barrier.wait()
        return original(self, crop_id, lock=lock)

    monkeypatch.setattr(PoolingRepository, "lots_for_crop", rendezvous)
    from app.schemas.pooling import PoolCreate

    results = []

    def attempt(buyer, demand_id):
        with db_container.session_factory() as s:
            results.append(
                build_marketplace_service(s, db_container)[1].create_pool(
                    uuid.UUID(buyer.user_id), uuid.UUID(demand_id), PoolCreate(), None
                )
            )

    threads = [threading.Thread(target=attempt, args=a) for a in ((b1, d1["id"]), (b2, d2["id"]))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    monkeypatch.undo()
    assert len(results) == 2
    assert sorted(float(p.allocated_kg) for p in results) == [150.0, 300.0]  # 450 kg in total, never more


def test_buyers_and_farmers_cannot_touch_each_others_records(db_client, market):
    a = market["grower"]("tomato", 150)
    other_farmer = market["grower"]("tomato", 10)
    b1, b2 = market["buyer"]("9123400301"), market["buyer"]("9123400302")
    demand = _demand(db_client, b1, market["crops"]["tomato"]["id"], 100)
    assert db_client.get(f"{API}/buyer-demands/{demand['id']}", headers=b2.headers).status_code == 404
    assert db_client.get(f"{API}/buyer-demands/{demand['id']}/matches", headers=b2.headers).status_code == 404
    assert db_client.post(f"{API}/buyer-demands/{demand['id']}/cancel", headers=b2.headers).status_code == 404
    assert db_client.post(f"{API}/buyer-demands", headers=a.actor.headers, json={}).status_code == 403
    r = db_client.patch(
        f"{API}/inventory/lots/{a.lot_id}", headers=other_farmer.actor.headers, json={"pool_eligible": False}
    )
    assert r.status_code == 404
    order = _order(db_client, b1, _pool(db_client, b1, demand["id"], "auth")["id"], "auth")
    (part,) = _get(db_client, a.actor, "/participations", status="pending")["items"]
    assert (
        db_client.post(f"{API}/participations/{part['id']}/accept", headers=other_farmer.actor.headers).status_code
        == 404
    )
    assert db_client.post(f"{API}/orders/{order['id']}/cancel", headers=b2.headers).status_code == 404
    # buyers see pseudonymous farm references only, never the farmer's identity or phone
    m = _get(db_client, b1, f"/buyer-demands/{demand['id']}/matches")
    assert all(set(x) >= {"farm_ref"} and "phone" not in x and "owner_id" not in x for x in m["matches"])
