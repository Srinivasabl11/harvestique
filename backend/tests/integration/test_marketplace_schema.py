"""Database-level guarantees of the Phase 6 tables (the application is bypassed)."""

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
    buyer, farmer = db.user("+919000000401"), db.user("+919000000402")
    crop = db.crop()
    cycle = db.cycle(db.plot(db.farm(farmer)), crop)
    lot = db.insert(
        "inventory_lots",
        crop_cycle_id=cycle,
        owner_id=farmer,
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
        status="pooled",
    )
    pool = db.insert(
        "harvest_pools",
        demand_id=demand,
        buyer_id=buyer,
        status="filled",
        algorithm="greedy",
        demand_kg=100,
        allocated_kg=100,
        shortage_kg=0,
        max_pool_risk=50,
        max_share="0.4",
        weights="{}",
        version=1,
    )
    member = db.insert("harvest_pool_members", pool_id=pool, lot_id=lot, score=50, components="{}")
    alloc = db.insert(
        "harvest_allocations",
        pool_id=pool,
        lot_id=lot,
        member_id=member,
        quantity_kg=100,
        status="active",
        risk_level="low",
        reservation_seq=1,
    )
    hub = db.insert("collection_hubs", name="Hub")
    order = db.insert(
        "buyer_orders", buyer_id=buyer, pool_id=pool, status="placed", ordered_kg=100, fulfilled_kg=0, version=1
    )
    part = db.insert("farmer_participations", allocation_id=alloc, farmer_id=farmer, status="pending")
    item = db.insert(
        "buyer_order_items",
        order_id=order,
        allocation_id=alloc,
        lot_id=lot,
        farmer_id=farmer,
        participation_id=part,
        quantity_kg=100,
        fulfilled_kg=0,
        status="awaiting_farmer",
    )
    actual = db.insert(
        "harvest_actuals", crop_cycle_id=cycle, quantity_kg=100, harvest_start_date="2027-01-05", recorded_by=farmer
    )
    return dict(
        buyer=buyer,
        farmer=farmer,
        lot=lot,
        pool=pool,
        alloc=alloc,
        hub=hub,
        order=order,
        part=part,
        item=item,
        actual=actual,
    )


def rejected(fn, *a, **kw):
    with pytest.raises(IntegrityError):
        fn(*a, **kw)


def batch(db, b, code="HQ-1", **kw):
    row = {
        "code": code,
        "order_item_id": b["item"],
        "lot_id": b["lot"],
        "harvest_actual_id": b["actual"],
        "hub_id": b["hub"],
        "received_kg": 10,
        "received_at": "2027-01-06T08:00:00+05:30",
        "received_by": b["buyer"],
        "status": "received",
    }
    row.update(kw)
    return db.insert("produce_batches", **row)


def test_one_order_per_pool_and_fulfilled_within_ordered(db, base):
    rejected(
        db.insert,
        "buyer_orders",
        buyer_id=base["buyer"],
        pool_id=base["pool"],
        status="placed",
        ordered_kg=100,
        fulfilled_kg=0,
        version=1,
    )
    rejected(db.run, "UPDATE buyer_orders SET fulfilled_kg = 101 WHERE id = :i", i=base["order"])
    rejected(db.run, "UPDATE buyer_orders SET status = 'shipped' WHERE id = :i", i=base["order"])


def test_order_items_one_per_allocation_and_quantities_sane(db, base):
    rejected(
        db.insert,
        "buyer_order_items",
        order_id=base["order"],
        allocation_id=base["alloc"],
        lot_id=base["lot"],
        farmer_id=base["farmer"],
        participation_id=base["part"],
        quantity_kg=1,
        fulfilled_kg=0,
        status="accepted",
    )
    rejected(db.run, "UPDATE buyer_order_items SET fulfilled_kg = 101 WHERE id = :i", i=base["item"])
    rejected(db.run, "UPDATE buyer_order_items SET quantity_kg = -1 WHERE id = :i", i=base["item"])


