"""Shared fixtures. Unit/API tests never need a real database or network."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.container import Container, build_container
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="test",
        database_url="postgresql+psycopg://test:test@localhost:1/unused",
        weather_provider="fake",
        llm_provider="fake",
        notification_channel="fake",
        # The labelled development OTP mode: the API returns the code, so fixtures can finish sign-up and sign-in.
        # Limits are raised for the many accounts fixtures create; tests/integration/test_auth_otp.py tests them.
        sms_provider="dev_console",
        otp_max_sends_per_phone_per_hour=1000,
        otp_max_sends_per_client_per_hour=100000,
    )


@pytest.fixture
def container(settings: Settings) -> Container:
    c = build_container(settings)
    c.db_ping = lambda: True  # no real DB in unit tests
    return c


@pytest.fixture
def client(settings: Settings, container: Container) -> Iterator[TestClient]:
    app = create_app(settings=settings, container=container)
    with TestClient(app) as tc:
        yield tc


# ======================================================================
# Real-PostgreSQL fixtures (Phase 1+). Tests exercise the *actual* Alembic
# migrations; only TEST_DATABASE_URL is ever touched, and its database name
# must contain "test" so a dev/prod database can never be wiped by mistake.
# ======================================================================

import os  # noqa: E402
import uuid  # noqa: E402
from datetime import UTC, date, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.core.clock import FixedClock  # noqa: E402
from app.models.base import Base  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
STRONG_TEST_SECRET = "test-secret-" + "k" * 40


def alembic_config(db_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["dburl"] = db_url
    return cfg


def _ensure_database_exists(url: str) -> None:
    """Create the (empty) test database if it does not exist yet."""
    target = make_url(url)
    try:
        create_engine(url).connect().close()
        return
    except OperationalError:
        pass
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def db_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set (scripts/validate.* set it for you)")
    database = make_url(url).database or ""
    assert "test" in database, f"Refusing to run destructive tests on non-test database {database!r}"
    try:
        _ensure_database_exists(url)
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable at TEST_DATABASE_URL: {exc.__class__.__name__}")
    return url


@pytest.fixture(scope="session")
def migrated_db(db_url: str) -> str:
    """Schema built by the real migrations (also proves downgrade-to-base then upgrade works)."""
    cfg = alembic_config(db_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return db_url


@pytest.fixture
def db_settings(migrated_db: str) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="test",
        database_url=migrated_db,
        jwt_secret_key=STRONG_TEST_SECRET,  # type: ignore[arg-type]
        # Cheapest Argon2id parameters: keeps ~50 hashing tests fast; production defaults live in Settings.
        password_hash_time_cost=1,
        password_hash_memory_kib=8,
        password_hash_parallelism=1,
        weather_provider="fake",
        llm_provider="fake",
        notification_channel="fake",
        # The labelled development OTP mode: the API returns the code, so fixtures can finish sign-up and sign-in.
        # Limits are raised for the many accounts fixtures create; tests/integration/test_auth_otp.py tests them.
        sms_provider="dev_console",
        otp_max_sends_per_phone_per_hour=1000,
        otp_max_sends_per_client_per_hour=100000,
    )


@pytest.fixture
def db_container(db_settings: Settings) -> Iterator[Container]:
    container = build_container(db_settings)
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with container.engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield container
    container.shutdown()


@pytest.fixture
def db_client(db_settings: Settings, db_container: Container) -> Iterator[TestClient]:
    app = create_app(settings=db_settings, container=db_container)
    with TestClient(app) as tc:
        yield tc


@pytest.fixture
def fixed_clock(db_container: Container) -> FixedClock:
    """Swap the container clock for a controllable one (lockout / expiry tests)."""
    clock = FixedClock(datetime.now(UTC))
    db_container.clock = clock
    return clock


# ------------------------------------------------------------------ helpers

PASSWORD = "Harvest123"


def farmer_body(phone: str = "9876543210", **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "role": "farmer",
        "phone": phone,
        "password": PASSWORD,
        "full_name": "Ramesh Gowda",
        "profile": {"village": "Hunsur", "district": "Mysuru", "state": "Karnataka", "preferred_language": "kn"},
    }
    body.update(overrides)
    return body


def buyer_body(phone: str = "9123456780", **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "role": "buyer",
        "phone": phone,
        "password": PASSWORD,
        "full_name": "Anita Rao",
        "profile": {"business_name": "Rao Fresh Mart", "buyer_type": "retailer", "city": "Mysuru"},
    }
    body.update(overrides)
    return body


def bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def finish_otp(client: TestClient, challenge: dict, purpose: str) -> dict:
    """Step 2 of registration or login. The code is the development code from step 1, or - when a test installed
    a RecordingSms (a real-provider setup) - the code that provider delivered. Returns {user, tokens}."""
    code = challenge.get("dev_code")
    if code is None:
        from app.providers.sms.providers import RecordingSms

        sms = client.app.state.container.sms
        assert isinstance(sms, RecordingSms), challenge
        code = sms.sent[-1][1].split("code: ")[1][:6]
    r = client.post(f"/api/v1/auth/{purpose}/verify", json={"challenge_id": challenge["challenge_id"], "code": code})
    assert r.status_code in (200, 201), r.text
    return r.json()


def register_and_verify(client: TestClient, body: dict) -> dict:
    r = client.post("/api/v1/auth/register", json=body)
    assert r.status_code == 202, r.text
    return finish_otp(client, r.json(), "register")


def login_and_verify(client: TestClient, phone: str, password: str) -> dict:
    r = client.post("/api/v1/auth/login", json={"phone": phone, "password": password})
    assert r.status_code == 202, r.text
    return finish_otp(client, r.json(), "login")


@pytest.fixture
def register_farmer(db_client: TestClient):
    def _register(phone: str = "9876543210", **overrides: object) -> dict:
        return register_and_verify(db_client, farmer_body(phone, **overrides))

    return _register


@pytest.fixture
def register_buyer(db_client: TestClient):
    def _register(phone: str = "9123456780", **overrides: object) -> dict:
        return register_and_verify(db_client, buyer_body(phone, **overrides))

    return _register


@pytest.fixture
def make_admin(db_container: Container):
    """Create an admin the same way operators do (service layer / CLI), then log in via the API."""
    from app.composition import build_auth_service
    from app.schemas.auth import AdminCreateRequest

    def _make(phone: str = "+919000000001") -> uuid.UUID:
        with db_container.session_factory() as session:
            user = build_auth_service(session, db_container).create_admin(
                AdminCreateRequest(phone=phone, password="AdminPass123", full_name="Site Admin")
            )
        return user.id

    return _make


@pytest.fixture
def admin_tokens(db_client: TestClient, make_admin) -> dict:
    make_admin()
    return login_and_verify(db_client, "+919000000001", "AdminPass123")["tokens"]


# ======================================================================
# Phase 2: farming fixtures. Everything is created through the real HTTP API.
# ======================================================================

from dataclasses import dataclass  # noqa: E402
from datetime import timedelta  # noqa: E402


@dataclass(frozen=True)
class Actor:
    """An authenticated caller: auth headers + identity."""

    headers: dict[str, str]
    user_id: str
    role: str


def today() -> date:
    return datetime.now(UTC).date()


def days_from_today(n: int) -> str:
    """ISO date `n` days from today (negative = past), as JSON would carry it."""
    return (today() + timedelta(days=n)).isoformat()


@pytest.fixture
def farmer(register_farmer) -> Actor:
    data = register_farmer("9876543210")
    return Actor(bearer(data["tokens"]["access_token"]), data["user"]["id"], "farmer")


@pytest.fixture
def other_farmer(register_farmer) -> Actor:
    data = register_farmer("9876543299", full_name="Suresh Kumar")
    return Actor(bearer(data["tokens"]["access_token"]), data["user"]["id"], "farmer")


@pytest.fixture
def buyer(register_buyer) -> Actor:
    data = register_buyer()
    return Actor(bearer(data["tokens"]["access_token"]), data["user"]["id"], "buyer")


@pytest.fixture
def admin(db_client: TestClient, admin_tokens: dict) -> Actor:
    headers = bearer(admin_tokens["access_token"])
    me = db_client.get("/api/v1/auth/me", headers=headers).json()
    return Actor(headers, me["id"], "admin")


class Api:
    """Terse builders over the HTTP API; every builder asserts the expected 201."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def _post(self, actor: Actor, url: str, body: dict) -> dict:
        r = self.client.post(f"/api/v1{url}", json=body, headers=actor.headers)
        assert r.status_code == 201, f"POST {url} -> {r.status_code}: {r.text}"
        return r.json()

    def crop(self, admin_actor: Actor, **overrides: object) -> dict:
        body = {"name": "Tomato", "category": "vegetable", "typical_duration_days": 100, **overrides}
        return self._post(admin_actor, "/crops", body)

    def farm(self, actor: Actor, **overrides: object) -> dict:
        body = {"name": "Green Acres", "total_area_acres": 10, **overrides}
        return self._post(actor, "/farms", body)

    def plot(self, actor: Actor, farm_id: str, **overrides: object) -> dict:
        body = {"name": "North Field", "area_acres": 4, **overrides}
        return self._post(actor, f"/farms/{farm_id}/plots", body)

    def cycle(self, actor: Actor, plot_id: str, crop_id: str, **overrides: object) -> dict:
        body = {"crop_id": crop_id, "sowing_date": days_from_today(-10), "expected_harvest_date": days_from_today(80)}
        body.update(overrides)
        return self._post(actor, f"/plots/{plot_id}/crop-cycles", body)

    def expense(self, actor: Actor, farm_id: str, **overrides: object) -> dict:
        body = {"category": "seed", "amount": 1500.5, "expense_date": days_from_today(-5), **overrides}
        return self._post(actor, f"/farms/{farm_id}/expenses", body)

    def activity(self, actor: Actor, farm_id: str, **overrides: object) -> dict:
        body = {"activity_type": "irrigation", "activity_date": days_from_today(-3), **overrides}
        return self._post(actor, f"/farms/{farm_id}/activities", body)

    def observation(self, actor: Actor, cycle_id: str, **overrides: object) -> dict:
        body = {"observed_on": days_from_today(-2), "health_status": "healthy", **overrides}
        return self._post(actor, f"/crop-cycles/{cycle_id}/observations", body)


