"""Dynamic Predictive Harvest Pooling and Dynamic Reallocation, end to end on PostgreSQL."""

from __future__ import annotations

import contextlib
import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.composition import build_pool_service
from app.core.enums import UserRole
from app.repositories.pooling import PoolingRepository
from app.schemas.auth import CurrentUser
from app.services.inventory import InventoryService
from tests.conftest import make_demand, make_pool

pytestmark = pytest.mark.integration
API = "/api/v1"


def pool_get(client, buyer, pool_id):
    return client.get(f"{API}/pools/{pool_id}", headers=buyer.headers).json()


def by_lot(pool, world):
    names = {v["lot_id"]: k for k, v in world.farms.items()}
    return {names[a["lot_id"]]: a["quantity_kg"] for a in pool["allocations"] if a["quantity_kg"] > 0}


def events(client, buyer, pool_id):
    return client.get(f"{API}/pools/{pool_id}/events", headers=buyer.headers).json()


def ledger(client, buyer, pool_id):
    return client.get(f"{API}/pools/{pool_id}/ledger", headers=buyer.headers).json()


@pytest.fixture
def pool_2000(db_client, buyer, pool_world):
    demand = make_demand(db_client, buyer, pool_world.crop["id"], 2000)
    return make_pool(db_client, buyer, demand["id"])


# ======================================================= the critical scenario


@pytest.mark.parametrize("algorithm", ["greedy", "lp"])
def test_critical_scenario_creates_a_2000_kg_pool_from_five_farms(db_client, buyer, pool_world, algorithm):
    demand = make_demand(db_client, buyer, pool_world.crop["id"], 2000)
    pool = make_pool(db_client, buyer, demand["id"], algorithm=algorithm)
    assert pool["status"] == "filled" and pool["allocated_kg"] == 2000 and pool["shortage_kg"] == 0
    assert by_lot(pool, pool_world) == {"A": 500, "B": 350, "C": 450, "D": 300, "E": 400}
    assert all(a["reservation_id"] for a in pool["allocations"])
    for name in "ABCDE":  # every farm is fully committed, never beyond its supply
        lot = pool_world.lot(name)
        assert lot["available_kg"] == 0 and lot["committed_kg"] == lot["committable_kg"]


def test_farm_c_drop_detects_exactly_250_kg_and_no_replacement_without_spare_supply(
    db_client, buyer, pool_world, pool_2000
):
    pool_world.change("C", 200)
    (event,) = events(db_client, buyer, pool_2000["id"])
    assert event["shortage_kg"] == 250 and event["replaced_kg"] == 0 and event["unresolved_kg"] == 250
    assert event["outcome"] == "none" and event["trigger"] == "prediction_change"
    assert event["before"]["allocations"][pool_world.farms["C"]["lot_id"]] == "450.000"
    assert event["after"]["allocations"][pool_world.farms["C"]["lot_id"]] == "200.000"
    assert "this pool loses 250" in event["reason"]
    pool = pool_get(db_client, buyer, pool_2000["id"])
    assert pool["status"] == "at_risk" and pool["allocated_kg"] == 1750 and pool["shortage_kg"] == 250
    assert by_lot(pool, pool_world)["C"] == 200
    lot_c = pool_world.lot("C")
    assert (
        lot_c["status"] == "open" and lot_c["committed_kg"] == 200 and lot_c["shortfall_kg"] == 0
    )  # reservation resized


def test_full_replacement_from_a_new_eligible_farm(db_client, buyer, pool_world, pool_2000):
    pool_world.add_farm("F", 300)
    pool_world.change("C", 200)
    (event,) = events(db_client, buyer, pool_2000["id"])
    assert (event["shortage_kg"], event["replaced_kg"], event["unresolved_kg"], event["outcome"]) == (
        250,
        250,
        0,
        "full",
    )
    pool = pool_get(db_client, buyer, pool_2000["id"])
    assert pool["status"] == "filled" and pool["allocated_kg"] == 2000 and pool["shortage_kg"] == 0
    assert by_lot(pool, pool_world) == {"A": 500, "B": 350, "C": 200, "D": 300, "E": 400, "F": 250}
    assert pool_world.lot("F")["available_kg"] == 50  # never more than F could promise


