"""Database-level guarantees of harvest pooling (application bypassed)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from tests.integration.test_farming_schema import Db

pytestmark = pytest.mark.integration


@pytest.fixture
def db(db_container) -> Db:
    return Db(db_container.engine)


@pytest.fixture
def base(db):
    buyer = db.user("+919000000301")
    crop = db.crop()
    lot_owner = db.user("+919000000302")
    cycle = db.cycle(db.plot(db.farm(lot_owner)), crop)
    lot = db.insert(
        "inventory_lots",
        crop_cycle_id=cycle,
        owner_id=lot_owner,
        status="open",
        committable_kg=100,
        committed_kg=0,
        available_kg=100,
        shortfall_kg=0,
        basis="x",
    )
    demand = db.insert(
        "buyer_demands",
        buyer_id=buyer,
        crop_id=crop,
        quantity_kg=100,
        window_start="2027-01-01",
        window_end="2027-02-01",
        min_grade="C",
        min_confidence=0,
        max_risk=100,
        status="open",
    )
    return {"buyer": buyer, "crop": crop, "lot": lot, "demand": demand}


def pool(db, b, **kw):
    row = {
        "demand_id": b["demand"],
        "buyer_id": b["buyer"],
        "status": "filled",
        "algorithm": "lp",
        "demand_kg": 100,
        "allocated_kg": 100,
        "shortage_kg": 0,
        "max_pool_risk": 50,
        "max_share": "0.4",
        "weights": "{}",
        "version": 1,
    }
    row.update(kw)
    return db.insert("harvest_pools", **row)


def rejected(fn, *a, **kw):
    with pytest.raises(IntegrityError):
        fn(*a, **kw)


@pytest.mark.parametrize(
    "bad",
    [
        {"quantity_kg": 0},
        {"window_end": "2026-12-01"},
        {"latitude": 12},
        {"max_distance_km": 0},
        {"min_confidence": 101},
        {"min_grade": "Z"},
    ],
)
def test_demand_checks(db, base, bad):
    row = {
        "buyer_id": base["buyer"],
        "crop_id": base["crop"],
        "quantity_kg": 1,
        "window_start": "2027-01-01",
        "window_end": "2027-02-01",
        "min_grade": "C",
        "min_confidence": 0,
        "max_risk": 100,
        "status": "open",
    }
    row.update(bad)
    rejected(db.insert, "buyer_demands", **row)


@pytest.mark.parametrize(
    "bad",
    [{"allocated_kg": 101}, {"allocated_kg": -1}, {"shortage_kg": -1}, {"status": "magic"}, {"algorithm": "quantum"}],
)
def test_pool_checks(db, base, bad):
    rejected(pool, db, base, **bad)


def test_one_pool_per_demand(db, base):
    pool(db, base)
    rejected(pool, db, base)


def test_one_allocation_per_pool_and_lot_never_negative(db, base):
    p = pool(db, base)
    member = db.insert("harvest_pool_members", pool_id=p, lot_id=base["lot"], score=50, components="{}")
    alloc = {
        "pool_id": p,
        "lot_id": base["lot"],
        "member_id": member,
        "quantity_kg": 10,
        "status": "active",
        "risk_level": "low",
        "reservation_seq": 1,
    }
    db.insert("harvest_allocations", **alloc)
    rejected(db.insert, "harvest_allocations", **alloc)
    rejected(db.insert, "harvest_allocations", **{**alloc, "quantity_kg": -1})


def test_event_must_account_for_its_shortage_and_keys_are_unique(db, base):
    p = pool(db, base)
    ev = {
        "pool_id": p,
        "trigger": "manual",
        "idempotency_key": "k1",
        "outcome": "partial",
        "algorithm": "lp",
        "shortage_kg": 250,
        "replaced_kg": 100,
        "unresolved_kg": 150,
        "topped_up_kg": 0,
        "steps": 1,
        "duration_ms": 1,
        "reason": "r",
        "before": "{}",
        "after": "{}",
    }
    db.insert("reallocation_events", **ev)
    rejected(db.insert, "reallocation_events", **ev)  # duplicate idempotency key
    rejected(
        db.insert, "reallocation_events", **{**ev, "idempotency_key": "k2", "unresolved_kg": 100}
    )  # 100 + 100 < 250


def test_ledger_quantities_never_negative(db, base):
    p = pool(db, base)
    rejected(
        db.insert,
        "allocation_ledger",
        pool_id=p,
        lot_id=base["lot"],
        action="reduced",
        quantity_before=-1,
        quantity_after=0,
        reason="r",
    )
