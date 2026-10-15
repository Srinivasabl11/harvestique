"""Role-based access control on protected endpoints."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import bearer

pytestmark = pytest.mark.integration

FARMER_ONLY = "/api/v1/farmers/me"
BUYER_ONLY = "/api/v1/buyers/me"
ADMIN_ONLY = "/api/v1/admin/users"
PROTECTED = [FARMER_ONLY, BUYER_ONLY, ADMIN_ONLY, "/api/v1/auth/me"]


@pytest.mark.parametrize("url", PROTECTED)
def test_protected_endpoints_require_authentication(db_client, url):
    r = db_client.get(url)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "not_authenticated"


@pytest.mark.parametrize("url", PROTECTED)
def test_protected_endpoints_reject_bad_tokens(db_client, url):
    assert db_client.get(url, headers=bearer("not.a.token")).status_code == 401


def test_farmer_endpoint_allows_only_farmers(db_client, register_farmer, register_buyer, admin_tokens):
    farmer, buyer = register_farmer(), register_buyer()

    ok = db_client.get(FARMER_ONLY, headers=bearer(farmer["tokens"]["access_token"]))
    assert ok.status_code == 200 and ok.json()["village"] == "Hunsur"

    for token in (buyer["tokens"]["access_token"], admin_tokens["access_token"]):
        r = db_client.get(FARMER_ONLY, headers=bearer(token))
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "permission_denied"


def test_buyer_endpoint_allows_only_buyers(db_client, register_farmer, register_buyer, admin_tokens):
    farmer, buyer = register_farmer(), register_buyer()

    ok = db_client.get(BUYER_ONLY, headers=bearer(buyer["tokens"]["access_token"]))
    assert ok.status_code == 200 and ok.json()["business_name"] == "Rao Fresh Mart"

    for token in (farmer["tokens"]["access_token"], admin_tokens["access_token"]):
        assert db_client.get(BUYER_ONLY, headers=bearer(token)).status_code == 403


def test_admin_endpoint_allows_only_admins(db_client, register_farmer, register_buyer, admin_tokens):
    farmer, buyer = register_farmer(), register_buyer()

    ok = db_client.get(ADMIN_ONLY, headers=bearer(admin_tokens["access_token"]))
    assert ok.status_code == 200
    assert ok.json()["total"] == 3

    for token in (farmer["tokens"]["access_token"], buyer["tokens"]["access_token"]):
        r = db_client.get(ADMIN_ONLY, headers=bearer(token))
        assert r.status_code == 403 and r.json()["error"]["code"] == "permission_denied"


def test_admin_user_list_filtering_and_pagination(db_client, register_farmer, register_buyer, admin_tokens):
    register_farmer("9876543210")
    register_farmer("9876543211")
    register_buyer()
    h = bearer(admin_tokens["access_token"])

    farmers = db_client.get(ADMIN_ONLY, params={"role": "farmer"}, headers=h).json()
    assert farmers["total"] == 2 and {u["role"] for u in farmers["items"]} == {"farmer"}

    page = db_client.get(ADMIN_ONLY, params={"limit": 2, "offset": 2}, headers=h).json()
    assert page["total"] == 4 and len(page["items"]) == 2 and page["limit"] == 2 and page["offset"] == 2

    assert "password_hash" not in db_client.get(ADMIN_ONLY, headers=h).text


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"role": "wizard"}])
def test_admin_list_validates_query_params(db_client, admin_tokens, params):
    r = db_client.get(ADMIN_ONLY, params=params, headers=bearer(admin_tokens["access_token"]))
    assert r.status_code == 422 and r.json()["error"]["code"] == "request_validation_error"


def test_authorisation_uses_the_database_role_not_the_token_claim(db_client, db_container, register_farmer):
    """A role change takes effect immediately; a stale 'farmer' claim cannot linger."""
    token = register_farmer()["tokens"]["access_token"]
    assert db_client.get(ADMIN_ONLY, headers=bearer(token)).status_code == 403
    with db_container.engine.begin() as conn:
        conn.execute(text("UPDATE users SET role = 'admin'"))
    assert db_client.get(ADMIN_ONLY, headers=bearer(token)).status_code == 200
    assert db_client.get(FARMER_ONLY, headers=bearer(token)).status_code == 403


def test_farmer_cannot_escalate_by_registering_with_admin_role(db_client, register_farmer):
    r = db_client.post(
        "/api/v1/auth/register",
        json={"role": "admin", "phone": "9000099999", "password": "Harvest123", "full_name": "Evil Admin"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["details"]["errors"][0]["field"] == "role"


def test_403_and_401_use_the_standard_error_envelope(db_client, register_buyer):
    token = register_buyer()["tokens"]["access_token"]
    body = db_client.get(ADMIN_ONLY, headers=bearer(token)).json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "details"}