@pytest.fixture
def api(db_client: TestClient) -> Api:
    return Api(db_client)


@pytest.fixture
def crop(api: Api, admin: Actor) -> dict:
    return api.crop(admin)


@pytest.fixture
def farm(api: Api, farmer: Actor) -> dict:
    return api.farm(farmer)


@pytest.fixture
def plot(api: Api, farmer: Actor, farm: dict) -> dict:
    return api.plot(farmer, farm["id"])


@pytest.fixture
def cycle(api: Api, farmer: Actor, plot: dict, crop: dict) -> dict:
    return api.cycle(farmer, plot["id"], crop["id"])


# ======================================================================
# Phase 4: intelligence fixtures
# ======================================================================

from app.core.errors import ProviderUnavailableError  # noqa: E402


class FailingWeather:
    """A weather provider whose every call fails (network down, Open-Meteo outage...)."""

    name = "failing"
    calls = 0

    def get_daily_forecast(self, latitude, longitude, days):  # type: ignore[no-untyped-def]
        FailingWeather.calls += 1
        raise ProviderUnavailableError("simulated outage")

    def get_daily_history(self, latitude, longitude, start, end):  # type: ignore[no-untyped-def]
        FailingWeather.calls += 1
        raise ProviderUnavailableError("simulated outage")


