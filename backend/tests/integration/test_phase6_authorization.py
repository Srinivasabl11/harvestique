"""Authorization matrix for every Phase 6 route: anonymous 401, wrong role 403, another user's resource 404,
owners/allowed roles succeed. A meta-test fails if a Phase 6 route is missing from the matrix."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.main import create_app
from tests.conftest import Actor, bearer, days_from_today, make_demand, make_pool
from tests.integration.test_farming_authorization import Route, sweep

pytestmark = pytest.mark.integration
Q = "?crop_id={crop_id}&quantity_kg=10&window_start=2027-01-01&window_end=2027-02-01"
CAL = "?start=2026-10-01&end=2026-11-01"

FARMER_ONLY = [
    Route("GET", "/market/opportunities", collection=True),
    Route("GET", "/participations", collection=True),
    Route("POST", "/participations/{participation_id}/accept"),
    Route("POST", "/participations/{participation_id}/decline", lambda i: {"reason": "no"}),
    Route("POST", "/participations/{participation_id}/progress", lambda i: {"stage": "preparing"}),
    Route("GET", "/reminders/suggestions", collection=True),
    Route("PATCH", "/farmers/me", lambda i: {"village": "x"}, collection=True),
    Route("POST", "/crop-health/analyze", collection=True),
    Route("GET", "/crop-health/analyses", collection=True),
]
BUYER_ONLY = [
    Route("GET", "/market/harvests" + Q, collection=True),
    Route("POST", "/orders", lambda i: {"pool_id": i["pool_id"]}, collection=True),
    Route("POST", "/orders/{order_id}/cancel"),
    Route("PATCH", "/buyers/me", lambda i: {"city": "x"}, collection=True),
]
BUYER_ADMIN = [
    Route("GET", "/market/supply", collection=True),
    Route("GET", "/orders", collection=True),
    Route("GET", "/orders/{order_id}"),
    Route("GET", "/orders/{order_id}/trace"),
    Route("GET", "/orders/{order_id}/batches"),
]
ADMIN_ONLY = [
    Route("POST", "/admin/hubs", lambda i: {"name": "Matrix Hub"}, collection=True),
    Route("PATCH", "/admin/hubs/{hub_id}", lambda i: {"is_active": True}, collection=True),
    Route("GET", "/admin/batches", collection=True),
    Route("DELETE", "/admin/batches/{batch_id}"),
    Route(
        "POST",
        "/admin/batches",
        lambda i: {"order_item_id": i["item_id"], "hub_id": i["hub_id"], "received_kg": 1},
        collection=True,
    ),
    Route(
        "POST",
        "/admin/batches/{batch_id}/quality",
        lambda i: {"grade": "A", "accepted_kg": 1, "rejected_kg": 0},
        collection=True,
    ),
    Route("POST", "/admin/order-items/{item_id}/fulfil", collection=True),
    Route("GET", "/admin/dashboard", collection=True),
]
FARMER_BUYER = [
    Route(
        "POST",
        "/reminders",
        lambda i: {"reminder_type": "custom", "title": "x", "due_at": "2030-01-01T09:00:00+05:30"},
        collection=True,
    ),
    Route("GET", "/reminders", collection=True),
    Route("GET", "/reminders/{reminder_id}"),
    Route("PATCH", "/reminders/{reminder_id}", lambda i: {"title": "y"}),
    Route("POST", "/reminders/{reminder_id}/complete"),
    Route("POST", "/reminders/{reminder_id}/dismiss"),
    Route("DELETE", "/reminders/{reminder_id}"),
    Route("GET", "/calendar" + CAL, collection=True),
    Route("POST", "/voice/intent", lambda i: {"transcript": "weather"}, collection=True),
    Route("POST", "/voice/transcribe", collection=True),
    Route("POST", "/voice/speak", lambda i: {"text": "hi"}, collection=True),
]
ANY_USER = [
    Route("GET", "/hubs", collection=True),
    Route("GET", "/trace/batches/{batch_code}"),
    Route("GET", "/notifications", collection=True),
    Route("GET", "/notifications/unread-count", collection=True),
    Route("POST", "/notifications/{notification_id}/read"),
    Route("POST", "/notifications/read-all", collection=True),
    Route("POST", "/assistant/chat", lambda i: {"message": "help"}, collection=True),
    Route("GET", "/assistant/tools", collection=True),
    Route("GET", "/crop-health/validation", collection=True),  # public catalogue facts, no personal data
    Route("POST", "/assistant/tools/{tool}", lambda i: {"args": {}}, collection=True),
]
ALL = FARMER_ONLY + BUYER_ONLY + BUYER_ADMIN + ADMIN_ONLY + FARMER_BUYER + ANY_USER


@pytest.fixture
def world(db_client, db_container, buyer, farmer, admin, pool_world):
    api = "/api/v1"
    pool = make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 500)["id"])
    order = db_client.post(f"{api}/orders", headers=buyer.headers, json={"pool_id": pool["id"]}).json()
    item = order["items"][0]
    part = db_client.get(f"{api}/participations", headers=farmer.headers).json()["items"][0]
    db_client.post(f"{api}/participations/{part['id']}/accept", headers=farmer.headers)
    hub = db_client.post(f"{api}/admin/hubs", headers=admin.headers, json={"name": "Auth Hub"}).json()
    name = next(k for k, v in pool_world.farms.items() if v["lot_id"] == item["lot_id"])
    cid = pool_world.farms[name]["cycle_id"]
    db_client.patch(
        f"{api}/crop-cycles/{cid}",
        headers=farmer.headers,
        json={"status": "harvested", "actual_harvest_date": days_from_today(0)},
    )
    db_client.post(f"{api}/crop-cycles/{cid}/harvest-actual", headers=farmer.headers, json={"quantity_kg": 600})
    batch = db_client.post(
        f"{api}/admin/batches",
        headers=admin.headers,
        json={"order_item_id": item["id"], "hub_id": hub["id"], "received_kg": 10},
    ).json()
    reminder = db_client.post(
        f"{api}/reminders",
        headers=farmer.headers,
        json={"reminder_type": "custom", "title": "r", "due_at": "2099-01-01T09:00:00+05:30"},
    ).json()
    with db_container.engine.begin() as conn:  # it becomes due (past times cannot be entered)
        conn.execute(
            text("UPDATE reminders SET due_at = '2020-01-01T09:00:00+05:30' WHERE id = :i"), {"i": reminder["id"]}
        )
    note = db_client.get(f"{api}/notifications", headers=farmer.headers).json()["items"][0]
    return {
        "crop_id": pool_world.crop["id"],
        "pool_id": pool["id"],
        "order_id": order["id"],
        "item_id": item["id"],
        "participation_id": part["id"],
        "hub_id": hub["id"],
        "batch_id": batch["id"],
        "batch_code": batch["code"],
        "reminder_id": reminder["id"],
        "notification_id": note["id"],
        "tool": "list_reminders",
    }


@pytest.fixture
def other_buyer(register_buyer) -> Actor:
    data = register_buyer("9123456712", profile={"business_name": "Another Buyer"})
    return Actor(bearer(data["tokens"]["access_token"]), data["user"]["id"], "buyer")


def test_anonymous_gets_401_everywhere(db_client, world):
    assert sweep(db_client, ALL, world, None, 401, "not_authenticated") == []


@pytest.mark.parametrize(
    ("routes", "wrong"),
    [
        (FARMER_ONLY, ("buyer", "admin")),
        (BUYER_ONLY, ("farmer", "admin")),
        (BUYER_ADMIN, ("farmer",)),
        (ADMIN_ONLY, ("farmer", "buyer")),
        (FARMER_BUYER, ("admin",)),
    ],
)
def test_wrong_roles_get_403(db_client, world, farmer, buyer, admin, routes, wrong):
    actors = {"farmer": farmer, "buyer": buyer, "admin": admin}
    for role in wrong:
        assert sweep(db_client, routes, world, actors[role].headers, 403, "permission_denied") == [], role


def test_another_farmer_sees_nothing_of_mine(db_client, world, other_farmer):
    mine = [r for r in FARMER_ONLY + FARMER_BUYER + ANY_USER if not r.collection]
    assert sweep(db_client, mine, world, other_farmer.headers, 404, None) == []


def test_another_buyer_sees_nothing_of_mine(db_client, world, other_buyer):
    mine = [r for r in BUYER_ONLY + BUYER_ADMIN if not r.collection]
    assert sweep(db_client, mine, world, other_buyer.headers, 404, "not_found") == []
    r = db_client.post("/api/v1/orders", headers=other_buyer.headers, json={"pool_id": world["pool_id"]})
    assert r.status_code == 404
    assert db_client.get(f"/api/v1/trace/batches/{world['batch_code']}", headers=other_buyer.headers).status_code == 404


def test_allowed_readers_succeed(db_client, world, farmer, buyer, admin):
    reads = lambda routes: [r for r in routes if r.method == "GET"]  # noqa: E731
    assert sweep(db_client, reads(FARMER_ONLY), world, farmer.headers, 200, None) == []
    assert sweep(db_client, reads(BUYER_ONLY + BUYER_ADMIN), world, buyer.headers, 200, None) == []
    assert sweep(db_client, reads(BUYER_ADMIN + ADMIN_ONLY), world, admin.headers, 200, None) == []
    assert sweep(db_client, reads(ANY_USER + FARMER_BUYER), world, farmer.headers, 200, None) == []
    assert (
        sweep(
            db_client, [r for r in ANY_USER if r.method == "GET" and "trace" in r.path], world, buyer.headers, 200, None
        )
        == []
    )


def test_every_phase6_route_is_in_the_matrix(db_container):
    prefixes = (
        "/market",
        "/orders",
        "/participations",
        "/hubs",
        "/admin/hubs",
        "/admin/batches",
        "/admin/order-items",
        "/admin/dashboard",
        "/trace",
        "/reminders",
        "/notifications",
        "/calendar",
        "/assistant",
        "/voice",
        "/crop-health",
    )
    paths = create_app(settings=Settings(_env_file=None), container=db_container).openapi()["paths"]  # type: ignore[call-arg]
    actual = {
        (m.upper(), p2)
        for p, ops in paths.items()
        for m in ops
        if m in {"get", "post", "patch", "put", "delete"}
        and (
            (p2 := re.sub(r"^/api/v1", "", p)).startswith(prefixes)
            or (p2 in ("/farmers/me", "/buyers/me") and m == "patch")
        )
    }
    covered = {
        (
            r.method,
            re.sub(
                r"\{(batch_code|tool)\}",
                lambda m: "{code}" if m.group(1) == "batch_code" else "{name}",
                r.path.split("?")[0],
            ),
        )
        for r in ALL
    }
    assert actual == covered, f"missing: {sorted(actual - covered)}; stale: {sorted(covered - actual)}"
