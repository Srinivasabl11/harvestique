"""Marketplace end to end on PostgreSQL: orders, participation, reallocation-driven order updates, cancellation,
collection, quality, fulfilment, traceability, market search and concurrency."""

from __future__ import annotations

import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.composition import build_marketplace_service
from tests.conftest import days_from_today, make_demand, make_pool

pytestmark = pytest.mark.integration
API = "/api/v1"


# ----------------------------------------------------------------- helpers
def place(client, buyer, pool_id, key=None, **body):
    headers = {**buyer.headers, **({"Idempotency-Key": key} if key else {})}
    return client.post(f"{API}/orders", headers=headers, json={"pool_id": pool_id, **body})


def order_get(client, buyer, order_id):
    return client.get(f"{API}/orders/{order_id}", headers=buyer.headers).json()


def pending(client, farmer):
    return client.get(
        f"{API}/participations", headers=farmer.headers, params={"status": "pending", "limit": 100}
    ).json()["items"]


def accept_all(client, farmer):
    for p in pending(client, farmer):
        r = client.post(f"{API}/participations/{p['id']}/accept", headers=farmer.headers)
        assert r.status_code == 200, r.text


def by_farm(order, world):
    names = {v["lot_id"]: k for k, v in world.farms.items()}
    return {names[i["lot_id"]]: (i["quantity_kg"], i["status"]) for i in order["items"]}


def part_for(client, farmer, world, name):
    lot = world.farms[name]["lot_id"]
    items = client.get(f"{API}/participations", headers=farmer.headers, params={"limit": 100}).json()["items"]
    return [p for p in items if p["lot_id"] == lot]


def harvest(client, farmer, world, name, kg):
    cid = world.farms[name]["cycle_id"]
    assert (
        client.patch(
            f"{API}/crop-cycles/{cid}",
            headers=farmer.headers,
            json={"status": "harvested", "actual_harvest_date": days_from_today(0)},
        ).status_code
        == 200
    )
    r = client.post(f"{API}/crop-cycles/{cid}/harvest-actual", headers=farmer.headers, json={"quantity_kg": kg})
    assert r.status_code == 201, r.text


def notes(client, actor, category=None):
    items = client.get(f"{API}/notifications", headers=actor.headers, params={"limit": 100}).json()["items"]
    return [n for n in items if category is None or n["category"] == category]


@pytest.fixture
def hub(db_client, admin):
    r = db_client.post(f"{API}/admin/hubs", headers=admin.headers, json={"name": "Test Hub", "district": "Mysuru"})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def ordered(db_client, buyer, farmer, pool_world):
    """A 2,000 kg pool over farms A-E with an order whose items are all accepted."""
    pool = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 2000, min_grade="B")["id"])
    r = place(db_client, buyer, pool["id"], key="o1")
    assert r.status_code == 201, r.text
    accept_all(db_client, farmer)
    return {"pool": pool, "order": order_get(db_client, buyer, r.json()["id"])}


# ===================================================================== orders
def test_placing_an_order_asks_every_farm_and_holds_the_existing_reservations(db_client, buyer, farmer, pool_world):
    pool = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 2000)["id"])
    order = place(db_client, buyer, pool["id"]).json()
    assert order["status"] == "placed" and order["ordered_kg"] == 2000 and order["committed_kg"] == 2000
    assert {k: v for k, v in by_farm(order, pool_world).items()} == {
        n: (q, "awaiting_farmer") for n, q in (("A", 500), ("B", 350), ("C", 450), ("D", 300), ("E", 400))
    }
    assert len(pending(db_client, farmer)) == 5
    assert len(notes(db_client, farmer, "participation_request")) == 5
    assert all(pool_world.lot(n)["available_kg"] == 0 for n in "ABCDE")  # no new reservations, no double booking
    assert "Nothing is guaranteed" in order["disclaimer"]


def test_order_idempotency_and_one_order_per_pool(db_client, buyer, pool_world):
    pool = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 2000)["id"])
    first = place(db_client, buyer, pool["id"], key="k").json()
    assert place(db_client, buyer, pool["id"], key="k").json()["id"] == first["id"]
    again = place(db_client, buyer, pool["id"], key="other")
    assert again.status_code == 409 and again.json()["error"]["code"] == "order_exists"


