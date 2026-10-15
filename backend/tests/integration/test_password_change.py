"""Passwords without SMS: change with the current password, admin-issued temporary passwords (forced change), the
operator set-password command, and the per-account tour flag."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.cli.set_password import PASSWORD_ENV, main
from app.services.auth import generate_temporary_password
from tests.conftest import PASSWORD, bearer, sign_in

pytestmark = pytest.mark.integration
API = "/api/v1/auth"
PHONE = "+919876543210"
NEW = "NewHarvest456"


def change(client, current=PASSWORD, new=NEW, phone=PHONE):
    return client.post(
        f"{API}/password/change", json={"phone": phone, "current_password": current, "new_password": new}
    )


def reset(client, admin_headers, user_id):
    return client.post(f"/api/v1/admin/users/{user_id}/password-reset", headers=admin_headers)


def test_change_sets_the_new_password_and_signs_out_other_devices(db_client, register_farmer):
    old = register_farmer()["tokens"]
    r = change(db_client)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    fresh = r.json()["tokens"]
    r = db_client.get(f"{API}/me", headers=bearer(old["access_token"]))
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_revoked"
    assert db_client.get(f"{API}/me", headers=bearer(fresh["access_token"])).status_code == 200
    assert db_client.post(f"{API}/login", json={"phone": PHONE, "password": PASSWORD}).status_code == 401
    assert sign_in(db_client, PHONE, NEW)["user"]["must_change_password"] is False


def test_change_needs_the_right_current_password_and_counts_failures(db_client, register_farmer, fixed_clock):
    register_farmer()
    for _ in range(5):
        r = change(db_client, current="WrongPass123")
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    assert change(db_client).status_code == 429  # the same lockout as sign-in
    assert db_client.post(f"{API}/login", json={"phone": PHONE, "password": PASSWORD}).status_code == 429


@pytest.mark.parametrize("weak", ["short1", "nodigitshere", "Password1"])
def test_the_new_password_follows_the_policy_and_is_never_echoed(db_client, register_farmer, weak):
    register_farmer()
    r = change(db_client, new=weak)
    assert r.status_code == 422 and weak not in r.text
    assert sign_in(db_client, PHONE, PASSWORD)  # unchanged


def test_the_new_password_must_differ(db_client, register_farmer):
    register_farmer()
    r = change(db_client, new=PASSWORD)
    assert r.status_code == 422 and r.json()["error"]["code"] == "password_unchanged"


def test_a_blocked_account_cannot_change_its_password(db_client, db_container, register_farmer):
    register_farmer()
    with db_container.engine.begin() as conn:
        conn.execute(text("UPDATE users SET access_status = 'suspended'"))
    r = change(db_client)
    assert r.status_code == 403 and r.json()["error"]["code"] == "access_suspended"


def test_admin_reset_gives_a_temporary_password_that_must_be_changed(db_client, register_farmer, admin):
    farmer = register_farmer()
    uid = farmer["user"]["id"]
    r = reset(db_client, admin.headers, uid)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    temporary = r.json()["temporary_password"]
    assert r.json()["user"]["must_change_password"] is True
    assert temporary not in r.json()["message"]

    # every old session ended and the old password no longer works
    r = db_client.get(f"{API}/me", headers=bearer(farmer["tokens"]["access_token"]))
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_revoked"
    assert db_client.post(f"{API}/login", json={"phone": PHONE, "password": PASSWORD}).status_code == 401

    # the temporary password alone gives no session
    r = db_client.post(f"{API}/login", json={"phone": PHONE, "password": temporary})
    assert r.status_code == 403 and r.json()["error"]["code"] == "password_change_required"
    assert "tokens" not in r.text

    r = change(db_client, current=temporary)
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is False
    assert sign_in(db_client, PHONE, NEW)["tokens"]["access_token"]
    assert db_client.post(f"{API}/login", json={"phone": PHONE, "password": temporary}).status_code == 401


def test_admin_reset_clears_a_lockout_and_is_stored_only_as_a_hash(db_client, db_container, register_farmer, admin):
    uid = register_farmer()["user"]["id"]
    for _ in range(5):
        db_client.post(f"{API}/login", json={"phone": PHONE, "password": "WrongPass123"})
    assert db_client.post(f"{API}/login", json={"phone": PHONE, "password": PASSWORD}).status_code == 429
    temporary = reset(db_client, admin.headers, uid).json()["temporary_password"]
    with db_container.engine.connect() as conn:
        stored = conn.scalar(text("SELECT password_hash FROM users WHERE role = 'farmer'"))
    assert stored.startswith("$argon2id$") and temporary not in stored
    assert change(db_client, current=temporary).status_code == 200


def test_only_admins_reset_and_never_an_admin_password(db_client, register_farmer, register_buyer, admin):
    farmer = register_farmer()
    buyer_id = register_buyer()["user"]["id"]
    assert reset(db_client, bearer(farmer["tokens"]["access_token"]), buyer_id).status_code == 403
    assert reset(db_client, {}, buyer_id).status_code == 401
    admin_id = db_client.get(f"{API}/me", headers=admin.headers).json()["id"]
    r = reset(db_client, admin.headers, admin_id)
    assert r.status_code == 403 and r.json()["error"]["code"] == "admin_password_fixed"
    assert reset(db_client, admin.headers, "00000000-0000-0000-0000-000000000000").status_code == 404


def test_temporary_passwords_are_random_readable_and_meet_the_policy():
    seen = {generate_temporary_password() for _ in range(200)}
    assert len(seen) == 200
    for pw in seen:
        assert len(pw) == 14 and pw.count("-") == 2
        assert not set(pw) & set("01ilo")  # no look-alike characters
        assert any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw)


def test_operator_command_sets_any_password_including_an_admins(db_client, make_admin, monkeypatch, capsys):
    db_container = db_client.app.state.container
    make_admin()
    old = sign_in(db_client, "+919000000001", "AdminPass123")["tokens"]
    monkeypatch.setenv(PASSWORD_ENV, "Recovered789")
    assert main(["--phone", "9000000001"], db_container) == 0
    out = capsys.readouterr().out
    assert "Password set for admin" in out and "Recovered789" not in out
    r = db_client.get(f"{API}/me", headers=bearer(old["access_token"]))
    assert r.status_code == 401
    assert sign_in(db_client, "+919000000001", "Recovered789")["user"]["role"] == "admin"


def test_operator_command_refuses_weak_passwords_and_unknown_numbers(db_container, monkeypatch, capsys):
    monkeypatch.setenv(PASSWORD_ENV, "weak")
    assert main(["--phone", "9000000001"], db_container) == 2
    monkeypatch.setenv(PASSWORD_ENV, "Recovered789")
    assert main(["--phone", "9000000001"], db_container) == 1
    assert "No account" in capsys.readouterr().err


def test_the_tour_version_is_stored_per_account_and_never_goes_back(db_client, register_farmer, register_buyer):
    farmer = register_farmer()
    buyer = register_buyer()
    assert farmer["user"]["tour_version_seen"] == 0
    h = bearer(farmer["tokens"]["access_token"])
    assert db_client.post(f"{API}/me/tour", headers=h, json={"version": 1}).json()["tour_version_seen"] == 1
    assert db_client.post(f"{API}/me/tour", headers=h, json={"version": 0}).json()["tour_version_seen"] == 1
    assert db_client.get(f"{API}/me", headers=bearer(buyer["tokens"]["access_token"])).json()["tour_version_seen"] == 0
    assert db_client.post(f"{API}/me/tour", json={"version": 1}).status_code == 401
