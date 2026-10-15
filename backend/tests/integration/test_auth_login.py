"""POST /auth/login, invalid credentials, and brute-force lockout."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from tests.conftest import PASSWORD, bearer

URL = "/api/v1/auth/login"
pytestmark = pytest.mark.integration


def login(client, phone="9876543210", password=PASSWORD):
    """Both steps: password (a code is sent) and, if accepted, the code. Returns the response that decided it."""
    r = client.post(URL, json={"phone": phone, "password": password})
    if r.status_code != 202:
        return r
    ch = r.json()
    return client.post(f"{URL}/verify", json={"challenge_id": ch["challenge_id"], "code": ch["dev_code"]})


def test_login_success_returns_user_and_tokens(db_client, register_farmer):
    register_farmer()
    r = login(db_client)
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "farmer" and body["user"]["last_login_at"]
    assert db_client.get("/api/v1/auth/me", headers=bearer(body["tokens"]["access_token"])).status_code == 200


@pytest.mark.parametrize("phone", ["9876543210", "+919876543210", "98765 43210", "919876543210"])
def test_login_accepts_any_phone_format(db_client, register_farmer, phone):
    register_farmer("9876543210")
    assert login(db_client, phone).status_code == 200


def test_each_login_creates_an_independent_session(db_client, register_farmer):
    register_farmer()
    a, b = login(db_client).json()["tokens"], login(db_client).json()["tokens"]
    assert a["refresh_token"] != b["refresh_token"]
    assert a["access_token"] != b["access_token"]


def test_wrong_password_is_401(db_client, register_farmer):
    register_farmer()
    r = login(db_client, password="WrongPass123")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"
    assert r.headers["www-authenticate"] == "Bearer"


def test_unknown_phone_is_indistinguishable_from_wrong_password(db_client, register_farmer):
    register_farmer()
    wrong_pw = login(db_client, password="WrongPass123")
    unknown = login(db_client, phone="9000011111")
    assert unknown.status_code == wrong_pw.status_code == 401
    assert unknown.json() == wrong_pw.json()  # no account enumeration


def test_password_is_case_sensitive(db_client, register_farmer):
    register_farmer()
    assert login(db_client, password=PASSWORD.lower()).status_code == 401


@pytest.mark.parametrize(
    "body", [{}, {"phone": "9876543210"}, {"password": PASSWORD}, {"phone": "9876543210", "password": ""}]
)
def test_login_validation(db_client, body):
    r = db_client.post(URL, json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "request_validation_error"


def test_invalid_phone_format_is_a_validation_error(db_client):
    assert login(db_client, phone="abc").status_code == 422


def test_disabled_account_cannot_log_in(db_client, db_container, register_farmer):
    register_farmer()
    with db_container.engine.begin() as conn:
        conn.execute(text("UPDATE users SET is_active = false"))
    r = login(db_client)
    assert r.status_code == 403 and r.json()["error"]["code"] == "account_disabled"
    # a wrong password still reveals nothing about the account state
    assert login(db_client, password="WrongPass123").status_code == 401


def test_password_hash_upgraded_when_parameters_strengthen(db_client, db_container, register_farmer):
    register_farmer()
    with db_container.engine.connect() as conn:
        before = conn.scalar(text("SELECT password_hash FROM users"))
    db_container.passwords = type(db_container.passwords)(time_cost=2, memory_kib=16, parallelism=1)
    assert login(db_client).status_code == 200
    with db_container.engine.connect() as conn:
        after = conn.scalar(text("SELECT password_hash FROM users"))
    assert after != before and "t=2" in after
    assert login(db_client).status_code == 200  # new hash still verifies


# ------------------------------------------------------------------ lockout


def test_account_locks_after_repeated_failures(db_client, register_farmer, fixed_clock):
    register_farmer()
    for _ in range(5):
        assert login(db_client, password="WrongPass123").status_code == 401
    r = login(db_client, password="WrongPass123")
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "account_locked"
    assert int(r.headers["retry-after"]) == r.json()["error"]["details"]["retry_after_seconds"] > 0
    # even the CORRECT password is refused while locked
    assert login(db_client).status_code == 429


def test_lockout_applies_to_unknown_phones_too(db_client):
    for _ in range(5):
        login(db_client, phone="9000022222", password="WrongPass123")
    assert login(db_client, phone="9000022222").status_code == 429  # same behaviour, no enumeration


def test_lockout_expires(db_client, register_farmer, fixed_clock):
    register_farmer()
    for _ in range(5):
        login(db_client, password="WrongPass123")
    assert login(db_client).status_code == 429
    fixed_clock.advance_to(fixed_clock.now() + timedelta(minutes=15, seconds=1))
    assert login(db_client).status_code == 200


def test_successful_login_resets_failure_counter(db_client, register_farmer, fixed_clock):
    register_farmer()
    for _ in range(4):
        login(db_client, password="WrongPass123")
    assert login(db_client).status_code == 200
    for _ in range(4):
        assert login(db_client, password="WrongPass123").status_code == 401  # not locked: counter restarted
    assert login(db_client).status_code == 200


def test_lockout_is_per_phone(db_client, register_farmer, register_buyer, fixed_clock):
    register_farmer()
    register_buyer()
    for _ in range(5):
        login(db_client, password="WrongPass123")
    assert login(db_client, phone="9123456780").status_code == 200