@pytest.fixture
def geo_farm(api: Api, farmer: Actor) -> dict:
    return api.farm(farmer, name="Mysuru Farm", latitude=12.2958, longitude=76.6394, total_area_acres=10)


@pytest.fixture
def ref_crop(api: Api, admin: Actor) -> dict:
    return api.crop(
        admin,
        name="Tomato",
        typical_duration_days=100,
        reference_yield_kg_per_acre=10000,
        reference_yield_cv=0.3,
        water_need_mm=500,
    )


@pytest.fixture
def geo_plot(api: Api, farmer: Actor, geo_farm: dict) -> dict:
    return api.plot(farmer, geo_farm["id"], area_acres=8, irrigation_type="drip")


@pytest.fixture
def growing(api: Api, farmer: Actor, geo_plot: dict, ref_crop: dict) -> dict:
    return api.cycle(
        farmer,
        geo_plot["id"],
        ref_crop["id"],
        status="growing",
        area_acres=2,
        sowing_date=days_from_today(-40),
        expected_harvest_date=days_from_today(60),
    )


def predict(client: TestClient, actor: Actor, cycle_id: str, body: dict | None = None, expect: int = 201) -> dict:
    r = client.post(f"/api/v1/crop-cycles/{cycle_id}/predictions", headers=actor.headers, json=body or {})
    assert r.status_code == expect, r.text
    return r.json()


def harvest(client: TestClient, actor: Actor, cycle_id: str, quantity: float, days_ago: int = 1) -> dict:
    r = client.patch(
        f"/api/v1/crop-cycles/{cycle_id}",
        headers=actor.headers,
        json={"status": "harvested", "actual_harvest_date": days_from_today(-days_ago)},
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/crop-cycles/{cycle_id}/harvest-actual", headers=actor.headers, json={"quantity_kg": quantity}
    )
    assert r.status_code == 201, r.text
    return r.json()


def relogin(client: TestClient, phone: str = "9876543210") -> dict[str, str]:
    """Fresh auth headers after moving a FixedClock forward (old access tokens correctly expire)."""
    return bearer(login_and_verify(client, phone, PASSWORD)["tokens"]["access_token"])


# ======================================================================
# Phase 5: pooling fixtures
# ======================================================================

