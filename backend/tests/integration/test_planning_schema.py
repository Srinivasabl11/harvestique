"""Database-level guarantees for crop plans, enforced even when the application is bypassed."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.integration.test_farming_schema import Db, uid

pytestmark = pytest.mark.integration

ITEM = {
    "position": 0,
    "crop_name": "Tomato",
    "area_acres": 1,
    "sowing_date": "2026-11-01",
    "duration_days": 100,
    "harvest_window_days": 30,
    "batches": 1,
    "yield_low_kg": 1,
    "yield_expected_kg": 2,
    "yield_high_kg": 3,
    "price_low": 1,
    "price_expected": 2,
    "price_high": 3,
    "seed_cost": 0,
    "fertilizer_cost": 0,
    "pesticide_cost": 0,
    "irrigation_cost": 0,
    "machinery_cost": 0,
    "other_cost": 0,
    "labour_person_days": 0,
    "labour_wage": 0,
    "fixed_cost": 0,
    "demand_level": "medium",
    "declared_risk": "medium",
    "estimate_basis": "local_knowledge",
}


@pytest.fixture
def db(db_container) -> Db:
    return Db(db_container.engine)


def make_plan(db: Db, owner: str, name: str = "P", **extra) -> str:
    return db.insert("crop_plans", owner_id=owner, name=name, season="year_round", available_land_acres=5, **extra)


def make_item(db: Db, plan: str, **extra) -> str:
    return db.insert("crop_plan_items", plan_id=plan, **{**ITEM, **extra})


def rejected(fn, *args, **kwargs):
    with pytest.raises(IntegrityError):
        fn(*args, **kwargs)


def test_plan_tables_exist(migrated_db):
    from sqlalchemy import create_engine, inspect

    assert {"crop_plans", "crop_plan_items"} <= set(inspect(create_engine(migrated_db)).get_table_names())


def test_a_valid_item_inserts(db):
    assert make_item(db, make_plan(db, db.user()))


@pytest.mark.parametrize(
    "field",
    [{"land": 0}, {"land": -1}],
)
def test_plan_land_must_be_positive(db, field):
    rejected(
        db.insert, "crop_plans", owner_id=db.user(), name="P", season="year_round", available_land_acres=field["land"]
    )


@pytest.mark.parametrize("column", ["budget_inr", "available_water_kl", "available_labour_person_days"])
@pytest.mark.parametrize("value", [0, -5])
def test_optional_limits_must_be_positive_when_present(db, column, value):
    rejected(make_plan, db, db.user(), **{column: value})


def test_optional_limits_may_be_null(db):
    assert make_plan(db, db.user(), budget_inr=None)


def test_plan_names_unique_per_owner_only(db):
    a, b = db.user("+919000000201"), db.user("+919000000202")
    make_plan(db, a, "Same")
    make_plan(db, b, "Same")
    rejected(make_plan, db, a, "Same")


@pytest.mark.parametrize(
    "bad",
    [
        {"yield_low_kg": 5, "yield_expected_kg": 2},  # low above expected
        {"yield_expected_kg": 9, "yield_high_kg": 3},  # expected above high
        {"yield_low_kg": 0, "yield_expected_kg": 0, "yield_high_kg": 0},  # expected must be > 0
        {"yield_low_kg": -1},
        {"price_low": 5, "price_expected": 2},
        {"price_expected": 9, "price_high": 3},
        {"price_expected": 0, "price_low": 0, "price_high": 1},
        {"area_acres": 0},
        {"duration_days": 0},
        {"harvest_window_days": 0},
        {"harvest_window_days": 366},
        {"batches": 0},
        {"batches": 13, "batch_interval_days": 5},
        {"seed_cost": -1},
        {"labour_wage": -1},
        {"fixed_cost": -1},
        {"cost_overrun_pct": -1},
        {"demand_quantity_kg": 0},
        {"water_kl_per_acre": -1},
        {"demand_level": "enormous"},
        {"declared_risk": "reckless"},
        {"estimate_basis": "vibes"},
    ],
)
def test_item_checks_reject_bad_rows(db, bad):
    rejected(make_item, db, make_plan(db, db.user()), **bad)


@pytest.mark.parametrize("interval", [None, 0, -3])
def test_staggered_item_needs_a_real_interval_even_when_it_is_null(db, interval):
    """Regression: `batches = 1 OR batch_interval_days >= 1` lets NULL through (a NULL check is not a failure)."""
    rejected(make_item, db, make_plan(db, db.user()), batches=2, batch_interval_days=interval)


def test_staggered_item_with_an_interval_is_accepted(db):
    assert make_item(db, make_plan(db, db.user()), batches=3, batch_interval_days=14)


def test_deleting_a_plan_cascades_to_its_items(db_container, db):
    plan = make_plan(db, db.user())
    make_item(db, plan)
    db.run("DELETE FROM crop_plans WHERE id = :i", i=plan)
    with db_container.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM crop_plan_items")) == 0


def test_a_crop_used_by_a_plan_item_cannot_be_deleted(db):
    crop = db.crop()
    make_item(db, make_plan(db, db.user()), crop_id=crop)
    rejected(db.run, "DELETE FROM crops WHERE id = :i", i=crop)


def test_a_farm_or_user_with_plans_cannot_be_deleted(db):
    owner = db.user()
    farm = db.farm(owner)
    make_plan(db, owner, farm_id=farm)
    rejected(db.run, "DELETE FROM farms WHERE id = :i", i=farm)
    rejected(db.run, "DELETE FROM users WHERE id = :i", i=owner)


def test_items_cannot_reference_a_missing_plan(db):
    rejected(make_item, db, uid())
