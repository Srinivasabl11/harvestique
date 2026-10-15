"""Authorization matrix for harvest pooling (buyers own demands/pools; admins oversee pools; farmers opt lots in)."""

from __future__ import annotations

import re

import pytest

from app.core.config import Settings
from app.main import create_app
from tests.conftest import make_demand, make_pool
from tests.integration.test_farming_authorization import Route, sweep

pytestmark = pytest.mark.integration
KEY = {"Idempotency-Key": "matrix"}

BUYER_ROUTES = [
    Route(
        "POST",
        "/buyer-demands",
        lambda i: {
            "crop_id": i["crop_id"],
            "quantity_kg": 10,
            "window_start": "2027-01-01",
            "window_end": "2027-02-01",
        },
        collection=True,
    ),
    Route("GET", "/buyer-demands", collection=True),
    Route("GET", "/buyer-demands/{demand_id}"),
    Route("GET", "/buyer-demands/{demand_id}/matches"),
    Route("POST", "/buyer-demands/{demand_id}/pool", lambda i: {}),
    Route("POST", "/buyer-demands/{demand_id}/cancel"),
]
POOL_ROUTES = [
    Route("GET", "/pools", collection=True),
    Route("GET", "/pools/{pool_id}"),
    Route("POST", "/pools/{pool_id}/rebalance"),
    Route("GET", "/pools/{pool_id}/events"),
    Route("GET", "/pools/{pool_id}/ledger"),
]
FARMER_ROUTES = [Route("PATCH", "/inventory/lots/{lot_id}", lambda i: {"pool_eligible": True})]
ROUTES = BUYER_ROUTES + POOL_ROUTES + FARMER_ROUTES


@pytest.fixture
def world(db_client, buyer, pool_world):
    demand = make_demand(db_client, buyer, pool_world.crop["id"], 100)
    pool = make_pool(db_client, buyer, demand["id"])
    other = make_demand(db_client, buyer, pool_world.crop["id"], 50)  # a demand with no pool yet
    return {
        "crop_id": pool_world.crop["id"],
        "demand_id": other["id"],
        "pool_id": pool["id"],
        "lot_id": pool_world.farms["A"]["lot_id"],
    }


@pytest.fixture
def second_buyer(register_buyer):
    from tests.conftest import Actor, bearer

    data = register_buyer("9123456799", full_name="Other Buyer")
    return Actor(bearer(data["tokens"]["access_token"]), data["user"]["id"], "buyer")


def test_anonymous_everywhere(db_client, world):
    assert sweep(db_client, ROUTES, world, KEY, 401, "not_authenticated") == []


def test_farmers_cannot_use_buyer_or_pool_routes(db_client, world, farmer):
    assert (
        sweep(db_client, BUYER_ROUTES + POOL_ROUTES, world, {**farmer.headers, **KEY}, 403, "permission_denied") == []
    )


def test_buyers_and_admins_cannot_change_farm_lots(db_client, world, buyer, admin):
    for actor in (buyer, admin):
        assert sweep(db_client, FARMER_ROUTES, world, actor.headers, 403, "permission_denied") == []


def test_admin_cannot_create_demands_but_oversees_pools(db_client, world, admin):
    assert sweep(db_client, BUYER_ROUTES, world, {**admin.headers, **KEY}, 403, "permission_denied") == []
    assert sweep(db_client, [r for r in POOL_ROUTES if r.method == "GET"], world, admin.headers, 200, None) == []


def test_another_buyer_sees_nothing(db_client, world, second_buyer):
    resource = [r for r in BUYER_ROUTES + POOL_ROUTES if not r.collection]
    assert sweep(db_client, resource, world, {**second_buyer.headers, **KEY}, 404, "not_found") == []
    assert db_client.get("/api/v1/pools", headers=second_buyer.headers).json()["total"] == 0


def test_another_farmer_cannot_touch_my_lot(db_client, world, other_farmer):
    assert sweep(db_client, FARMER_ROUTES, world, other_farmer.headers, 404, "not_found") == []


def test_owner_reads(db_client, world, buyer):
    assert (
        sweep(db_client, [r for r in BUYER_ROUTES + POOL_ROUTES if r.method == "GET"], world, buyer.headers, 200, None)
        == []
    )


def test_every_pooling_route_is_covered(db_container):
    paths = create_app(settings=Settings(_env_file=None), container=db_container).openapi()["paths"]  # type: ignore[call-arg]
    actual = {
        (m.upper(), re.sub(r"^/api/v1", "", p))
        for p, ops in paths.items()
        for m in ops
        if m in {"get", "post", "patch", "delete"}
        and re.sub(r"^/api/v1", "", p).startswith(("/buyer-demands", "/pools"))
    }
    assert actual == {(r.method, r.path) for r in BUYER_ROUTES + POOL_ROUTES}