def test_partial_replacement(db_client, buyer, pool_world, pool_2000):
    pool_world.add_farm("F", 100)
    pool_world.change("C", 200)
    (event,) = events(db_client, buyer, pool_2000["id"])
    assert (event["shortage_kg"], event["replaced_kg"], event["unresolved_kg"], event["outcome"]) == (
        250,
        100,
        150,
        "partial",
    )
    pool = pool_get(db_client, buyer, pool_2000["id"])
    assert (
        pool["status"] == "at_risk" and pool["allocated_kg"] == 1850 and pool["shortage_kg"] == 150
    )  # 2000 - 250 + 100


def test_replacement_is_spread_over_several_farms_when_needed(db_client, buyer, pool_world, pool_2000):
    pool_world.add_farm("F", 120)
    pool_world.add_farm("G", 200)
    pool_world.change("C", 200)
    (event,) = events(db_client, buyer, pool_2000["id"])
    assert event["outcome"] == "full" and event["replaced_kg"] == 250
    got = by_lot(pool_get(db_client, buyer, pool_2000["id"]), pool_world)
    assert got["F"] + got["G"] == 250 and got["F"] <= 120 and got["G"] <= 200


@pytest.mark.parametrize(
    ("farm_kwargs", "reason"),
    [
        ({"opt_in": False}, "not_opted_in"),
        ({"grade": "C"}, "grade_below_minimum"),
        ({"lat": 15.5, "lon": 76.6}, "too_far"),
    ],
)
def test_ineligible_farms_are_not_used_as_replacements(db_client, buyer, pool_world, farm_kwargs, reason):
    demand = make_demand(
        db_client,
        buyer,
        pool_world.crop["id"],
        2000,
        min_grade="B",
        latitude=12.30,
        longitude=76.64,
        max_distance_km=100,
    )
    pool = make_pool(db_client, buyer, demand["id"])
    pool_world.add_farm("F", 500, **farm_kwargs)
    pool_world.change("C", 200)
    (event,) = events(db_client, buyer, pool["id"])
    assert event["outcome"] == "none" and event["unresolved_kg"] == 250
    match = next(
        m
        for m in db_client.get(f"{API}/buyer-demands/{demand['id']}/matches", headers=buyer.headers).json()["matches"]
        if m["lot_id"] == pool_world.farms["F"]["lot_id"]
    )
    assert not match["eligible"] and reason in match["reasons"]


def test_prediction_increase_tops_up_an_unfilled_pool(db_client, buyer, pool_world):
    demand = make_demand(db_client, buyer, pool_world.crop["id"], 2200)  # more than the 2000 kg available
    pool = make_pool(db_client, buyer, demand["id"])
    assert pool["status"] == "partial" and pool["allocated_kg"] == 2000
    pool_world.change("E", 600)  # +200 kg
    (event,) = events(db_client, buyer, pool["id"])
    assert (event["outcome"], event["shortage_kg"], event["topped_up_kg"]) == ("top_up", 0, 200)
    assert pool_get(db_client, buyer, pool["id"])["status"] == "filled"


def test_prediction_increase_on_a_full_pool_changes_nothing(db_client, buyer, pool_world, pool_2000):
    pool_world.change("E", 600)
    (event,) = events(db_client, buyer, pool_2000["id"])
    assert event["outcome"] == "no_change" and pool_world.lot("E")["available_kg"] == 200


def test_insufficient_supply_creates_a_partial_pool(db_client, buyer, pool_world):
    pool = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 3000)["id"])
    assert pool["status"] == "partial" and pool["allocated_kg"] == 2000 and pool["shortage_kg"] == 0


def test_no_eligible_supply_creates_an_unfilled_pool(db_client, api, buyer, admin, pool_world):
    onion = api.crop(admin, name="Onion")
    pool = make_pool(db_client, buyer, make_demand(db_client, buyer, onion["id"], 100)["id"])
    assert pool["status"] == "unfilled" and pool["allocations"] == []


# ======================================= competing pools, multiple reservations


