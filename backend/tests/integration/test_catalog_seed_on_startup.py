"""A fresh install gets the standard crop catalog at startup, so farmers can add crops to plots."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.cli.seed_crops import seed_if_empty, seed_payloads
from app.core.config import Settings
from app.core.container import build_container
from app.main import create_app
from tests.conftest import register_and_verify

pytestmark = pytest.mark.integration
N = len(seed_payloads())


def crop_count(container) -> int:
    with container.engine.connect() as conn:
        return int(conn.scalar(text("SELECT count(*) FROM crops")))


def test_empty_catalog_is_seeded_once(db_container):
    assert crop_count(db_container) == 0
    assert seed_if_empty(db_container) == N >= 70
    assert crop_count(db_container) == N
    assert seed_if_empty(db_container) == 0  # idempotent
    with db_container.engine.connect() as conn:
        refs = conn.scalar(text("SELECT count(*) FROM crops WHERE reference_yield_kg_per_acre IS NOT NULL"))
    assert refs and refs > 0


def test_a_non_empty_catalog_is_never_touched(db_client, admin, api):
    api.crop(admin, name="Only Crop")
    container = db_client.app.state.container
    assert seed_if_empty(container) == 0 and crop_count(container) == 1


def test_server_startup_seeds_an_empty_catalog_and_farmers_see_crops(
    db_settings, db_container
):  # db_container: clean tables
    settings = db_settings.model_copy(update={"app_env": "development"})
    container = build_container(settings)
    with TestClient(create_app(settings=settings, container=container)) as client:
        assert crop_count(container) == N
        reg = register_and_verify(
            client,
            {
                "role": "farmer",
                "phone": "9811177777",
                "password": "Harvest123",
                "full_name": "Farmer One",
                "profile": {},
            },
        )
        token = reg["tokens"]["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        crops = client.get("/api/v1/crops", params={"limit": 100}, headers=auth).json()
        names = {
            c["name"]
            for offset in range(0, crops["total"], 100)
            for c in client.get("/api/v1/crops", params={"limit": 100, "offset": offset}, headers=auth).json()["items"]
        }
        assert crops["total"] == N and {"Tomato", "Ragi", "Onion"} <= names


def test_startup_seeding_is_skipped_in_tests_and_when_disabled(db_settings, db_container):
    for update in ({}, {"app_env": "development", "seed_crop_catalog_on_startup": False}):
        settings = db_settings.model_copy(update=update)
        container = build_container(settings)
        with TestClient(create_app(settings=settings, container=container)):
            assert crop_count(container) == 0


def test_startup_survives_an_unreachable_database():
    settings = Settings(_env_file=None, app_env="development", database_url="postgresql+psycopg://x:y@localhost:1/none")  # type: ignore[call-arg]
    with TestClient(create_app(settings=settings)) as client:
        assert client.get("/api/v1/health/live").status_code == 200
