"""POST /auth/register on a server with open sign-up (pending approval: test_tester_access.py)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import PASSWORD, bearer, buyer_body, farmer_body

URL = "/api/v1/auth/register"
pytestmark = pytest.mark.integration


def register(client, body):
    return client.post(URL, json=body)


def test_register_farmer(db_client):
    r = register(db_client, farmer_body("98765 43210", email="Ramesh@Example.COM"))
    assert r.status_code == 201
    body = r.json()
    user = body["user"]
    assert user["role"] == "farmer"
    assert user["phone"] == "+919876543210"  # normalised
    assert user["email"] == "ramesh@example.com"  # lower-cased
    assert user["farmer_profile"] == {
        "village": "Hunsur",
        "district": "Mysuru",
        "state": "Karnataka",
        "preferred_language": "kn",
    }
    assert user["buyer_profile"] is None
    assert body["tokens"]["token_type"] == "bearer" and body["tokens"]["expires_in"] == 900
    assert body["tokens"]["access_token"] and body["tokens"]["refresh_token"]


def test_register_farmer_with_minimal_profile(db_client):
    r = register(db_client, {k: v for k, v in farmer_body().items() if k != "profile"})
    assert r.status_code == 201
    assert r.json()["user"]["farmer_profile"]["preferred_language"] == "en"


def test_register_buyer(db_client):
    r = register(db_client, buyer_body())
    assert r.status_code == 201
    user = r.json()["user"]
    assert user["role"] == "buyer"
    assert user["buyer_profile"]["business_name"] == "Rao Fresh Mart"
    assert user["buyer_profile"]["buyer_type"] == "retailer"
    assert user["farmer_profile"] is None


def test_registration_logs_user_in(db_client):
    tokens = register(db_client, farmer_body()).json()["tokens"]
    assert db_client.get("/api/v1/auth/me", headers=bearer(tokens["access_token"])).status_code == 200


def test_response_never_contains_password_material(db_client):
    r = register(db_client, farmer_body())
    assert PASSWORD not in r.text
    assert "password" not in r.json()["user"] and "argon2" not in r.text


def test_password_is_stored_as_argon2id_hash(db_client, db_container):
    register(db_client, farmer_body())
    with db_container.engine.connect() as conn:
        stored = conn.scalar(text("SELECT password_hash FROM users"))
    assert stored.startswith("$argon2id$") and PASSWORD not in stored


def test_refresh_token_is_stored_only_as_hash(db_client, db_container):
    raw = register(db_client, farmer_body()).json()["tokens"]["refresh_token"]
    with db_container.engine.connect() as conn:
        stored = conn.scalar(text("SELECT token_hash FROM refresh_tokens"))
    assert stored != raw and len(stored) == 64


def test_an_already_registered_phone_cannot_be_taken_over(db_client, db_container):
    assert register(db_client, farmer_body("9876543210")).status_code == 201
    again = register(db_client, buyer_body("+91 98765-43210", password="Other4567"))  # same number, another format
    assert again.status_code == 409 and again.json()["error"]["code"] == "phone_already_registered"
    assert "tokens" not in again.text
    with db_container.engine.connect() as conn:
        assert conn.scalar(text("SELECT role FROM users")) == "farmer"  # the first account is untouched


def test_sign_ups_are_capped_per_hour_across_the_server(db_client, db_container):
    db_container.settings = db_container.settings.model_copy(update={"registrations_max_per_hour": 2})
    assert register(db_client, farmer_body("9876543210")).status_code == 201
    assert register(db_client, farmer_body("9876543211")).status_code == 201
    r = register(db_client, farmer_body("9876543212"))
    assert r.status_code == 429 and r.json()["error"]["code"] == "registration_rate_limited"
    assert r.headers["retry-after"] == "3600"


def test_duplicate_email_conflicts_case_insensitively(db_client):
    assert register(db_client, farmer_body("9876543210", email="x@example.com")).status_code == 201
    r = register(db_client, buyer_body("9123456780", email="X@EXAMPLE.com"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_already_registered"


def test_same_email_allowed_to_be_absent_on_many_users(db_client):
    assert register(db_client, farmer_body("9876543210")).status_code == 201
    assert register(db_client, farmer_body("9876543211")).status_code == 201  # both email=NULL


def _errors(response):
    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "request_validation_error"
    return {e["field"]: e for e in body["error"]["details"]["errors"]}


@pytest.mark.parametrize(
    "password", ["short1", "nodigitshere", "12345678", "x" * 129, "Password1", "Harvestique1", "ABCD1234"]
)
def test_weak_password_rejected_and_never_echoed(db_client, password):
    r = register(db_client, farmer_body(password=password))
    assert "password" in _errors(r)
    assert password not in r.text  # validation errors must not leak the submitted secret


@pytest.mark.parametrize("phone", ["", "12345", "not-a-phone", "5876543210"])
def test_invalid_phone_rejected(db_client, phone):
    assert "phone" in _errors(register(db_client, farmer_body(phone=phone)))


def test_invalid_email_rejected(db_client):
    assert "email" in _errors(register(db_client, farmer_body(email="not-an-email")))


def test_buyer_requires_business_name(db_client):
    body = buyer_body()
    body["profile"] = {"city": "Mysuru"}
    r = register(db_client, body)
    assert any(f.endswith("business_name") for f in _errors(r))


def test_invalid_buyer_type_and_language_rejected(db_client):
    b = buyer_body()
    b["profile"] = {"business_name": "Shop", "buyer_type": "spaceship"}
    assert register(db_client, b).status_code == 422
    f = farmer_body()
    f["profile"] = {"preferred_language": "klingon"}
    assert register(db_client, f).status_code == 422


@pytest.mark.parametrize("role", ["admin", "superuser", "", None])
def test_cannot_self_register_as_admin_or_unknown_role(db_client, role, db_container):
    r = register(db_client, farmer_body(role=role))
    assert r.status_code == 422
    with db_container.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM users")) == 0


def test_missing_role_rejected(db_client):
    body = farmer_body()
    del body["role"]
    assert register(db_client, body).status_code == 422


@pytest.mark.parametrize("extra", [{"is_active": False}, {"id": "x"}, {"password_hash": "x"}])
def test_unknown_fields_rejected(db_client, extra):
    assert register(db_client, farmer_body(**extra)).status_code == 422


def test_malformed_json_uses_error_envelope(db_client):
    r = db_client.post(URL, content="{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "request_validation_error"


def test_whitespace_is_trimmed(db_client):
    r = register(db_client, farmer_body(full_name="  Ramesh Gowda  "))
    assert r.json()["user"]["full_name"] == "Ramesh Gowda"
