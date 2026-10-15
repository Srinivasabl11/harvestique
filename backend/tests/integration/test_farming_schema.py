"""Database-level guarantees. These bypass the API/services on purpose: the constraints must hold
even if a bug (or a future code path) lets bad data through."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration


def uid() -> str:
    return str(uuid.uuid4())


class Db:
    """Raw-SQL row factory returning ids."""

    def __init__(self, engine) -> None:
        self.engine = engine

    def run(self, sql: str, **params) -> None:
        with self.engine.begin() as conn:
            conn.execute(text(sql), params)

    def user(self, phone: str = "+919000000100") -> str:
        i = uid()
        self.run(
            "INSERT INTO users (id, phone, password_hash, full_name, role, is_active) "
            "VALUES (:i, :p, 'x', 'T', 'farmer', true)",
            i=i,
            p=phone,
        )
        return i

    def insert(self, table: str, **cols: object) -> str:
        """INSERT a row (ids generated here) and return its id. Table/column names are test-controlled."""
        row = {"id": uid(), **cols}
        names = ", ".join(row)
        values = ", ".join(f":{c}" for c in row)
        self.run(f"INSERT INTO {table} ({names}) VALUES ({values})", **row)  # noqa: S608
        return str(row["id"])

    def farm(self, owner: str, name: str = "F", area: float = 10, **extra: object) -> str:
        return self.insert("farms", owner_id=owner, name=name, total_area_acres=area, **extra)

    def plot(self, farm: str, name: str = "P", area: float = 2, **extra: object) -> str:
        return self.insert("farm_plots", farm_id=farm, name=name, area_acres=area, **extra)

    def crop(self, name: str = "C", days: int = 100) -> str:
        i = uid()
        self.run(
            "INSERT INTO crops (id, name, category, typical_duration_days) VALUES (:i, :n, 'vegetable', :d)",
            i=i,
            n=name,
            d=days,
        )
        return i

    def cycle(self, plot: str, crop: str, **extra: object) -> str:
        defaults: dict[str, object] = {"status": "planned", "area_acres": 1, "sowing_date": "2026-01-01"}
        return self.insert("crop_cycles", plot_id=plot, crop_id=crop, **{**defaults, **extra})


@pytest.fixture
def db(db_container) -> Db:
    return Db(db_container.engine)


def rejected(fn, *args, **kwargs) -> None:
    with pytest.raises(IntegrityError):
        fn(*args, **kwargs)


# -------------------------------------------------------------------- tables


def test_all_farming_tables_exist(migrated_db):
    from sqlalchemy import create_engine, inspect

    tables = set(inspect(create_engine(migrated_db)).get_table_names())
    assert {
        "farms",
        "farm_plots",
        "crops",
        "crop_cycles",
        "farm_expenses",
        "farm_activities",
        "crop_observations",
    } <= tables


# ------------------------------------------------------------------- CHECKs


@pytest.mark.parametrize("area", [0, -1])
def test_farm_area_must_be_positive(db, area):
    rejected(db.farm, db.user(), area=area)


@pytest.mark.parametrize(
    "coords",
    [{"latitude": 12.3}, {"longitude": 76.6}, {"latitude": 91, "longitude": 0}, {"latitude": 0, "longitude": -181}],
)
def test_farm_coordinates_must_be_paired_and_in_range(db, coords):
    rejected(db.farm, db.user(), **coords)


@pytest.mark.parametrize("area", [0, -0.5])
def test_plot_area_must_be_positive(db, area):
    rejected(db.plot, db.farm(db.user()), area=area)


def test_enum_columns_reject_unknown_values(db):
    farm = db.farm(db.user())
    rejected(db.plot, farm, soil_type="moon-dust")
    rejected(db.plot, farm, name="Q", irrigation_type="magic")


@pytest.mark.parametrize("days", [0, -3, 3651])
def test_crop_duration_range(db, days):
    rejected(db.crop, days=days)


def test_crop_cycle_checks(db):
    plot, crop = db.plot(db.farm(db.user())), db.crop()
    rejected(db.cycle, plot, crop, area_acres=0)
    rejected(db.cycle, plot, crop, expected_harvest_date="2026-01-01")  # not after sowing
    rejected(db.cycle, plot, crop, status="harvested", actual_harvest_date="2025-12-31")  # before sowing
    rejected(db.cycle, plot, crop, status="harvested")  # harvested needs a harvest date
    rejected(db.cycle, plot, crop, status="growing", actual_harvest_date="2026-02-01")  # date without harvested
    rejected(db.cycle, plot, crop, status="exploded")
    assert db.cycle(plot, crop, status="harvested", actual_harvest_date="2026-02-01")  # the valid shape works


def test_expense_amount_and_observation_percent(db):
    user = db.user()
    farm = db.farm(user)
    plot, crop = db.plot(farm), db.crop()
    cycle = db.cycle(plot, crop)
    for amount in (0, -5):
        rejected(
            db.run,
            "INSERT INTO farm_expenses (id, farm_id, category, amount, expense_date) "
            "VALUES (:i, :f, 'seed', :a, '2026-01-01')",
            i=uid(),
            f=farm,
            a=amount,
        )
    for percent in (-1, 100.5):
        rejected(
            db.run,
            "INSERT INTO crop_observations (id, crop_cycle_id, observed_on, health_status, estimated_loss_percent) "
            "VALUES (:i, :c, '2026-01-02', 'healthy', :p)",
            i=uid(),
            c=cycle,
            p=percent,
        )


# ------------------------------------------------------------------- UNIQUEs


def test_farm_name_unique_per_owner_only(db):
    a, b = db.user("+919000000101"), db.user("+919000000102")
    db.farm(a, name="Same")
    db.farm(b, name="Same")  # different owner: fine
    rejected(db.farm, a, name="Same")


def test_plot_name_unique_per_farm_only(db):
    owner = db.user()
    f1, f2 = db.farm(owner, name="One"), db.farm(owner, name="Two")
    db.plot(f1, name="North")
    db.plot(f2, name="North")
    rejected(db.plot, f1, name="North", area=1)


def test_crop_name_unique(db):
    db.crop("Tomato")
    rejected(db.crop, "Tomato")


# --------------------------------------------------------- RESTRICT deletes


def test_cannot_delete_a_farm_that_has_plots(db):
    farm = db.farm(db.user())
    db.plot(farm)
    rejected(db.run, "DELETE FROM farms WHERE id = :i", i=farm)


def test_cannot_delete_a_plot_that_has_cycles(db):
    plot, crop = db.plot(db.farm(db.user())), db.crop()
    db.cycle(plot, crop)
    rejected(db.run, "DELETE FROM farm_plots WHERE id = :i", i=plot)


def test_cannot_delete_a_crop_that_is_in_use(db):
    plot, crop = db.plot(db.farm(db.user())), db.crop()
    db.cycle(plot, crop)
    rejected(db.run, "DELETE FROM crops WHERE id = :i", i=crop)


def test_cannot_delete_a_user_who_owns_farms(db):
    owner = db.user()
    db.farm(owner)
    rejected(db.run, "DELETE FROM users WHERE id = :i", i=owner)


def test_cannot_delete_a_cycle_that_has_records(db):
    farm = db.farm(db.user())
    plot, crop = db.plot(farm), db.crop()
    cycle = db.cycle(plot, crop)
    db.insert("crop_observations", crop_cycle_id=cycle, observed_on="2026-01-02", health_status="healthy")
    rejected(db.run, "DELETE FROM crop_cycles WHERE id = :i", i=cycle)
