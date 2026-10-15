"""JWT authentication, /me, refresh rotation, logout and session revocation."""

from __future__ import annotations

import uuid
from datetime import timedelta

import jwt
import pytest
from sqlalchemy import text

from tests.conftest import STRONG_TEST_SECRET, bearer, login_and_verify

ME = "/api/v1/auth/me"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
pytestmark = pytest.mark.integration


def err_code(response) -> str:
    return response.json()["error"]["code"]


# --------------------------------------------------------------------- /me


def test_me_returns_authenticated_user(db_client, register_farmer):
    data = register_farmer()
    r = db_client.get(ME, headers=bearer(data["tokens"]["access_token"]))
    assert r.status_code == 200
    assert r.json()["id"] == data["user"]["id"] and r.json()["role"] == "farmer"
    assert "password" not in r.text


def test_me_returns_buyer_profile_for_buyers(db_client, register_buyer):
    token = register_buyer()["tokens"]["access_token"]
    body = db_client.get(ME, headers=bearer(token)).json()
    assert body["buyer_profile"]["business_name"] == "Rao Fresh Mart" and body["farmer_profile"] is None


# ----------------------------------------------------- authentication errors


def test_missing_token_is_401(db_client):
    r = db_client.get(ME)
    assert r.status_code == 401 and err_code(r) == "not_authenticated"
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("header", ["Basic dXNlcjpwYXNz", "Bearer", "Token abc", "abc"])
def test_wrong_auth_scheme_is_401(db_client, header):
    assert db_client.get(ME, headers={"Authorization": header}).status_code == 401


@pytest.mark.parametrize("token", ["garbage", "a.b.c", "x" * 400])
def test_malformed_token_is_401(db_client, token):
    r = db_client.get(ME, headers=bearer(token))
    assert r.status_code == 401 and err_code(r) == "invalid_token"