def test_competing_pools_share_a_lot_and_the_newest_commitment_is_cut_first(db_client, buyer, pool_world):
    p1 = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 1600)["id"])
    p2 = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 400)["id"])
    a1, a2 = by_lot(p1, pool_world), by_lot(p2, pool_world)
    shared = next(n for n in a1 if n in a2)
    old_share, new_share = a1[shared], a2[shared]
    committed = old_share + new_share
    drop_to = committed - (new_share + 10)  # shortfall larger than the newer pool's share
    pool_world.change(shared, drop_to)
    (e1,) = events(db_client, buyer, p1["id"])
    (e2,) = events(db_client, buyer, p2["id"])
    assert e2["shortage_kg"] == new_share  # newer pool absorbs first, completely
    assert e1["shortage_kg"] == 10  # older pool loses only the remainder
    assert e1["shortage_kg"] + e2["shortage_kg"] == committed - drop_to  # exactly the lot's shortfall
    lot = pool_world.lot(shared)
    assert lot["committed_kg"] == drop_to and lot["shortfall_kg"] == 0


@pytest.mark.parametrize("older_first", [True, False])
def test_shared_lot_cuts_are_identical_whichever_pool_is_processed_first(
    db_container, db_client, buyer, pool_world, older_first
):
    """Regression: the older pool's reduction used to fail when it was processed first (lot still over-committed)."""
    from app.composition import build_prediction_service
    from app.schemas.intelligence import PredictionRequest

    p1 = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 1600)["id"])
    p2 = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 400)["id"])
    a1, a2 = by_lot(p1, pool_world), by_lot(p2, pool_world)
    shared = next(n for n in a1 if n in a2)
    drop_to = a1[shared] + a2[shared] - (a2[shared] + 10)
    pool_world.predictor.quantities[pool_world.farms[shared]["area"]] = Decimal(str(drop_to))
    with db_container.session_factory() as s:  # lower the lot without the automatic trigger
        svc = build_prediction_service(s, db_container)
        svc._on_lot_changed = None
        svc.create(
            uuid.UUID(pool_world.farmer.user_id), uuid.UUID(pool_world.farms[shared]["cycle_id"]), PredictionRequest()
        )
    order = [p1, p2] if older_first else [p2, p1]
    for p in order:
        with db_container.session_factory() as s:
            build_pool_service(s, db_container)._rebalance(
                uuid.UUID(p["id"]), "manual", None, f"order-test:{p['id']}", None
            )
    (e1,), (e2,) = events(db_client, buyer, p1["id"]), events(db_client, buyer, p2["id"])
    assert (e1["shortage_kg"], e2["shortage_kg"]) == (10, a2[shared])
    lot = pool_world.lot(shared)
    assert lot["committed_kg"] == drop_to and lot["shortfall_kg"] == 0 and lot["status"] == "open"


def test_a_farmers_own_reservation_is_never_cut_by_a_pool(db_client, buyer, farmer, pool_world):
    lot_id = pool_world.farms["E"]["lot_id"]
    db_client.post(
        f"{API}/inventory/lots/{lot_id}/reservations",
        headers=farmer.headers,
        json={"quantity_kg": 100, "booking_key": "my-own"},
    )
    pool = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 2000)["id"])
    assert by_lot(pool, pool_world)["E"] == 300  # the farmer's 100 kg was respected
    pool_world.change("E", 250)  # shortfall 150 across 400 committed
    (event,) = events(db_client, buyer, pool["id"])
    assert event["shortage_kg"] == 150
    reservations = {r["booking_key"]: r for r in pool_world.lot("E")["reservations"]}
    assert reservations["my-own"]["status"] == "active" and reservations["my-own"]["quantity_kg"] == 100


# ================================================== idempotency, rollback, races


def test_pool_creation_is_idempotent(db_client, buyer, pool_world):
    demand = make_demand(db_client, buyer, pool_world.crop["id"], 2000)
    first = make_pool(db_client, buyer, demand["id"], key="order-77")
    again = make_pool(db_client, buyer, demand["id"], key="order-77")
    assert again["id"] == first["id"] and again["allocated_kg"] == 2000
    other = db_client.post(
        f"{API}/buyer-demands/{demand['id']}/pool", headers={**buyer.headers, "Idempotency-Key": "different"}, json={}
    )
    assert other.status_code == 409 and other.json()["error"]["code"] == "pool_exists"
    assert pool_world.lot("A")["committed_kg"] == 500  # nothing double-booked


def test_rebalance_is_idempotent_and_requires_a_key(db_client, buyer, pool_world, pool_2000):
    url = f"{API}/pools/{pool_2000['id']}/rebalance"
    assert db_client.post(url, headers=buyer.headers).status_code == 422  # key required
    pool_world.add_farm("F", 300)
    first = db_client.post(url, headers={**buyer.headers, "Idempotency-Key": "r1"}).json()
    before = len(ledger(db_client, buyer, pool_2000["id"]))
    second = db_client.post(url, headers={**buyer.headers, "Idempotency-Key": "r1"}).json()
    assert second == first and len(ledger(db_client, buyer, pool_2000["id"])) == before
    assert first["outcome"] == "no_change"


