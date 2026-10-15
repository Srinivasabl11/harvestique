"""Authorization matrix for every farm-management endpoint.

For each route: anonymous -> 401, buyer -> 403, admin -> 403, a *different farmer* -> 404
(existence is not revealed), the owner -> allowed. A meta-test fails if a farming route exists
that is missing from the matrix, so new endpoints cannot silently skip authorization tests.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from app.core.config import Settings
from app.main import create_app
from tests.conftest import bearer, days_from_today

pytestmark = pytest.mark.integration

Ids = dict[str, str]
Body = Callable[[Ids], dict[str, Any]] | None


@dataclass(frozen=True)
class Route:
    method: str
    path: str  # OpenAPI-style template, e.g. /farms/{farm_id}/plots
    body: Body = None
    collection: bool = False  # not tied to an existing resource (no "someone else's" 404)

    @property
    def id(self) -> str:
        return f"{self.method} {self.path}"


ROUTES = [
    Route("GET", "/farms", collection=True),
    Route("POST", "/farms", lambda i: {"name": "Matrix Farm", "total_area_acres": 1}, collection=True),
    Route("GET", "/farms/{farm_id}"),
    Route("PATCH", "/farms/{farm_id}", lambda i: {"notes": "x"}),
    Route("DELETE", "/farms/{farm_id}"),
    Route("POST", "/farms/{farm_id}/plots", lambda i: {"name": "Matrix Plot", "area_acres": 1}),
    Route("GET", "/farms/{farm_id}/plots"),
    Route("GET", "/plots/{plot_id}"),
    Route("PATCH", "/plots/{plot_id}", lambda i: {"notes": "x"}),
    Route("DELETE", "/plots/{plot_id}"),
    Route(
        "POST", "/plots/{plot_id}/crop-cycles", lambda i: {"crop_id": i["crop_id"], "sowing_date": days_from_today(-1)}
    ),
    Route("GET", "/plots/{plot_id}/crop-cycles"),
    Route("GET", "/farms/{farm_id}/crop-cycles"),
    Route("GET", "/crop-cycles/{cycle_id}"),
    Route("PATCH", "/crop-cycles/{cycle_id}", lambda i: {"notes": "x"}),
    Route("DELETE", "/crop-cycles/{cycle_id}"),
    Route(
        "POST",
        "/farms/{farm_id}/expenses",
        lambda i: {"category": "seed", "amount": 5, "expense_date": days_from_today(-1)},
    ),
    Route("GET", "/farms/{farm_id}/expenses"),
    Route("GET", "/expenses/{expense_id}"),
    Route("PATCH", "/expenses/{expense_id}", lambda i: {"description": "x"}),
    Route("DELETE", "/expenses/{expense_id}"),
    Route(
        "POST",
        "/farms/{farm_id}/activities",
        lambda i: {"activity_type": "weeding", "activity_date": days_from_today(-1)},
    ),
    Route("GET", "/farms/{farm_id}/activities"),
    Route("GET", "/activities/{activity_id}"),
    Route("PATCH", "/activities/{activity_id}", lambda i: {"description": "x"}),
    Route("DELETE", "/activities/{activity_id}"),
    Route(
        "POST",
        "/crop-cycles/{cycle_id}/observations",
        lambda i: {"observed_on": days_from_today(-1), "health_status": "healthy"},
    ),
    Route("GET", "/crop-cycles/{cycle_id}/observations"),
    Route("GET", "/observations/{observation_id}"),
    Route("PATCH", "/observations/{observation_id}", lambda i: {"notes": "x"}),
    Route("DELETE", "/observations/{observation_id}"),
]
OWNER_READS = [r for r in ROUTES if r.method == "GET"]
RESOURCE_ROUTES = [r for r in ROUTES if not r.collection]


@pytest.fixture
def world(api, farmer, admin) -> Ids:
    """One of everything, owned by `farmer`."""
    crop = api.crop(admin)
    farm = api.farm(farmer)
    plot = api.plot(farmer, farm["id"])
    cycle = api.cycle(farmer, plot["id"], crop["id"])
    return {
        "crop_id": crop["id"],
        "farm_id": farm["id"],
        "plot_id": plot["id"],
        "cycle_id": cycle["id"],
        "expense_id": api.expense(farmer, farm["id"])["id"],
        "activity_id": api.activity(farmer, farm["id"])["id"],
        "observation_id": api.observation(farmer, cycle["id"])["id"],
    }


def call(client, route: Route, ids: Ids, headers: dict[str, str] | None):
    url = "/api/v1" + route.path.format(**ids)
    body = route.body(ids) if route.body else None
    return client.request(route.method, url, json=body, headers=headers or {})


def sweep(
    client, routes: list[Route], ids: Ids, headers: dict[str, str] | None, expect: int, error_code: str | None
) -> list[str]:
    """Call every route and return a description of each that did not answer as expected.

    None of these calls may change state (they are all denied before reaching a service), so one
    shared `world` is enough and the matrix stays fast while still naming the exact failing route.
    """
    problems: list[str] = []
    for route in routes:
        r = call(client, route, ids, headers)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
        got = body.get("error", {}).get("code") if isinstance(body, dict) else None  # list bodies carry no error
        if r.status_code != expect or (error_code is not None and got != error_code):
            problems.append(f"{route.id}: expected {expect}/{error_code}, got {r.status_code}/{got}")
    return problems


def test_anonymous_is_unauthorized_everywhere(db_client, world):
    assert sweep(db_client, ROUTES, world, None, 401, "not_authenticated") == []


def test_buyer_is_forbidden_everywhere(db_client, world, buyer):
    assert sweep(db_client, ROUTES, world, buyer.headers, 403, "permission_denied") == []


def test_admin_is_forbidden_everywhere(db_client, world, admin):
    """Roles are strict: an admin gets no implicit farmer access."""
    assert sweep(db_client, ROUTES, world, admin.headers, 403, "permission_denied") == []


def test_another_farmer_gets_404_not_403_on_every_resource_route(db_client, world, other_farmer):
    assert sweep(db_client, RESOURCE_ROUTES, world, other_farmer.headers, 404, "not_found") == []


def test_owner_can_read_everything(db_client, world, farmer):
    assert sweep(db_client, OWNER_READS, world, farmer.headers, 200, None) == []
    # ...and nothing above changed or removed the owner's data
    assert db_client.get(f"/api/v1/farms/{world['farm_id']}", headers=farmer.headers).json()["name"] == "Green Acres"


def test_collection_endpoints_only_expose_my_own_data(db_client, api, world, other_farmer):
    mine = api.farm(other_farmer, name="Mine")
    listing = db_client.get("/api/v1/farms", headers=other_farmer.headers).json()
    assert [f["id"] for f in listing["items"]] == [mine["id"]]
    for kind in ("expenses", "activities", "crop-cycles"):
        assert (
            db_client.get(f"/api/v1/farms/{world['farm_id']}/{kind}", headers=other_farmer.headers).status_code == 404
        )


def test_every_farming_route_is_in_the_matrix(db_container, db_settings):
    prefixes = ("/farms", "/plots", "/crop-cycles", "/expenses", "/activities", "/observations")
    paths = create_app(settings=Settings(_env_file=None), container=db_container).openapi()["paths"]  # type: ignore[call-arg]
    actual = {
        (method.upper(), re.sub(r"^/api/v1", "", path))
        for path, ops in paths.items()
        for method in ops
        if method in {"get", "post", "patch", "put", "delete"} and re.sub(r"^/api/v1", "", path).startswith(prefixes)
    }
    from tests.integration.test_grading_api import AUTHZ_ROUTES as GRADING_ROUTES
    from tests.integration.test_intelligence_authorization import ROUTES as INTELLIGENCE_ROUTES

    # Later phases add routes under the same prefixes (e.g. /farms/{id}/weather); they are covered by their
    # own matrix. The guarantee: every route here is covered by SOME matrix, and this matrix has no stale rows.
    covered = {(r.method, r.path) for r in ROUTES + INTELLIGENCE_ROUTES + GRADING_ROUTES}
    assert actual <= covered, f"missing from every matrix: {sorted(actual - covered)}"
    assert {(r.method, r.path) for r in ROUTES} <= actual, "stale rows in the farming matrix"


# ------------------------------------------------- sessions apply here too


def test_logged_out_farmer_loses_access_immediately(db_client, farmer, farm):
    assert db_client.get("/api/v1/farms", headers=farmer.headers).status_code == 200
    assert db_client.post("/api/v1/auth/logout", headers=farmer.headers).status_code == 204
    r = db_client.get(f"/api/v1/farms/{farm['id']}", headers=farmer.headers)
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_revoked"


def test_disabled_farmer_is_blocked(db_client, db_container, farmer, farm):
    from sqlalchemy import text

    with db_container.engine.begin() as conn:
        conn.execute(text("UPDATE users SET is_active = false WHERE role = 'farmer'"))
    assert db_client.get("/api/v1/farms", headers=farmer.headers).status_code == 403


def test_a_role_change_to_buyer_revokes_farm_access_at_once(db_client, db_container, farmer, farm):
    from sqlalchemy import text

    with db_container.engine.begin() as conn:
        conn.execute(text("UPDATE users SET role = 'buyer' WHERE id = :id"), {"id": farmer.user_id})
    assert db_client.get(f"/api/v1/farms/{farm['id']}", headers=farmer.headers).status_code == 403


def test_bogus_token_is_rejected_on_farming_routes(db_client):
    assert db_client.get("/api/v1/farms", headers=bearer("not.a.jwt")).status_code == 401
