"""Database-level guarantees of the intelligence layer (application bypassed)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from tests.integration.test_farming_schema import Db

pytestmark = pytest.mark.integration


@pytest.fixture
def db(db_container) -> Db:
    return Db(db_container.engine)


@pytest.fixture
def cycle_id(db):
    owner = db.user()
    return db.cycle(db.plot(db.farm(owner)), db.crop()), owner


def prediction(db, cycle, version=1, **kw):
    row = {
        "crop_cycle_id": cycle,
        "version": version,
        "status": "ok",
        "model_name": "m",
        "model_version": "1",
        "p10_kg": 1,
        "p50_kg": 2,
        "p90_kg": 3,
        "harvest_start_p10": "2026-03-01",
        "harvest_start_p50": "2026-03-05",
        "harvest_start_p90": "2026-03-09",
        "harvest_end_p90": "2026-03-30",
        "confidence_score": 50,
        "confidence_level": "medium",
        "confidence_basis": "heuristic",
        "risk_level": "low",
        "weather_status": "fresh",
        "payload": "{}",
    }
    row.update(kw)
    return db.insert("yield_predictions", **row)


def rejected(fn, *a, **kw):
    with pytest.raises(IntegrityError):
        fn(*a, **kw)


def test_versions_are_unique_per_cycle(db, cycle_id):
    prediction(db, cycle_id[0], 1)
    rejected(prediction, db, cycle_id[0], 1)
    assert prediction(db, cycle_id[0], 2)


@pytest.mark.parametrize(
    "bad",
    [
        {"p10_kg": 5},
        {"p90_kg": 1},
        {"p10_kg": -1},
        {"version": 0},
        {"confidence_score": 101},
        {"harvest_start_p10": "2026-04-01"},
        {"status": "guess"},
    ],
)
def test_prediction_checks(db, cycle_id, bad):
    rejected(prediction, db, cycle_id[0], **bad)


def test_insufficient_prediction_may_have_no_quantities(db, cycle_id):
    assert prediction(db, cycle_id[0], status="insufficient_data", p10_kg=None, p50_kg=None, p90_kg=None)


def test_one_actual_per_cycle_and_non_negative(db, cycle_id):
    cycle, owner = cycle_id
    rejected(
        db.insert,
        "harvest_actuals",
        crop_cycle_id=cycle,
        quantity_kg=-1,
        harvest_start_date="2026-03-01",
        recorded_by=owner,
    )
    db.insert("harvest_actuals", crop_cycle_id=cycle, quantity_kg=0, harvest_start_date="2026-03-01", recorded_by=owner)
    rejected(
        db.insert,
        "harvest_actuals",
        crop_cycle_id=cycle,
        quantity_kg=5,
        harvest_start_date="2026-03-01",
        recorded_by=owner,
    )


def lot(db, cycle, owner, **kw):
    row = {
        "crop_cycle_id": cycle,
        "owner_id": owner,
        "status": "open",
        "committable_kg": 10,
        "committed_kg": 0,
        "available_kg": 10,
        "shortfall_kg": 0,
        "basis": "x",
    }
    row.update(kw)
    return db.insert("inventory_lots", **row)


@pytest.mark.parametrize("field", ["committable_kg", "committed_kg", "available_kg", "shortfall_kg"])
def test_inventory_quantities_can_never_be_negative(db, cycle_id, field):
    rejected(lot, db, *cycle_id, **{field: -1})


def test_reservations_positive_and_booking_keys_single_use(db, cycle_id):
    lot_id = lot(db, *cycle_id)
    rejected(db.insert, "inventory_reservations", lot_id=lot_id, quantity_kg=0, booking_key="k", status="active")
    db.insert("inventory_reservations", lot_id=lot_id, quantity_kg=1, booking_key="k", status="released")
    rejected(db.insert, "inventory_reservations", lot_id=lot_id, quantity_kg=1, booking_key="k", status="active")


def test_crop_reference_checks(db):
    rejected(
        db.insert, "crops", name="A", category="vegetable", typical_duration_days=10, reference_yield_kg_per_acre=0
    )
    rejected(db.insert, "crops", name="B", category="vegetable", typical_duration_days=10, reference_yield_cv=0)
    rejected(db.insert, "crops", name="C", category="vegetable", typical_duration_days=10, water_need_mm=-1)


def test_calibration_versions_unique_per_scope(db):
    db.insert(
        "calibration_profiles",
        scope="global",
        version=1,
        sample_size=0,
        sufficient=False,
        bias_factor=1,
        interval_scale=1,
        note="n",
    )
    rejected(
        db.insert,
        "calibration_profiles",
        scope="global",
        version=1,
        sample_size=0,
        sufficient=False,
        bias_factor=1,
        interval_scale=1,
        note="n",
    )
    rejected(
        db.insert,
        "calibration_profiles",
        scope="x",
        version=1,
        sample_size=0,
        sufficient=False,
        bias_factor=0,
        interval_scale=1,
        note="n",
    )


def test_predictions_cannot_be_orphaned(db):
    rejected(prediction, db, str(uuid.uuid4()))
