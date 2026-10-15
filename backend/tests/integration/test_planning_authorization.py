"""Authorization matrix for every planning endpoint (same scheme as test_farming_authorization)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from app.core.config import Settings
from app.main import create_app
from tests.planning_factory import calc_body, candidate_body, item_body

pytestmark = pytest.mark.integration

Ids = dict[str, str]


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    body: Callable[[Ids], Any] | None = None
    params: Callable[[Ids], Any] | None = None
    collection: bool = False  # not tied to an existing resource: no "someone else's" 404

    @property
    def id(self) -> str:
        return f"{self.method} {self.path}"


ROUTES = [
    Route("POST", "/planning/calculate", lambda i: calc_body(), collection=True),
    Route(
        "POST",
        "/planning/suggest-allocation",
        lambda i: {"available_land_acres": 5, "candidates": [candidate_body()]},
        collection=True,
    ),
    Route("POST", "/crop-plans", lambda i: {"name": "Matrix plan", "available_land_acres": 1}, collection=True),
    Route("GET", "/crop-plans", collection=True),
    Route("GET", "/crop-plans/compare", params=lambda i: [("plan_id", i["plan_id"]), ("plan_id", i["plan2_id"])]),
    Route("GET", "/crop-plans/{plan_id}"),
    Route("PATCH", "/crop-plans/{plan_id}", lambda i: {"description": "x"}),
    Route("DELETE", "/crop-plans/{plan_id}"),
    Route("POST", "/crop-plans/{plan_id}/duplicate", lambda i: {"name": "Matrix copy"}),
    Route("GET", "/crop-plans/{plan_id}/evaluation"),
    Route("POST", "/crop-plans/{plan_id}/items", lambda i: item_body()),
    Route("GET", "/crop-plan-items/{item_id}"),
    Route("PATCH", "/crop-plan-items/{item_id}", lambda i: {"notes": "x"}),
    Route("DELETE", "/crop-plan-items/{item_id}"),
]
RESOURCE_ROUTES = [r for r in ROUTES if not r.collection]
OWNER_READS = [r for r in ROUTES if r.method == "GET"]


@pytest.fixture
def world(db_client, farmer) -> Ids:
    def create(name):
        r = db_client.post(
            "/api/v1/crop-plans",
            headers=farmer.headers,
            json={"name": name, "available_land_acres": 5, "items": [item_body()]},
        )
        assert r.status_code == 201, r.text
        return r.json()

    one, two = create("Plan one"), create("Plan two")
    return {"plan_id": one["id"], "plan2_id": two["id"], "item_id": one["items"][0]["id"]}


def sweep(client, routes, ids, headers, expect, error_code) -> list[str]:
    problems = []
    for route in routes:
        r = client.request(
            route.method,
            "/api/v1" + route.path.format(**ids),
            json=route.body(ids) if route.body else None,
            params=route.params(ids) if route.params else None,
            headers=headers or {},
        )
        got = r.json().get("error", {}).get("code") if "json" in r.headers.get("content-type", "") else None
        if r.status_code != expect or (error_code is not None and got != error_code):
            problems.append(f"{route.id}: expected {expect}/{error_code}, got {r.status_code}/{got}")
    return problems


def test_anonymous_is_unauthorized_everywhere(db_client, world):
    assert sweep(db_client, ROUTES, world, None, 401, "not_authenticated") == []


def test_buyer_is_forbidden_everywhere(db_client, world, buyer):
    assert sweep(db_client, ROUTES, world, buyer.headers, 403, "permission_denied") == []


def test_admin_is_forbidden_everywhere(db_client, world, admin):
    assert sweep(db_client, ROUTES, world, admin.headers, 403, "permission_denied") == []


def test_another_farmer_gets_404_on_every_resource_route(db_client, world, other_farmer):
    assert sweep(db_client, RESOURCE_ROUTES, world, other_farmer.headers, 404, "not_found") == []


def test_owner_can_read_everything(db_client, world, farmer):
    assert sweep(db_client, OWNER_READS, world, farmer.headers, 200, None) == []
    assert (
        db_client.get(f"/api/v1/crop-plans/{world['plan_id']}", headers=farmer.headers).json()["name"] == "Plan one"
    )  # nothing above changed it


def test_plan_lists_only_ever_show_my_own_plans(db_client, world, other_farmer):
    listing = db_client.get("/api/v1/crop-plans", headers=other_farmer.headers).json()
    assert listing["total"] == 0 and listing["items"] == []


def test_every_planning_route_is_in_the_matrix(db_container):
    prefixes = ("/planning", "/crop-plans", "/crop-plan-items")
    paths = create_app(settings=Settings(_env_file=None), container=db_container).openapi()["paths"]  # type: ignore[call-arg]
    actual = {
        (method.upper(), re.sub(r"^/api/v1", "", path))
        for path, ops in paths.items()
        for method in ops
        if method in {"get", "post", "patch", "put", "delete"} and re.sub(r"^/api/v1", "", path).startswith(prefixes)
    }
    from tests.integration.test_intelligence_authorization import ROUTES as INTELLIGENCE_ROUTES

    own = {(r.method, r.path) for r in ROUTES}
    covered = own | {(r.method, r.path) for r in INTELLIGENCE_ROUTES}  # e.g. .../items/from-prediction
    assert actual <= covered, f"missing from every matrix: {sorted(actual - covered)}"
    assert own <= actual, f"stale rows: {sorted(own - actual)}"


def test_logged_out_farmer_loses_planning_access_immediately(db_client, farmer, world):
    assert db_client.post("/api/v1/auth/logout", headers=farmer.headers).status_code == 204
    r = db_client.get(f"/api/v1/crop-plans/{world['plan_id']}", headers=farmer.headers)
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_revoked"
