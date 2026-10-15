"""Admin-controlled tester access: new sign-ups can wait for approval; an admin can approve, suspend or revoke."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.container import Container, build_container
from app.main import create_app
from tests.conftest import PASSWORD, bearer, buyer_body, farmer_body, sign_in


@pytest.fixture
def pending_client(db_settings: Settings, db_container: Container) -> Iterator[TestClient]:
    """The production setting: every new sign-up waits for an admin (db_container has already emptied the tables)."""
    settings = db_settings.model_copy(update={"new_account_access": "pending"})
    container = build_container(settings)
    with TestClient(create_app(settings=settings, container=container)) as tc:
        yield tc
    container.shutdown()


@pytest.fixture
def pending_admin(pending_client: TestClient, make_admin) -> dict:
    make_admin()
    return bearer(sign_in(pending_client, "+919000000001", "AdminPass123")["tokens"]["access_token"])


def _sign_up(client: TestClient, body: dict) -> dict:
    r = client.post("/api/v1/auth/register", json=body)
    assert r.status_code == 202, r.text
    return r.json()


def _set(client: TestClient, admin: dict, user_id: str, status: str):
    return client.post(f"/api/v1/admin/users/{user_id}/access", json={"status": status}, headers=admin)


def _user_id(client: TestClient, admin: dict, phone: str) -> str:
    users = client.get("/api/v1/admin/users", headers=admin).json()["items"]
    return next(u["id"] for u in users if u["phone"] == phone)


def test_default_setting_keeps_open_sign_up(register_farmer):
    out = register_farmer()
    assert out["user"]["access_status"] == "approved"
    assert out["tokens"]["access_token"]


def test_new_sign_up_waits_for_approval_then_signs_in(pending_client, pending_admin):
    body = _sign_up(pending_client, farmer_body())
    assert body["status"] == "pending" and "waiting for approval" in body["message"]
    assert body["tokens"] is None and body["user"] is None  # no session before an admin approves

    r = pending_client.post("/api/v1/auth/login", json={"phone": "+919876543210", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "access_pending"

    waiting = pending_client.get("/api/v1/admin/users", params={"access": "pending"}, headers=pending_admin).json()
    assert [u["phone"] for u in waiting["items"]] == ["+919876543210"]
    assert waiting["items"][0]["phone_verified_at"] is None  # no SMS check: the admin's approval is the check

    approved = _set(pending_client, pending_admin, waiting["items"][0]["id"], "approved")
    assert approved.status_code == 200 and approved.json()["access_status"] == "approved"
    tokens = sign_in(pending_client, "+919876543210", PASSWORD)["tokens"]
    assert pending_client.get("/api/v1/auth/me", headers=bearer(tokens["access_token"])).status_code == 200


def test_signing_up_an_existing_number_reveals_nothing_and_changes_nothing(pending_client, pending_admin):
    first = _sign_up(pending_client, farmer_body())
    uid = _user_id(pending_client, pending_admin, "+919876543210")
    _set(pending_client, pending_admin, uid, "approved")

    again = _sign_up(pending_client, buyer_body("+91 98765 43210", password="Takeover789"))
    assert again == first  # the same answer as a brand-new sign-up: who is registered is not revealed
    users = pending_client.get("/api/v1/admin/users", headers=pending_admin).json()["items"]
    assert len(users) == 2  # the admin and the original farmer; nothing new was created
    assert sign_in(pending_client, "+919876543210", PASSWORD)["user"]["role"] == "farmer"
    r = pending_client.post("/api/v1/auth/login", json={"phone": "+919876543210", "password": "Takeover789"})
    assert r.status_code == 401


def test_suspend_blocks_at_once_and_reapproval_resumes_the_session(pending_client, pending_admin):
    _sign_up(pending_client, buyer_body())
    uid = _user_id(pending_client, pending_admin, "+919123456780")
    _set(pending_client, pending_admin, uid, "approved")
    tokens = sign_in(pending_client, "+919123456780", PASSWORD)["tokens"]
    me = bearer(tokens["access_token"])

    assert _set(pending_client, pending_admin, uid, "suspended").status_code == 200
    r = pending_client.get("/api/v1/auth/me", headers=me)
    assert r.status_code == 403 and r.json()["error"]["code"] == "access_suspended"
    r = pending_client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 403 and r.json()["error"]["code"] == "access_suspended"

    _set(pending_client, pending_admin, uid, "approved")
    assert pending_client.get("/api/v1/auth/me", headers=me).status_code == 200


def test_revoke_signs_out_every_session(pending_client, pending_admin):
    _sign_up(pending_client, farmer_body())
    uid = _user_id(pending_client, pending_admin, "+919876543210")
    _set(pending_client, pending_admin, uid, "approved")
    tokens = sign_in(pending_client, "+919876543210", PASSWORD)["tokens"]

    _set(pending_client, pending_admin, uid, "revoked")
    r = pending_client.post("/api/v1/auth/login", json={"phone": "+919876543210", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "access_revoked"

    # approving again does not bring the old sessions back: the person signs in anew
    _set(pending_client, pending_admin, uid, "approved")
    r = pending_client.get("/api/v1/auth/me", headers=bearer(tokens["access_token"]))
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_revoked"
    assert sign_in(pending_client, "+919876543210", PASSWORD)["tokens"]["access_token"]


def test_only_admins_change_access_and_admins_cannot_be_locked_out(pending_client, pending_admin):
    _sign_up(pending_client, farmer_body())
    farmer_id = _user_id(pending_client, pending_admin, "+919876543210")
    _set(pending_client, pending_admin, farmer_id, "approved")
    _sign_up(pending_client, buyer_body())
    buyer_id = _user_id(pending_client, pending_admin, "+919123456780")
    farmer = bearer(sign_in(pending_client, "+919876543210", PASSWORD)["tokens"]["access_token"])

    assert _set(pending_client, farmer, buyer_id, "approved").status_code == 403  # a farmer cannot approve anyone
    admin_id = _user_id(pending_client, pending_admin, "+919000000001")
    r = _set(pending_client, pending_admin, admin_id, "revoked")
    assert r.status_code == 403 and r.json()["error"]["code"] == "admin_access_fixed"
    assert _set(pending_client, pending_admin, farmer_id, "pending").status_code == 422  # not an admin decision
    missing = "00000000-0000-0000-0000-000000000000"
    assert _set(pending_client, pending_admin, missing, "approved").status_code == 404


def test_existing_sessions_unaffected_by_switching_to_pending(db_client, db_settings, register_farmer):
    """Accounts that existed before NEW_ACCOUNT_ACCESS=pending stay approved."""
    register_farmer()
    settings = db_settings.model_copy(update={"new_account_access": "pending"})
    container = build_container(settings)
    try:
        with TestClient(create_app(settings=settings, container=container)) as client:
            assert sign_in(client, "+919876543210", PASSWORD)["user"]["access_status"] == "approved"
    finally:
        container.shutdown()
