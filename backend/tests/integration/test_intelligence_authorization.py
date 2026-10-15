"""Authorization matrix for every intelligence/inventory endpoint (same scheme as earlier phases)."""

from __future__ import annotations

import re

import pytest

from app.core.config import Settings
from app.main import create_app
from tests.conftest import harvest, predict
from tests.integration.test_farming_authorization import Route, sweep

pytestmark = pytest.mark.integration

ROUTES = [
    Route("GET", "/farms/{farm_id}/weather"),
    Route("GET", "/farms/{farm_id}/weather/now"),
    Route("GET", "/farms/{farm_id}/risk"),
    Route("POST", "/crop-cycles/{cycle_id}/predictions", lambda i: {}),
    Route("GET", "/crop-cycles/{cycle_id}/predictions"),
    Route("GET", "/predictions/{prediction_id}"),
    Route("POST", "/crop-cycles/{cycle_id}/harvest-actual", lambda i: {"quantity_kg": 1}),
    Route("PATCH", "/crop-cycles/{cycle_id}/harvest-actual", lambda i: {"quantity_kg": 1, "reason": "matrix"}),
    Route("GET", "/crop-cycles/{cycle_id}/feedback"),
    Route("GET", "/inventory/lots", collection=True),
    Route("GET", "/inventory/lots/{lot_id}"),
    Route("POST", "/inventory/lots/{lot_id}/reservations", lambda i: {"quantity_kg": 1, "booking_key": "matrix"}),
    Route("POST", "/inventory/reservations/{reservation_id}/release"),
    Route("POST", "/inventory/reservations/{reservation_id}/fulfil"),
    Route(
        "POST",
        "/crop-plans/{plan_id}/items/from-prediction",
        lambda i: {"prediction_id": i["prediction_id"], "price_per_kg": {"low": 1, "expected": 2, "high": 3}},
    ),
]
FARMER_ONLY = [r for r in ROUTES]
RESOURCE = [r for r in ROUTES if not r.collection]
SPECIAL = [("GET", "/calibration"), ("POST", "/admin/calibration/recompute")]


@pytest.fixture
def world(db_client, farmer, growing, geo_farm):
    p = predict(db_client, farmer, growing["id"])
    lot = db_client.get("/api/v1/inventory/lots", headers=farmer.headers).json()["items"][0]
    res = db_client.post(
        f"/api/v1/inventory/lots/{lot['id']}/reservations",
        headers=farmer.headers,
        json={"quantity_kg": 1, "booking_key": "w"},
    ).json()
    plan = db_client.post(
        "/api/v1/crop-plans", headers=farmer.headers, json={"name": "W", "available_land_acres": 5}
    ).json()
    return {
        "farm_id": geo_farm["id"],
        "cycle_id": growing["id"],
        "prediction_id": p["id"],
        "lot_id": lot["id"],
        "reservation_id": res["id"],
        "plan_id": plan["id"],
    }


def test_anonymous_everywhere(db_client, world):
    assert sweep(db_client, ROUTES, world, None, 401, "not_authenticated") == []


@pytest.mark.parametrize("role", ["buyer", "admin"])
def test_wrong_roles_everywhere(db_client, world, request, role):
    assert sweep(db_client, FARMER_ONLY, world, request.getfixturevalue(role).headers, 403, "permission_denied") == []


def test_other_farmer_gets_404(db_client, world, other_farmer):
    problems = sweep(
        db_client,
        [r for r in RESOURCE if "from-prediction" not in r.path],
        world,
        other_farmer.headers,
        404,
        "not_found",
    )
    assert problems == []
    # the plan belongs to `farmer`, so another farmer gets 404 for the plan before the prediction is checked
    plan_route = next(r for r in RESOURCE if "from-prediction" in r.path)
    assert sweep(db_client, [plan_route], world, other_farmer.headers, 404, "not_found") == []


def test_owner_reads(db_client, world, farmer):
    assert sweep(db_client, [r for r in ROUTES if r.method == "GET"], world, farmer.headers, 200, None) == []


def test_calibration_access(db_client, world, farmer, buyer, admin):
    assert db_client.get("/api/v1/calibration").status_code == 401
    for actor in (farmer, buyer, admin):  # aggregate statistics only, no farm data
        assert db_client.get("/api/v1/calibration", headers=actor.headers).status_code == 200
    assert db_client.post("/api/v1/admin/calibration/recompute").status_code == 401
    for actor in (farmer, buyer):
        assert db_client.post("/api/v1/admin/calibration/recompute", headers=actor.headers).status_code == 403


def test_a_farmer_cannot_record_a_harvest_on_someone_elses_cycle(db_client, world, farmer, other_farmer, growing):
    harvest(db_client, farmer, growing["id"], 100)
    r = db_client.post(
        f"/api/v1/crop-cycles/{growing['id']}/harvest-actual", headers=other_farmer.headers, json={"quantity_kg": 1}
    )
    assert r.status_code == 404


def test_every_intelligence_route_is_covered(db_container):
    prefixes = ("/predictions", "/inventory", "/calibration", "/admin/calibration")
    paths = create_app(settings=Settings(_env_file=None), container=db_container).openapi()["paths"]  # type: ignore[call-arg]
    actual = {
        (m.upper(), re.sub(r"^/api/v1", "", p))
        for p, ops in paths.items()
        for m in ops
        if m in {"get", "post", "patch", "delete"}
        and (
            re.sub(r"^/api/v1", "", p).startswith(prefixes)
            or re.search(r"/(weather|weather/now|risk|predictions|harvest-actual|feedback|from-prediction)$", p)
        )
    }
    from tests.integration.test_pooling_authorization import ROUTES as POOLING_ROUTES

    covered = {(r.method, r.path) for r in ROUTES} | set(SPECIAL) | {(r.method, r.path) for r in POOLING_ROUTES}
    assert actual <= covered, f"missing: {sorted(actual - covered)}"
    assert {(r.method, r.path) for r in ROUTES} <= actual, "stale rows"