def test_cannot_order_someone_elses_or_an_empty_pool(db_client, buyer, register_buyer, api, admin, pool_world):
    from tests.conftest import Actor, bearer

    other = register_buyer("9123456711", profile={"business_name": "Other Co"})
    other_buyer = Actor(bearer(other["tokens"]["access_token"]), other["user"]["id"], "buyer")
    pool = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 100)["id"])
    assert place(db_client, other_buyer, pool["id"]).status_code == 404
    onion = api.crop(admin, name="Onion")
    empty = make_pool(db_client, buyer, make_demand(db_client, buyer, onion["id"], 100)["id"])
    r = place(db_client, buyer, empty["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "pool_empty"


def test_accepting_every_item_confirms_the_order(db_client, buyer, farmer, ordered):
    assert ordered["order"]["status"] == "confirmed"
    assert len(notes(db_client, buyer, "participation_response")) == 5
    p = db_client.get(f"{API}/participations", headers=farmer.headers).json()["items"][0]
    r = db_client.post(f"{API}/participations/{p['id']}/accept", headers=farmer.headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"
    assert p["buyer_business"] and "price" not in str(p).lower()


# ============================================= decline and reallocation sync
def test_decline_releases_supply_and_reallocates_atomically(db_client, buyer, farmer, pool_world, ordered):
    pool_world.add_farm("F", 450)
    (pc,) = part_for(db_client, farmer, pool_world, "C")
    r = db_client.post(
        f"{API}/participations/{pc['id']}/decline", headers=farmer.headers, json={"reason": "family emergency"}
    )
    assert r.status_code == 200 and r.json()["status"] == "declined"
    (event,) = db_client.get(f"{API}/pools/{ordered['pool']['id']}/events", headers=buyer.headers).json()
    assert (event["trigger"], event["shortage_kg"], event["replaced_kg"], event["outcome"]) == (
        "farmer_declined",
        450,
        450,
        "full",
    )
    assert "farmer declined" in event["reason"]
    order = order_get(db_client, buyer, ordered["order"]["id"])
    farms = by_farm(order, pool_world)
    assert farms["C"] == (450, "declined") and farms["F"] == (450, "awaiting_farmer")
    assert order["status"] == "placed" and order["committed_kg"] == 2000
    assert pool_world.lot("C")["available_kg"] == 450  # C's supply is free again
    # C is excluded from this pool from now on: a rebalance never offers it back
    rb = db_client.post(
        f"{API}/pools/{ordered['pool']['id']}/rebalance", headers={**buyer.headers, "Idempotency-Key": "x"}
    ).json()
    assert rb["outcome"] == "no_change" and pool_world.lot("C")["committed_kg"] == 0
    again = db_client.post(f"{API}/participations/{pc['id']}/decline", headers=farmer.headers, json={"reason": "again"})
    assert again.status_code == 409


def test_decline_without_spare_supply_leaves_the_buyer_warned(db_client, buyer, farmer, pool_world, ordered):
    (pb,) = part_for(db_client, farmer, pool_world, "B")
    db_client.post(f"{API}/participations/{pb['id']}/decline", headers=farmer.headers, json={"reason": "sold locally"})
    order = order_get(db_client, buyer, ordered["order"]["id"])
    assert order["committed_kg"] == 1650 and order["pool_status"] == "at_risk" and order["pool_shortage_kg"] == 350
    (warning,) = notes(db_client, buyer, "shortage")
    assert warning["severity"] == "warning" and "unresolved 350" in warning["body"]


def test_failed_reallocation_rolls_back_the_decline(db_container, db_client, farmer, pool_world, ordered, monkeypatch):
    from app.services.inventory import InventoryService

    pool_world.add_farm("F", 450)
    (pc,) = part_for(db_client, farmer, pool_world, "C")
    monkeypatch.setattr(
        InventoryService, "reserve_locked", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash"))
    )
    with pytest.raises(RuntimeError):
        db_client.post(f"{API}/participations/{pc['id']}/decline", headers=farmer.headers, json={"reason": "x"})
    monkeypatch.undo()
    (still,) = part_for(db_client, farmer, pool_world, "C")
    assert still["status"] == "accepted" and still["item_status"] == "accepted"
    assert pool_world.lot("C")["committed_kg"] == 450


def test_prediction_drop_updates_the_order_and_tells_everyone(db_client, buyer, farmer, pool_world, ordered):
    pool_world.add_farm("F", 300)
    pool_world.change("C", 200)
    order = order_get(db_client, buyer, ordered["order"]["id"])
    farms = by_farm(order, pool_world)
    assert farms["C"] == (200, "accepted") and farms["F"] == (250, "awaiting_farmer")
    assert order["committed_kg"] == 2000 and order["status"] == "placed"
    assert any("from 450" in n["body"] and "to 200" in n["body"] for n in notes(db_client, farmer, "order_update"))
    assert notes(db_client, buyer, "reallocation")[0]["body"].startswith("Shortage 250")


def test_prediction_increase_beyond_the_accepted_quantity_asks_the_farmer_again(db_client, buyer, farmer, pool_world):
    pool = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 2200)["id"])
    order = place(db_client, buyer, pool["id"]).json()
    accept_all(db_client, farmer)
    pool_world.change("E", 600)  # +200 kg tops up the unfilled pool from E
    order = order_get(db_client, buyer, order["id"])
    assert by_farm(order, pool_world)["E"] == (600, "awaiting_farmer") and order["status"] == "placed"
    assert any("now asks 600" in n["body"] for n in notes(db_client, farmer, "order_update"))


# =============================================================== cancellation
def test_cancel_releases_everything_and_closes_the_pool(db_client, buyer, farmer, pool_world, ordered):
    r = db_client.post(f"{API}/orders/{ordered['order']['id']}/cancel", headers=buyer.headers)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert all(pool_world.lot(n)["committed_kg"] == 0 and pool_world.lot(n)["available_kg"] > 0 for n in "ABCDE")
    assert {i["status"] for i in r.json()["items"]} == {"cancelled"}
    pool_world.change("C", 100)  # a closed pool is never rebalanced again
    assert db_client.get(f"{API}/pools/{ordered['pool']['id']}/events", headers=buyer.headers).json() == []
    rb = db_client.post(
        f"{API}/pools/{ordered['pool']['id']}/rebalance", headers={**buyer.headers, "Idempotency-Key": "z"}
    )
    assert rb.status_code == 409 and rb.json()["error"]["code"] == "pool_closed"
    assert db_client.post(f"{API}/orders/{ordered['order']['id']}/cancel", headers=buyer.headers).status_code == 409


# ============================================ collection, quality, fulfilment
def test_batches_need_an_accepted_item_a_recorded_harvest_and_an_active_hub(
    db_client, buyer, farmer, admin, pool_world, hub
):
    pool = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 2000)["id"])
    order = place(db_client, buyer, pool["id"]).json()
    item = order["items"][0]
    body = {"order_item_id": item["id"], "hub_id": hub["id"], "received_kg": 100}
    r = db_client.post(f"{API}/admin/batches", headers=admin.headers, json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "item_not_accepted"
    accept_all(db_client, farmer)
    r = db_client.post(f"{API}/admin/batches", headers=admin.headers, json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "harvest_not_recorded"
    db_client.patch(f"{API}/admin/hubs/{hub['id']}", headers=admin.headers, json={"is_active": False})
    names = {v["lot_id"]: k for k, v in pool_world.farms.items()}
    harvest(db_client, farmer, pool_world, names[item["lot_id"]], 600)
    r = db_client.post(f"{API}/admin/batches", headers=admin.headers, json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "hub_not_found"


def _deliver(
    client, admin, farmer, world, ordered, hub, name, received, accepted, rejected, grade="A", harvest_kg=None
):
    harvest(client, farmer, world, name, harvest_kg if harvest_kg is not None else received)
    item = next(
        i
        for i in order_get(client, ordered["buyer"], ordered["order"]["id"])["items"]
        if i["lot_id"] == world.farms[name]["lot_id"]
    )
    batch = client.post(
        f"{API}/admin/batches",
        headers=admin.headers,
        json={"order_item_id": item["id"], "hub_id": hub["id"], "received_kg": received},
    ).json()
    q = client.post(
        f"{API}/admin/batches/{batch['id']}/quality",
        headers=admin.headers,
        json={"grade": grade if accepted else None, "accepted_kg": accepted, "rejected_kg": rejected},
    )
    assert q.status_code == 200, q.text
    return item, batch


@pytest.fixture
def ordered_b(ordered, buyer):
    return {**ordered, "buyer": buyer}


def test_quality_rules(db_client, admin, farmer, pool_world, ordered_b, hub):
    harvest(db_client, farmer, pool_world, "A", 500)
    item = next(i for i in ordered_b["order"]["items"] if i["lot_id"] == pool_world.farms["A"]["lot_id"])
    batch = db_client.post(
        f"{API}/admin/batches",
        headers=admin.headers,
        json={"order_item_id": item["id"], "hub_id": hub["id"], "received_kg": 500},
    ).json()
    assert batch["code"].startswith("HQ-") and batch["status"] == "received" and batch["quality"] is None
    url = f"{API}/admin/batches/{batch['id']}/quality"
    for body, code in [
        ({"grade": "A", "accepted_kg": 400, "rejected_kg": 50}, "quantities_mismatch"),
        ({"grade": "C", "accepted_kg": 500, "rejected_kg": 0}, "grade_below_order_minimum"),  # buyer asked for B+
    ]:
        r = db_client.post(url, headers=admin.headers, json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == code
    assert (
        db_client.post(url, headers=admin.headers, json={"accepted_kg": 500, "rejected_kg": 0}).status_code == 422
    )  # grade required
    ok = db_client.post(
        url, headers=admin.headers, json={"grade": "B", "accepted_kg": 480, "rejected_kg": 20, "moisture_percent": 11.5}
    )
    assert (
        ok.status_code == 200
        and ok.json()["quality"]["result"] == "partially_accepted"
        and ok.json()["quality"]["data_kind"] == "measured"
    )
    dup = db_client.post(url, headers=admin.headers, json={"grade": "A", "accepted_kg": 500, "rejected_kg": 0})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "quality_already_recorded"


def test_fulfilment_counts_only_accepted_produce_and_closes_the_order(
    db_client, buyer, admin, farmer, pool_world, ordered_b, hub
):
    order_id = ordered_b["order"]["id"]
    deliveries = {
        "A": (500, 500, 0),
        "B": (350, 340, 10),
        "C": (450, 450, 0),
        "D": (300, 0, 300),
        "E": (450, 450, 0),
    }  # E delivers MORE than its 400 kg share
    items = {}
    for name, (received, acc, rej) in deliveries.items():
        items[name], _ = _deliver(
            db_client,
            admin,
            farmer,
            pool_world,
            ordered_b,
            hub,
            name,
            received,
            acc,
            rej,
            harvest_kg=max(received, 500),
        )
    early = db_client.post(f"{API}/orders/{order_id}/cancel", headers=buyer.headers)
    assert early.status_code == 409 and early.json()["error"]["code"] == "already_collected"
    results = {
        n: db_client.post(f"{API}/admin/order-items/{i['id']}/fulfil", headers=admin.headers).json()
        for n, i in items.items()
    }
    assert {n: (r["fulfilled_kg"], r["item_status"]) for n, r in results.items()} == {
        "A": (500, "fulfilled"),
        "B": (340, "fulfilled"),
        "C": (450, "fulfilled"),
        "D": (0, "short"),
        "E": (400, "fulfilled"),  # 450 accepted, capped at the 400 kg share
    }
    order = order_get(db_client, buyer, order_id)
    assert order["status"] == "partially_fulfilled" and order["fulfilled_kg"] == 1690
    # inventory: fulfilled reservations, D released; the pool is closed
    lot_a = pool_world.lot("A")
    assert [r["status"] for r in lot_a["reservations"] if r["status"] != "released"] == ["fulfilled"]
    assert pool_world.lot("D")["committed_kg"] == 0
    pool = db_client.get(f"{API}/pools/{ordered_b['pool']['id']}", headers=buyer.headers).json()
    assert pool["allocated_kg"] == 1690
    again = db_client.post(f"{API}/admin/order-items/{items['A']['id']}/fulfil", headers=admin.headers)
    assert again.status_code == 409


def test_fulfil_needs_batches_with_quality(db_client, admin, farmer, pool_world, ordered_b, hub):
    item = next(i for i in ordered_b["order"]["items"] if i["lot_id"] == pool_world.farms["A"]["lot_id"])
    r = db_client.post(f"{API}/admin/order-items/{item['id']}/fulfil", headers=admin.headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_batches"
    harvest(db_client, farmer, pool_world, "A", 500)
    db_client.post(
        f"{API}/admin/batches",
        headers=admin.headers,
        json={"order_item_id": item["id"], "hub_id": hub["id"], "received_kg": 500},
    )
    r = db_client.post(f"{API}/admin/order-items/{item['id']}/fulfil", headers=admin.headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "quality_pending"


def test_full_fulfilment_and_traceability(db_client, buyer, admin, farmer, other_farmer, pool_world, ordered_b, hub):
    codes = {}
    for name, kg in {"A": 500, "B": 350, "C": 450, "D": 300, "E": 400}.items():
        item, batch = _deliver(db_client, admin, farmer, pool_world, ordered_b, hub, name, kg, kg, 0)
        db_client.post(f"{API}/admin/order-items/{item['id']}/fulfil", headers=admin.headers)
        codes[name] = batch["code"]
    order = order_get(db_client, buyer, ordered_b["order"]["id"])
    assert order["status"] == "fulfilled" and order["fulfilled_kg"] == 2000
    trace = db_client.get(f"{API}/orders/{order['id']}/trace", headers=buyer.headers).json()
    assert trace["chain"].startswith("Order -> Pool") and len(trace["items"]) == 5 and trace["pool"]["closed"] is True
    steps = trace["items"][0]["steps"]
    kinds = {s["step"]: s["data_kind"] for s in steps}
    assert (
        kinds["allocation"] == "estimate"
        and kinds["harvest"] == "measured"
        and kinds["quality"] == "measured"
        and kinds["fulfilment"] == "measured"
    )
    assert kinds["prediction_feedback"] == "measured"
    assert any(e["action"] == "fulfilled" for e in steps[0]["detail"]["ledger"])
    # batch trace by code: buyer and owning farmer only
    bt = db_client.get(f"{API}/trace/batches/{codes['A']}", headers=buyer.headers)
    assert (
        bt.status_code == 200
        and bt.json()["harvest"]["data_kind"] == "measured"
        and bt.json()["prediction"]["data_kind"] == "estimate"
    )
    assert db_client.get(f"{API}/trace/batches/{codes['A']}", headers=farmer.headers).status_code == 200
    assert db_client.get(f"{API}/trace/batches/{codes['A']}", headers=other_farmer.headers).status_code == 404
    assert db_client.get(f"{API}/trace/batches/HQ-000000-ABCDEF", headers=admin.headers).status_code == 404
    assert {n["category"] for n in notes(db_client, farmer)} >= {"collection", "quality", "fulfilment"}


# ===================================================================== market
def test_supply_search_and_opportunities_show_only_opted_in_estimates(db_client, buyer, farmer, admin, pool_world):
    pool_world.add_farm("X", 999, opt_in=False)
    (row,) = db_client.get(f"{API}/market/supply", headers=buyer.headers).json()
    assert row["lots"] == 5 and row["available_kg"] == 2000 and row["data_kind"] == "estimate"
    params = {
        "crop_id": pool_world.crop["id"],
        "quantity_kg": 800,
        "window_start": days_from_today(30),
        "window_end": days_from_today(150),
    }
    res = db_client.get(f"{API}/market/harvests", headers=buyer.headers, params=params).json()
    assert res["eligible_supply_kg"] == 2000 and len(res["matches"]) == 5 and res["demand_id"] is None
    assert all(m["eligible"] and len(m["farm_ref"]) == 8 for m in res["matches"])
    assert pool_world.farms["X"]["lot_id"] not in {m["lot_id"] for m in res["matches"]}
    bad = db_client.get(
        f"{API}/market/harvests", headers=buyer.headers, params={**params, "window_end": days_from_today(1)}
    )
    assert bad.status_code == 422
    assert db_client.get(f"{API}/market/harvests", headers=farmer.headers, params=params).status_code == 403
    demand = make_demand(db_client, buyer, pool_world.crop["id"], 700)
    (op,) = db_client.get(f"{API}/market/opportunities", headers=farmer.headers).json()
    assert op["demand_id"] == demand["id"] and op["my_matching_cycles"] == 6 and "price" not in op
    (n,) = notes(db_client, farmer, "buyer_opportunity")
    assert "700" in n["body"] and "Fresh" not in n["body"]  # no buyer identity in the opportunity


# ================================================================ concurrency
def test_concurrent_orders_on_one_pool_create_exactly_one(db_container, db_client, buyer, pool_world):
    pool = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 2000)["id"])
    from app.schemas.marketplace import OrderCreate

    results: list[object] = []
    barrier = threading.Barrier(2)

    def attempt():
        with db_container.session_factory() as s:
            svc = build_marketplace_service(s, db_container)[0]
            barrier.wait()
            try:
                results.append(
                    svc.place_order(uuid.UUID(buyer.user_id), OrderCreate(pool_id=uuid.UUID(pool["id"])), None).id
                )
            except Exception as exc:
                results.append(type(exc).__name__)

    ts = [threading.Thread(target=attempt) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=30)
    assert sorted(type(r).__name__ for r in results) == ["UUID", "str"] and "ConflictError" in results
    with db_container.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM buyer_orders")) == 1
        assert conn.scalar(text("SELECT count(*) FROM buyer_order_items")) == 5


def test_concurrent_fulfilment_of_one_item_fulfils_once(
    db_container, db_client, admin, farmer, pool_world, ordered_b, hub
):
    item, _ = _deliver(db_client, admin, farmer, pool_world, ordered_b, hub, "A", 500, 500, 0)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def attempt():
        with db_container.session_factory() as s:
            svc = build_marketplace_service(s, db_container)[0]
            barrier.wait()
            try:
                svc.fulfil_item(uuid.UUID(admin.user_id), uuid.UUID(item["id"]))
                outcomes.append("ok")
            except Exception as exc:
                outcomes.append(getattr(exc, "code", type(exc).__name__))

    ts = [threading.Thread(target=attempt) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=30)
    assert sorted(outcomes) == ["item_not_fulfillable", "ok"]
    with db_container.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM allocation_ledger WHERE action = 'fulfilled'")) == 1
        assert conn.scalar(text("SELECT fulfilled_kg FROM buyer_orders")) == Decimal(500)


def test_replaying_the_same_reallocation_notifies_once(db_container, db_client, buyer, farmer, pool_world, ordered):
    pool_world.change("C", 200)  # shortage event -> buyer + farmer notifications
    (event,) = db_client.get(f"{API}/pools/{ordered['pool']['id']}/events", headers=buyer.headers).json()
    from app.schemas.pooling import EventOut

    before = (len(notes(db_client, buyer)), len(notes(db_client, farmer)))
    for _ in range(2):  # e.g. a retried hook after a crash
        with db_container.session_factory() as s:
            build_marketplace_service(s, db_container)[0].sync_pool(
                uuid.UUID(ordered["pool"]["id"]), EventOut.model_validate(event)
            )
    assert (len(notes(db_client, buyer)), len(notes(db_client, farmer))) == before


def test_lot_shows_its_pooling_opt_in_and_grade(db_client, farmer, pool_world):
    lot = pool_world.lot("A")
    assert lot["pool_eligible"] is True and lot["expected_grade"] == "B"
    r = db_client.patch(
        f"{API}/inventory/lots/{lot['id']}",
        headers=farmer.headers,
        json={"pool_eligible": False, "expected_grade": "A"},
    )
    assert (r.json()["pool_eligible"], r.json()["expected_grade"]) == (False, "A")


# ================================================ order lifecycle notifications
def test_order_notifications_show_the_order_id_produce_and_quantity(db_client, buyer, farmer, pool_world):
    pool = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 2000)["id"])
    order = place(db_client, buyer, pool["id"]).json()
    ref = f"#{order['id'][:8].upper()}"
    crop = pool_world.crop["name"]
    request = notes(db_client, farmer, "participation_request")[0]
    assert ref in request["title"] and crop in request["title"] and " kg of " in request["body"]
    accept_all(db_client, farmer)
    confirmed = notes(db_client, buyer, "participation_response")
    assert len(confirmed) == 5 and all(ref in n["title"] and crop in n["body"] for n in confirmed)


def test_farmer_progress_preparing_then_ready_notifies_the_buyer_once(db_client, buyer, farmer, other_farmer, ordered):
    p = db_client.get(f"{API}/participations", headers=farmer.headers, params={"limit": 100}).json()["items"][0]
    url = f"{API}/participations/{p['id']}/progress"
    assert db_client.post(url, headers=other_farmer.headers, json={"stage": "preparing"}).status_code == 404
    assert db_client.post(url, headers=buyer.headers, json={"stage": "preparing"}).status_code == 403
    r = db_client.post(url, headers=farmer.headers, json={"stage": "preparing"})
    assert r.status_code == 200 and r.json()["progress"] == "preparing" and r.json()["progress_at"]
    assert db_client.post(url, headers=farmer.headers, json={"stage": "preparing"}).status_code == 200  # retry
    r = db_client.post(url, headers=farmer.headers, json={"stage": "ready"})
    assert r.json()["progress"] == "ready"
    back = db_client.post(url, headers=farmer.headers, json={"stage": "preparing"})
    assert back.status_code == 409 and back.json()["error"]["code"] == "progress_backwards"
    updates = notes(db_client, buyer, "order_update")
    ref = f"#{ordered['order']['id'][:8].upper()}"
    assert sorted(n["title"].rsplit(" ", 1)[-1] for n in updates) == ["preparing", "ready"]  # no duplicates
    assert all(ref in n["title"] and " kg of " in n["body"] for n in updates)
    item = next(i for i in order_get(db_client, buyer, ordered["order"]["id"])["items"] if i["lot_id"] == p["lot_id"])
    assert item["farmer_progress"] == "ready"
    assert db_client.post(url, headers=farmer.headers, json={"stage": "shipped"}).status_code == 422


def test_progress_needs_an_accepted_request(db_client, buyer, farmer, pool_world):
    pool = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 500)["id"])
    place(db_client, buyer, pool["id"])
    p = pending(db_client, farmer)[0]
    r = db_client.post(f"{API}/participations/{p['id']}/progress", headers=farmer.headers, json={"stage": "ready"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_accepted"


def test_a_decline_tells_the_buyer_directly(db_client, buyer, farmer, pool_world):
    pool = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 500)["id"])
    order = place(db_client, buyer, pool["id"]).json()
    p = pending(db_client, farmer)[0]
    db_client.post(f"{API}/participations/{p['id']}/decline", headers=farmer.headers, json={"reason": "Crop damaged"})
    declined = [n for n in notes(db_client, buyer, "participation_response") if "declined" in n["title"]]
    assert len(declined) == 1 and f"#{order['id'][:8].upper()}" in declined[0]["title"]
    assert declined[0]["severity"] == "warning"