def test_token_signed_with_wrong_secret_is_401(db_client, register_farmer):
    data = register_farmer()
    claims = jwt.decode(
        data["tokens"]["access_token"],
        STRONG_TEST_SECRET,
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    forged = jwt.encode(claims, "attacker-secret-" + "a" * 40, algorithm="HS256")
    r = db_client.get(ME, headers=bearer(forged))
    assert r.status_code == 401 and err_code(r) == "invalid_token"


def test_alg_none_token_is_rejected(db_client, register_farmer):
    data = register_farmer()
    claims = jwt.decode(
        data["tokens"]["access_token"],
        STRONG_TEST_SECRET,
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    forged = jwt.encode(claims, key="", algorithm="none")
    assert db_client.get(ME, headers=bearer(forged)).status_code == 401


def test_tampered_payload_is_rejected(db_client, register_farmer):
    token = register_farmer()["tokens"]["access_token"]
    header, payload, signature = token.split(".")
    flipped = payload[:-2] + ("AA" if not payload.endswith("AA") else "BB")
    assert db_client.get(ME, headers=bearer(f"{header}.{flipped}.{signature}")).status_code == 401


def test_expired_token_is_401_with_distinct_code(db_client, register_farmer, fixed_clock):
    token = register_farmer()["tokens"]["access_token"]
    fixed_clock.advance_to(fixed_clock.now() + timedelta(minutes=14, seconds=50))
    assert db_client.get(ME, headers=bearer(token)).status_code == 200
    fixed_clock.advance_to(fixed_clock.now() + timedelta(seconds=20))
    r = db_client.get(ME, headers=bearer(token))
    assert r.status_code == 401 and err_code(r) == "token_expired"


def test_token_claims(db_client, register_farmer):
    data = register_farmer()
    claims = jwt.decode(
        data["tokens"]["access_token"],
        STRONG_TEST_SECRET,
        algorithms=["HS256"],
        issuer="harvestique",
        options={"verify_iat": False},
    )
    assert claims["sub"] == data["user"]["id"] and claims["role"] == "farmer" and claims["typ"] == "access"
    assert claims["exp"] - claims["iat"] == 900
    assert uuid.UUID(claims["sid"]) and claims["jti"]
    assert "phone" not in claims and "password" not in claims  # no PII in the token


def test_token_for_deleted_user_is_401(db_client, db_container, register_farmer):
    token = register_farmer()["tokens"]["access_token"]
    with db_container.engine.begin() as conn:
        conn.execute(text("DELETE FROM users"))
    r = db_client.get(ME, headers=bearer(token))
    assert r.status_code == 401 and err_code(r) == "invalid_token"


def test_disabling_account_blocks_existing_tokens_immediately(db_client, db_container, register_farmer):
    token = register_farmer()["tokens"]["access_token"]
    with db_container.engine.begin() as conn:
        conn.execute(text("UPDATE users SET is_active = false"))
    r = db_client.get(ME, headers=bearer(token))
    assert r.status_code == 403 and err_code(r) == "account_disabled"


def test_a_refresh_token_is_not_usable_as_an_access_token(db_client, register_farmer):
    refresh = register_farmer()["tokens"]["refresh_token"]
    assert db_client.get(ME, headers=bearer(refresh)).status_code == 401


# ------------------------------------------------------------------ logout


def test_logout_revokes_the_session_immediately(db_client, register_farmer):
    tokens = register_farmer()["tokens"]
    assert db_client.post(LOGOUT, headers=bearer(tokens["access_token"])).status_code == 204
    r = db_client.get(ME, headers=bearer(tokens["access_token"]))  # access token itself has not expired
    assert r.status_code == 401 and err_code(r) == "session_revoked"
    r = db_client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401 and err_code(r) == "session_revoked"


def test_logout_requires_authentication(db_client):
    assert db_client.post(LOGOUT).status_code == 401


def test_logout_only_ends_the_current_session(db_client, register_farmer):
    register_farmer()

    def login() -> dict:
        return login_and_verify(db_client, "9876543210", "Harvest123")["tokens"]

    phone_session, tablet_session = login(), login()
    db_client.post(LOGOUT, headers=bearer(phone_session["access_token"]))
    assert db_client.get(ME, headers=bearer(phone_session["access_token"])).status_code == 401
    assert db_client.get(ME, headers=bearer(tablet_session["access_token"])).status_code == 200


def test_logout_twice_is_401_not_500(db_client, register_farmer):
    token = register_farmer()["tokens"]["access_token"]
    assert db_client.post(LOGOUT, headers=bearer(token)).status_code == 204
    assert db_client.post(LOGOUT, headers=bearer(token)).status_code == 401


# ----------------------------------------------------------------- refresh


def test_refresh_rotates_tokens(db_client, register_farmer):
    old = register_farmer()["tokens"]
    r = db_client.post(REFRESH, json={"refresh_token": old["refresh_token"]})
    assert r.status_code == 200
    new = r.json()
    assert new["refresh_token"] != old["refresh_token"] and new["access_token"] != old["access_token"]
    assert db_client.get(ME, headers=bearer(new["access_token"])).status_code == 200
    # old access token belongs to the same session, which is still live
    assert db_client.get(ME, headers=bearer(old["access_token"])).status_code == 200


def test_reusing_a_rotated_refresh_token_kills_the_whole_session(db_client, register_farmer):
    old = register_farmer()["tokens"]
    new = db_client.post(REFRESH, json={"refresh_token": old["refresh_token"]}).json()

    replay = db_client.post(REFRESH, json={"refresh_token": old["refresh_token"]})  # attacker replays stolen token
    assert replay.status_code == 401 and err_code(replay) == "refresh_token_reused"

    # ... which also invalidates the legitimate holder's newest tokens
    assert db_client.post(REFRESH, json={"refresh_token": new["refresh_token"]}).status_code == 401
    r = db_client.get(ME, headers=bearer(new["access_token"]))
    assert r.status_code == 401 and err_code(r) == "session_revoked"


def test_refresh_with_unknown_token_is_401(db_client):
    r = db_client.post(REFRESH, json={"refresh_token": "x" * 64})
    assert r.status_code == 401 and err_code(r) == "invalid_refresh_token"


def test_refresh_request_validation(db_client):
    assert db_client.post(REFRESH, json={}).status_code == 422
    assert db_client.post(REFRESH, json={"refresh_token": "short"}).status_code == 422


def test_expired_refresh_token_is_401(db_client, register_farmer, fixed_clock):
    tokens = register_farmer()["tokens"]
    fixed_clock.advance_to(fixed_clock.now() + timedelta(days=14, seconds=1))
    r = db_client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401 and err_code(r) == "refresh_token_expired"


def test_refresh_blocked_for_disabled_account(db_client, db_container, register_farmer):
    tokens = register_farmer()["tokens"]
    with db_container.engine.begin() as conn:
        conn.execute(text("UPDATE users SET is_active = false"))
    r = db_client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 403 and err_code(r) == "account_disabled"