from dataclasses import replace as _replace  # noqa: E402
from decimal import Decimal as _D  # noqa: E402

from app.core.enums import PredictionStatus as _PS  # noqa: E402
from app.domain.prediction.engine import RuleBasedPredictor  # noqa: E402
from app.domain.prediction.models import Quantiles  # noqa: E402


class FixedPredictor:
    """Test PredictionProvider: the real rule model, but with an exact quantity per cycle (keyed by area)."""

    name, version = "fixed-test", "1"

    def __init__(self) -> None:
        self.quantities: dict[_D, _D] = {}
        self._real = RuleBasedPredictor()

    def predict(self, inp):  # type: ignore[no-untyped-def]
        r = self._real.predict(inp)
        q = self.quantities.get(inp.cycle.area_acres)
        if q is None:
            return r
        per = (q / inp.cycle.area_acres).quantize(_D("0.001"))
        return _replace(r, status=_PS.OK, quantity_kg=Quantiles(q, q, q), yield_per_acre_kg=Quantiles(per, per, per))


class PoolWorld:
    """Farms A..E (500/350/450/300/400 kg) opted into pooling, plus helpers to add farms and change predictions."""

    def __init__(self, client: TestClient, api: Api, farmer: Actor, crop: dict, predictor: FixedPredictor) -> None:
        self.client, self.api, self.farmer, self.crop, self.predictor = client, api, farmer, crop, predictor
        self.farms: dict[str, dict] = {}
        self._area = _D("1.0")

    def add_farm(
        self, name: str, kg: float, *, opt_in: bool = True, grade: str = "B", lat: float = 12.30, lon: float = 76.64
    ) -> dict:
        self._area += _D("0.1")
        farm = self.api.farm(self.farmer, name=f"Farm {name}", latitude=lat, longitude=lon, total_area_acres=5)
        plot = self.api.plot(self.farmer, farm["id"], area_acres=4)
        cycle = self.api.cycle(
            self.farmer,
            plot["id"],
            self.crop["id"],
            status="growing",
            area_acres=float(self._area),
            sowing_date=days_from_today(-40),
            expected_harvest_date=days_from_today(60),
        )
        self.predictor.quantities[self._area] = _D(str(kg))
        predict(self.client, self.farmer, cycle["id"])
        lot = next(
            x
            for x in self.client.get(
                "/api/v1/inventory/lots", headers=self.farmer.headers, params={"limit": 100}
            ).json()["items"]
            if x["crop_cycle_id"] == cycle["id"]
        )
        r = self.client.patch(
            f"/api/v1/inventory/lots/{lot['id']}",
            headers=self.farmer.headers,
            json={"pool_eligible": opt_in, "expected_grade": grade},
        )
        assert r.status_code == 200, r.text
        self.farms[name] = {"cycle_id": cycle["id"], "lot_id": lot["id"], "area": self._area}
        return self.farms[name]

    def change(self, name: str, kg: float) -> dict:
        """A new prediction version for this farm (triggers automatic shortage detection / reallocation)."""
        self.predictor.quantities[self.farms[name]["area"]] = _D(str(kg))
        return predict(self.client, self.farmer, self.farms[name]["cycle_id"])

    def lot(self, name: str) -> dict:
        return self.client.get(
            f"/api/v1/inventory/lots/{self.farms[name]['lot_id']}", headers=self.farmer.headers
        ).json()


@pytest.fixture
def pool_world(db_client, db_container, api, farmer, ref_crop) -> PoolWorld:
    predictor = FixedPredictor()
    db_container.predictor = predictor
    world = PoolWorld(db_client, api, farmer, ref_crop, predictor)
    for name, kg in (("A", 500), ("B", 350), ("C", 450), ("D", 300), ("E", 400)):
        world.add_farm(name, kg)
    return world


def make_demand(client: TestClient, buyer: Actor, crop_id: str, qty: float, **kw: object) -> dict:
    body = {
        "crop_id": crop_id,
        "quantity_kg": qty,
        "window_start": days_from_today(30),
        "window_end": days_from_today(150),
        **kw,
    }
    r = client.post("/api/v1/buyer-demands", headers=buyer.headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def make_pool(
    client: TestClient, buyer: Actor, demand_id: str, *, algorithm: str = "greedy", key: str | None = None, **kw: object
) -> dict:
    headers = {**buyer.headers, **({"Idempotency-Key": key} if key else {})}
    r = client.post(
        f"/api/v1/buyer-demands/{demand_id}/pool",
        headers=headers,
        json={"algorithm": algorithm, "max_pool_risk": 100, **kw},
    )
    assert r.status_code == 201, r.text
    return r.json()