def test_one_participation_per_allocation(db, base):
    rejected(
        db.insert, "farmer_participations", allocation_id=base["alloc"], farmer_id=base["farmer"], status="pending"
    )


def test_batches_unique_code_positive_weight(db, base):
    batch(db, base)
    rejected(batch, db, base)  # duplicate code
    rejected(batch, db, base, code="HQ-2", received_kg=0)


@pytest.mark.parametrize(
    "bad",
    [
        {"result": "accepted", "accepted_kg": 5, "rejected_kg": 5},
        {"result": "rejected", "accepted_kg": 5, "rejected_kg": 5},
        {"result": "partially_accepted", "accepted_kg": 10, "rejected_kg": 0},
        {"result": "accepted", "accepted_kg": -1, "rejected_kg": 0},
        {"result": "accepted", "accepted_kg": 10, "rejected_kg": 0, "moisture_percent": 101},
        {"result": "great", "accepted_kg": 10, "rejected_kg": 0},
    ],
)
def test_quality_result_must_match_quantities(db, base, bad):
    b = batch(db, base)
    row = {"batch_id": b, "inspector_id": base["buyer"], "grade": "A", "checked_at": "2027-01-06T09:00:00+05:30", **bad}
    rejected(db.insert, "quality_checks", **row)


def test_one_quality_check_per_batch(db, base):
    b = batch(db, base)
    row = {
        "batch_id": b,
        "inspector_id": base["buyer"],
        "grade": "A",
        "result": "accepted",
        "accepted_kg": 10,
        "rejected_kg": 0,
        "checked_at": "2027-01-06T09:00:00+05:30",
    }
    db.insert("quality_checks", **row)
    rejected(db.insert, "quality_checks", **row)


def test_hub_names_unique_and_coordinates_paired(db, base):
    rejected(db.insert, "collection_hubs", name="Hub")
    rejected(db.insert, "collection_hubs", name="Other", latitude=12.3)


def test_notification_dedup_and_valid_category(db, base):
    row = {
        "user_id": base["farmer"],
        "category": "reminder",
        "title": "t",
        "body": "b",
        "severity": "info",
        "data": "{}",
        "dedup_key": "k",
    }
    db.insert("notifications", **row)
    rejected(db.insert, "notifications", **row)
    rejected(db.insert, "notifications", **{**row, "dedup_key": "k2", "category": "spam"})


def test_reminder_enums_and_crop_health_dimensions(db, base):
    rejected(
        db.insert,
        "reminders",
        owner_id=base["farmer"],
        reminder_type="nap",
        title="t",
        due_at="2027-01-01T09:00:00+05:30",
        recurrence="none",
        status="pending",
        source="user",
    )
    rejected(
        db.insert,
        "reminders",
        owner_id=base["farmer"],
        reminder_type="custom",
        title="t",
        due_at="2027-01-01T09:00:00+05:30",
        recurrence="hourly",
        status="pending",
        source="user",
    )
    rejected(
        db.insert,
        "crop_health_analyses",
        owner_id=base["farmer"],
        image_sha256="0" * 64,
        width=0,
        height=10,
        label="healthy",
        probabilities="{}",
        features="{}",
        model_name="m",
        model_version="1",
    )
    rejected(
        db.insert,
        "crop_health_analyses",
        owner_id=base["farmer"],
        image_sha256="0" * 64,
        width=10,
        height=10,
        label="certainly_blight",
        probabilities="{}",
        features="{}",
        model_name="m",
        model_version="1",
    )


def test_restrict_keeps_audit_history(db, base):
    batch(db, base)
    rejected(db.run, "DELETE FROM buyer_order_items WHERE id = :i", i=base["item"])
    rejected(db.run, "DELETE FROM collection_hubs WHERE id = :i", i=base["hub"])