def test_duplicate_prediction_trigger_is_applied_once(db_container, db_client, buyer, pool_world, pool_2000):
    pred = pool_world.change("C", 200)
    with db_container.session_factory() as session:
        build_pool_service(session, db_container).on_lot_changed(
            uuid.UUID(pool_world.farms["C"]["lot_id"]), f"prediction:{pred['id']}"
        )
    assert len(events(db_client, buyer, pool_2000["id"])) == 1


def _snapshot(db_container):
    with db_container.engine.connect() as conn:
        return (
            conn.execute(text("SELECT lot_id, quantity_kg, status FROM harvest_allocations ORDER BY lot_id")).all(),
            conn.execute(text("SELECT id, status, quantity_kg FROM inventory_reservations ORDER BY id")).all(),
            conn.scalar(text("SELECT count(*) FROM allocation_ledger")),
            conn.scalar(text("SELECT count(*) FROM reallocation_events")),
            conn.execute(text("SELECT status, allocated_kg, shortage_kg FROM harvest_pools")).all(),
        )


def test_a_failing_reallocation_rolls_back_completely(
    db_container, db_client, buyer, pool_world, pool_2000, monkeypatch
):
    pool_world.add_farm("F", 300)
    pool_world.predictor.quantities[pool_world.farms["C"]["area"]] = 200
    calls = {"n": 0}
    original = InventoryService.reserve_locked

    def flaky(self, lot, qty, key, note):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:  # fail half-way: C has already been shrunk; adding F's replacement crashes
            raise RuntimeError("simulated crash")
        return original(self, lot, qty, key, note)

    # the prediction itself is saved; the automatic reallocation fails and must leave the pool untouched
    before = _snapshot(db_container)
    monkeypatch.setattr(InventoryService, "reserve_locked", flaky)
    r = db_client.post(
        f"{API}/crop-cycles/{pool_world.farms['C']['cycle_id']}/predictions", headers=pool_world.farmer.headers, json={}
    )
    assert r.status_code == 201
    monkeypatch.undo()
    after = _snapshot(db_container)
    assert after[0] == before[0] and after[2:] == before[2:]  # allocations, ledger, events, pool unchanged
    # a manual rebalance afterwards completes the job
    ok = db_client.post(
        f"{API}/pools/{pool_2000['id']}/rebalance", headers={**buyer.headers, "Idempotency-Key": "after-crash"}
    ).json()
    assert ok["outcome"] == "full" and ok["replaced_kg"] == 250


