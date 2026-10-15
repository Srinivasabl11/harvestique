"""One farmer-buyer journey through the endpoints the nine app sections call, checking what EACH side sees after every
step (farmer Home/Market/Harvest/Reminders; buyer Market/Demand/Orders/Reminders), plus authorization between roles.
The per-feature rules (pooling, reallocation, concurrency) have their own suites; this checks they stay in sync."""

from __future__ import annotations

import pytest

from tests.conftest import Actor, bearer, days_from_today, make_demand

pytestmark = pytest.mark.integration
API = "/api/v1"


def get(client, actor, path, **params):
    r = client.get(f"{API}{path}", headers=actor.headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def items(client, actor, path, **params):
    return get(client, actor, path, limit=100, **params)["items"]


def unread(client, actor):
    return get(client, actor, "/notifications/unread-count")["unread"]


def test_listing_demand_order_accept_progress_and_cancel_stay_in_sync_for_both_roles(
    db_client, farmer, buyer, pool_world, register_buyer
):
    crop_id = pool_world.crop["id"]
    # farmer My Farm/Harvest -> buyer Market: opted-in lots are visible as estimates, not as confirmed stock
    supply = get(db_client, buyer, "/market/supply")
    row = next(r for r in supply if r["crop_id"] == crop_id)
    assert row["available_kg"] == 2000 and row["lots"] == 5
    found = get(
        db_client,
        buyer,
        "/market/harvests",
        crop_id=crop_id,
        quantity_kg=800,
        window_start=days_from_today(30),
        window_end=days_from_today(150),
    )
    assert found["matches"] and "phone" not in str(found)  # no private contact data in search results

    # buyer Demand -> farmer Market: the demand shows up as an opportunity for the farmer growing that crop
    demand = make_demand(db_client, buyer, crop_id, 800)
    assert demand["status"] == "open"
    opportunities = get(db_client, farmer, "/market/opportunities")
    assert any(o["crop_name"] == pool_world.crop["name"] for o in opportunities)

    # buyer pools and orders -> farmer Home/Market: pending requests and an unread notification per request
    pool = db_client.post(
        f"{API}/buyer-demands/{demand['id']}/pool", headers={**buyer.headers, "Idempotency-Key": "j-pool"}, json={}
    )
    assert pool.status_code in (200, 201), pool.text
    order = db_client.post(
        f"{API}/orders", headers={**buyer.headers, "Idempotency-Key": "j-order"}, json={"pool_id": pool.json()["id"]}
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    assert order.json()["ordered_kg"] == 800
    replay = db_client.post(
        f"{API}/orders", headers={**buyer.headers, "Idempotency-Key": "j-order"}, json={"pool_id": pool.json()["id"]}
    )
    assert replay.json()["id"] == order_id  # a retried tap does not create a second order
    pending = items(db_client, farmer, "/participations", status="pending")
    assert pending and sum(p["quantity_kg"] for p in pending) == 800
    farmer_unread = unread(db_client, farmer)
    categories = sorted(n["category"] for n in items(db_client, farmer, "/notifications"))
    # the demand itself told the matching farmer once ("Buyer looking for ..."); then one request per lot
    assert categories == ["buyer_opportunity"] + ["participation_request"] * len(pending)
    assert farmer_unread == len(pending) + 1
    assert get(db_client, buyer, f"/buyer-demands/{demand['id']}")["status"] != "open"  # not offered twice

    # farmer accepts all -> buyer Orders shows confirmed; buyer is told once per request
    for p in pending:
        r = db_client.post(f"{API}/participations/{p['id']}/accept", headers=farmer.headers)
        assert r.status_code == 200, r.text
    mine = items(db_client, buyer, "/orders")
    assert [o["status"] for o in mine if o["id"] == order_id] == ["confirmed"]
    assert unread(db_client, buyer) == len(pending)

    # farmer progress -> buyer sees it; read state persists per user
    first = pending[0]
    r = db_client.post(
        f"{API}/participations/{first['id']}/progress", headers=farmer.headers, json={"stage": "preparing"}
    )
    assert r.status_code == 200, r.text
    notes = items(db_client, buyer, "/notifications")
    assert db_client.post(f"{API}/notifications/{notes[0]['id']}/read", headers=buyer.headers).status_code in (200, 204)
    assert unread(db_client, buyer) == len(pending)  # +1 progress -1 read
    assert unread(db_client, farmer) == farmer_unread  # the buyer reading changes nothing for the farmer

    # unauthorized: another buyer and the farmer cannot see or change the buyer's order
    other = register_buyer("9123456712", profile={"business_name": "Other Co"})
    intruder = Actor(bearer(other["tokens"]["access_token"]), other["user"]["id"], "buyer")
    assert db_client.get(f"{API}/orders/{order_id}", headers=intruder.headers).status_code == 404
    assert db_client.post(f"{API}/orders/{order_id}/cancel", headers=intruder.headers).status_code == 404
    assert db_client.post(f"{API}/orders/{order_id}/cancel", headers=farmer.headers).status_code == 403
    assert db_client.post(f"{API}/participations/{first['id']}/accept", headers=buyer.headers).status_code == 403
    assert db_client.get(f"{API}/notifications", headers=intruder.headers).json()["items"] == []

    # buyer cancels -> farmer side updated, supply released, everyone told
    before = unread(db_client, farmer)
    r = db_client.post(f"{API}/orders/{order_id}/cancel", headers=buyer.headers, json={"reason": "plans changed"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
    asked = {q["id"] for q in pending}
    statuses = {p["status"] for p in items(db_client, farmer, "/participations") if p["id"] in asked}
    assert statuses == {"withdrawn"}, statuses  # shown as "Withdrawn" in Market; gone from Harvest
    assert unread(db_client, farmer) > before
    assert get(db_client, buyer, "/market/supply")[0]["available_kg"] == 2000  # nothing stays held
    again = db_client.post(f"{API}/orders/{order_id}/cancel", headers=buyer.headers, json={})
    assert again.status_code in (200, 409)  # repeat is harmless, never a second state change
    assert get(db_client, buyer, f"/orders/{order_id}")["status"] == "cancelled"


def test_after_the_order_is_cancelled_the_demand_is_not_left_stuck(db_client, buyer, pool_world):
    demand = make_demand(db_client, buyer, pool_world.crop["id"], 300)
    pool = db_client.post(
        f"{API}/buyer-demands/{demand['id']}/pool", headers={**buyer.headers, "Idempotency-Key": "s-pool"}, json={}
    ).json()
    order = db_client.post(
        f"{API}/orders", headers={**buyer.headers, "Idempotency-Key": "s-order"}, json={"pool_id": pool["id"]}
    ).json()
    assert db_client.post(f"{API}/orders/{order['id']}/cancel", headers=buyer.headers, json={}).status_code == 200
    after = get(db_client, buyer, f"/buyer-demands/{demand['id']}")
    withdraw = db_client.post(f"{API}/buyer-demands/{demand['id']}/cancel", headers=buyer.headers)
    assert after["status"] == "cancelled"  # the buyer's Demand tab shows it closed with the order
    assert withdraw.status_code == 200 and withdraw.json()["status"] == "cancelled"  # a repeat is harmless