# ==================================== corrections that respect the audit trail
def test_a_harvest_can_be_corrected_until_produce_reaches_a_hub(
    db_client, db_container, admin, farmer, other_farmer, pool_world, ordered_b, hub
):
    harvest(db_client, farmer, pool_world, "A", 5000)  # a typo: 5000 instead of 500
    cid = pool_world.farms["A"]["cycle_id"]
    url = f"{API}/crop-cycles/{cid}/harvest-actual"
    assert (
        db_client.patch(url, headers=other_farmer.headers, json={"quantity_kg": 500, "reason": "typo"}).status_code
        == 404
    )
    assert db_client.patch(url, headers=farmer.headers, json={"quantity_kg": 500}).status_code == 422  # reason needed
    r = db_client.patch(url, headers=farmer.headers, json={"quantity_kg": 500, "reason": "Typed one zero too many"})
    assert r.status_code == 200, r.text
    assert r.json()["actual"]["quantity_kg"] == 500
    assert {row["actual_kg"] for row in r.json()["feedback"]} == {500}  # every prediction re-scored
    with db_container.engine.connect() as conn:
        row = conn.execute(
            text("SELECT quantity_kg, previous_quantity_kg, correction_reason FROM harvest_actuals")
        ).one()
    assert (float(row[0]), float(row[1]), row[2]) == (500, 5000, "Typed one zero too many")

    item = next(i for i in ordered_b["order"]["items"] if i["lot_id"] == pool_world.farms["A"]["lot_id"])
    batch = db_client.post(
        f"{API}/admin/batches",
        headers=admin.headers,
        json={"order_item_id": item["id"], "hub_id": hub["id"], "received_kg": 200},
    ).json()
    r = db_client.patch(url, headers=farmer.headers, json={"quantity_kg": 450, "reason": "again"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "harvest_in_use"

    # a mistaken batch can be removed before its quality check, not after
    assert db_client.delete(f"{API}/admin/batches/{batch['id']}", headers=farmer.headers).status_code == 403
    assert db_client.delete(f"{API}/admin/batches/{batch['id']}", headers=admin.headers).status_code == 204
    assert db_client.patch(url, headers=farmer.headers, json={"quantity_kg": 450, "reason": "again"}).status_code == 200
    batch = db_client.post(
        f"{API}/admin/batches",
        headers=admin.headers,
        json={"order_item_id": item["id"], "hub_id": hub["id"], "received_kg": 200},
    ).json()
    db_client.post(
        f"{API}/admin/batches/{batch['id']}/quality",
        headers=admin.headers,
        json={"grade": "A", "accepted_kg": 200, "rejected_kg": 0},
    )
    r = db_client.delete(f"{API}/admin/batches/{batch['id']}", headers=admin.headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "batch_in_use"