def test_manual_rebalance_failure_raises_and_changes_nothing(db_container, buyer, pool_world, pool_2000, monkeypatch):
    pool_world.add_farm("F", 300)
    pool_world.predictor.quantities[pool_world.farms["C"]["area"]] = 200
    with db_container.session_factory() as s:  # lower C's lot without triggering pools
        from app.composition import build_prediction_service

        svc = build_prediction_service(s, db_container)
        svc._on_lot_changed = None
        from app.schemas.intelligence import PredictionRequest

        svc.create(
            uuid.UUID(pool_world.farmer.user_id), uuid.UUID(pool_world.farms["C"]["cycle_id"]), PredictionRequest()
        )
    before = _snapshot(db_container)
    monkeypatch.setattr(InventoryService, "reserve_locked", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    user = CurrentUser(user_id=uuid.UUID(buyer.user_id), role=UserRole.BUYER, session_id=uuid.uuid4())
    with db_container.session_factory() as s, pytest.raises(RuntimeError):
        build_pool_service(s, db_container).rebalance(user, uuid.UUID(pool_2000["id"]), "k")
    assert _snapshot(db_container) == before


def test_concurrent_pools_cannot_over_allocate_shared_supply(db_container, db_client, buyer, pool_world, monkeypatch):
    d1 = make_demand(db_client, buyer, pool_world.crop["id"], 2000)
    d2 = make_demand(db_client, buyer, pool_world.crop["id"], 2000)
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

    def attempt(demand_id):
        with db_container.session_factory() as s:
            results.append(
                build_pool_service(s, db_container).create_pool(
                    uuid.UUID(buyer.user_id),
                    uuid.UUID(demand_id),
                    PoolCreate(algorithm="greedy", max_pool_risk=100),
                    None,
                )
            )

    threads = [threading.Thread(target=attempt, args=(d["id"],)) for d in (d1, d2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    monkeypatch.undo()
    assert len(results) == 2
    assert sorted(float(p.allocated_kg) for p in results) == [0.0, 2000.0]
    for name in "ABCDE":
        lot = pool_world.lot(name)
        assert lot["committed_kg"] <= lot["committable_kg"] and lot["available_kg"] >= 0


def test_pools_never_take_supply_already_committed(db_client, buyer, farmer, pool_world):
    db_client.post(
        f"{API}/inventory/lots/{pool_world.farms['A']['lot_id']}/reservations",
        headers=farmer.headers,
        json={"quantity_kg": 500, "booking_key": "sold"},
    )
    pool = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 2000)["id"])
    assert pool["allocated_kg"] == 1500 and "A" not in by_lot(pool, pool_world)


# ======================================================================= audit


def test_audit_ledger_reconstructs_every_allocation(db_client, buyer, pool_world, pool_2000):
    pool_world.add_farm("F", 300)
    pool_world.change("C", 200)
    rows = ledger(db_client, buyer, pool_2000["id"])
    (event,) = events(db_client, buyer, pool_2000["id"])
    assert [r["action"] for r in rows][:5] == ["allocated"] * 5
    c, f = pool_world.farms["C"]["lot_id"], pool_world.farms["F"]["lot_id"]
    reduce_c = next(r for r in rows if r["lot_id"] == c and r["action"] == "reduced")
    add_f = next(r for r in rows if r["lot_id"] == f)
    assert (reduce_c["quantity_before"], reduce_c["quantity_after"], reduce_c["reallocation_event_id"]) == (
        450,
        200,
        event["id"],
    )
    assert (add_f["action"], add_f["quantity_before"], add_f["quantity_after"], add_f["reallocation_event_id"]) == (
        "replacement_added",
        0,
        250,
        event["id"],
    )
    final = {a["lot_id"]: a["quantity_kg"] for a in pool_get(db_client, buyer, pool_2000["id"])["allocations"]}
    replay: dict[str, float] = {}
    for r in rows:  # replaying the ledger gives the current state exactly
        assert r["quantity_before"] == replay.get(r["lot_id"], 0)
        replay[r["lot_id"]] = r["quantity_after"]
    assert replay == final
    assert event["after"]["allocated_kg"] == "2000.000" and event["before"]["allocated_kg"] == "2000.000"


def test_replaced_reservations_are_released_not_deleted(db_container, db_client, buyer, pool_world, pool_2000):
    pool_world.change("C", 200)
    rows = pool_world.lot("C")["reservations"]
    statuses = sorted((r["status"], r["quantity_kg"]) for r in rows)
    assert statuses == [("active", 200), ("released", 450)]


def test_harvest_record_also_triggers_reallocation(db_client, buyer, farmer, pool_world, pool_2000):
    cid = pool_world.farms["C"]["cycle_id"]
    from tests.conftest import days_from_today

    db_client.patch(
        f"{API}/crop-cycles/{cid}",
        headers=farmer.headers,
        json={"status": "harvested", "actual_harvest_date": days_from_today(-1)},
    )
    db_client.post(f"{API}/crop-cycles/{cid}/harvest-actual", headers=farmer.headers, json={"quantity_kg": 300})
    (event,) = events(db_client, buyer, pool_2000["id"])
    assert event["shortage_kg"] == 150 and event["trigger_ref"].startswith("harvest:")


def test_an_open_demand_can_be_cancelled_but_a_pooled_one_cannot(db_client, buyer, pool_world):
    open_demand = make_demand(db_client, buyer, pool_world.crop["id"], 100)
    url = f"/api/v1/buyer-demands/{open_demand['id']}/cancel"
    r = db_client.post(url, headers=buyer.headers)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert db_client.post(url, headers=buyer.headers).json()["status"] == "cancelled"  # repeat is harmless
    pooled = make_demand(db_client, buyer, pool_world.crop["id"], 200)
    make_pool(db_client, buyer, pooled["id"])
    r = db_client.post(f"/api/v1/buyer-demands/{pooled['id']}/cancel", headers=buyer.headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "demand_pooled"
