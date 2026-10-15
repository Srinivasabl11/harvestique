"""Phone verification: registration and login finish only with a one-time SMS code.

Covers: no tokens before the code; wrong, expired, reused and exhausted codes; resend cooldown and limits; per-phone
and per-client rate limits; account enumeration; hashed storage; SMS failures; the labelled development mode versus a
real SMS provider (recorded here like a phone's inbox); and accounts created before verification existed.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import text

from app.core.errors import ProviderUnavailableError
from app.providers.sms.providers import AndroidGatewaySms, DisabledSms, RecordingSms
from tests.conftest import PASSWORD, bearer, farmer_body

pytestmark = pytest.mark.integration
API = "/api/v1/auth"
PHONE = "+919876543210"


def start_register(client, phone="9876543210", **overrides):
    return client.post(f"{API}/register", json=farmer_body(phone, **overrides))


def verify(client, challenge, code, purpose="register"):
    return client.post(f"{API}/{purpose}/verify", json={"challenge_id": challenge["challenge_id"], "code": code})


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10 ** len(code):0{len(code)}d}"


@pytest.fixture
def inbox(db_container) -> RecordingSms:
    """A real-provider setup: codes go only to the phone (recorded), never into the API response."""
    db_container.sms = RecordingSms()
    return db_container.sms


@pytest.fixture
def clock(fixed_clock):
    return fixed_clock


def later(clock, seconds: float) -> None:
    clock.advance_to(clock.now() + timedelta(seconds=seconds))


# ------------------------------------------------------------- registration
def test_registration_issues_no_tokens_until_the_code_is_verified(db_client, db_container, inbox):
    r = start_register(db_client)
    assert r.status_code == 202
    ch = r.json()
    assert "tokens" not in ch and ch["dev_code"] is None and ch["delivery"] == "sms"
    assert ch["phone_hint"] == "+91******3210" and ch["code_length"] == 6 and ch["attempts_left"] == 5
    assert inbox.sent and inbox.sent[0][0] == PHONE and "Harvestique code" in inbox.sent[0][1]
    # the pending account cannot be used yet
    with db_container.engine.connect() as conn:
        assert conn.execute(text("SELECT registration_pending, phone_verified_at FROM users")).one() == (True, None)
        assert conn.scalar(text("SELECT count(*) FROM refresh_tokens")) == 0

    done = verify(db_client, ch, inbox.last_code(PHONE))
    assert done.status_code == 201
    body = done.json()
    assert body["user"]["phone_verified_at"] is not None and body["tokens"]["access_token"]
    assert db_client.get(f"{API}/me", headers=bearer(body["tokens"]["access_token"])).status_code == 200


def test_codes_are_stored_only_as_keyed_hashes(db_client, db_container, inbox):
    start_register(db_client)
    code = inbox.last_code(PHONE)
    with db_container.engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM otp_challenges")).mappings().one()
    assert code not in str(dict(row)) and len(row["code_hash"]) == 64


def test_wrong_codes_count_down_and_then_lock_the_challenge(db_client, inbox):
    ch = start_register(db_client).json()
    good = inbox.last_code(PHONE)
    for left in (4, 3, 2, 1, 0):
        r = verify(db_client, ch, wrong(good))
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_otp"
        assert r.json()["error"]["details"]["attempts_left"] == left
    r = verify(db_client, ch, good)  # even the right code no longer works
    assert r.status_code == 401 and r.json()["error"]["code"] == "otp_attempts_exhausted"


def test_codes_expire(db_client, inbox, clock):
    ch = start_register(db_client).json()
    later(clock, 301)
    r = verify(db_client, ch, inbox.last_code(PHONE))
    assert r.status_code == 401 and r.json()["error"]["code"] == "otp_expired"


def test_a_code_works_once_and_only_for_its_purpose(db_client, inbox):
    ch = start_register(db_client).json()
    code = inbox.last_code(PHONE)
    assert verify(db_client, ch, code, purpose="login").json()["error"]["code"] == "otp_challenge_ended"
    assert verify(db_client, ch, code).status_code == 201
    again = verify(db_client, ch, code)
    assert again.status_code == 401 and again.json()["error"]["code"] == "otp_challenge_ended"


@pytest.mark.parametrize("code", ["12345", "1234567890", "abcdef", "", "12 34 56"])
def test_malformed_codes_are_validation_errors(db_client, inbox, code):
    ch = start_register(db_client).json()
    assert verify(db_client, ch, code).status_code == 422


def test_an_existing_number_gets_the_same_answer_but_no_sms_and_no_way_in(db_client, inbox, register_farmer):
    register_farmer("9876543210")
    sent_before = len(inbox.sent)
    new = start_register(db_client, "9123456789").json()
    existing = start_register(db_client, "9876543210", full_name="Attacker")
    assert existing.status_code == 202
    taken = existing.json()
    assert set(taken) == set(new) and taken["message"].startswith("If this number can be registered")
    assert taken["message"].replace("+91******3210", "X") == new["message"].replace("+91******6789", "X")
    assert len(inbox.sent) == sent_before + 1  # only the new number got an SMS
    for guess in ("000000", "999999"):
        assert verify(db_client, taken, guess).json()["error"]["code"] == "invalid_otp"


def test_registering_someone_elses_number_cannot_block_their_sign_in(
    db_client, db_container, inbox, register_farmer, monkeypatch
):
    register_farmer("9876543210")
    monkeypatch.setattr(db_container.settings, "otp_max_sends_per_phone_per_hour", 3)
    for i in range(5):  # an attacker "registers" the victim's number again and again (decoys: no SMS)
        assert start_register(db_client, "9876543210", full_name=f"Attacker {i}").status_code == 202
    r = db_client.post(f"{API}/login", json={"phone": "9876543210", "password": PASSWORD})
    assert r.status_code == 202  # no cooldown and no hourly limit used up by the decoys
    assert verify(db_client, r.json(), inbox.last_code(PHONE), purpose="login").status_code == 200


def test_an_abandoned_sign_up_is_replaced_but_its_sends_still_count(db_client, db_container, inbox, clock, monkeypatch):
    monkeypatch.setattr(db_container.settings, "otp_max_sends_per_phone_per_hour", 2)
    first = start_register(db_client, full_name="First Try").json()
    later(clock, 61)
    second = start_register(db_client, full_name="Second Try")
    assert second.status_code == 202
    assert verify(db_client, first, inbox.last_code(PHONE)).json()["error"]["code"] in (
        "invalid_otp",
        "otp_challenge_ended",
    )
    later(clock, 61)
    third = start_register(db_client, full_name="Third Try")  # replacing the pending user did not erase the history
    assert third.status_code == 429 and third.json()["error"]["code"] == "otp_rate_limited"
    done = verify(db_client, second.json(), inbox.last_code(PHONE))
    assert done.status_code == 201 and done.json()["user"]["full_name"] == "Second Try"


# --------------------------------------------------------------------- login
def test_password_alone_never_signs_in(db_client, db_container, inbox, register_farmer):
    register_farmer()
    with db_container.engine.connect() as conn:
        sessions = conn.scalar(text("SELECT count(*) FROM refresh_tokens"))
    r = db_client.post(f"{API}/login", json={"phone": "9876543210", "password": PASSWORD})
    assert r.status_code == 202 and "tokens" not in r.json() and r.json()["purpose"] == "login"
    with db_container.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM refresh_tokens")) == sessions  # nothing issued yet
    done = verify(db_client, r.json(), inbox.last_code(PHONE), purpose="login")
    assert done.status_code == 200 and done.json()["tokens"]["refresh_token"]


def test_wrong_password_sends_no_code_and_does_not_reveal_the_account(db_client, inbox, register_farmer):
    register_farmer()
    sent = len(inbox.sent)
    bad = db_client.post(f"{API}/login", json={"phone": "9876543210", "password": "Wrong12345"})
    unknown = db_client.post(f"{API}/login", json={"phone": "9000000000", "password": "Wrong12345"})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json() and len(inbox.sent) == sent


def test_an_account_created_before_verification_existed_is_verified_by_its_next_login(
    db_client, db_container, inbox, register_farmer
):
    register_farmer()
    with db_container.engine.begin() as conn:  # what migration 0008 leaves for existing accounts
        conn.execute(text("UPDATE users SET phone_verified_at = NULL, registration_pending = false"))
    r = db_client.post(f"{API}/login", json={"phone": "9876543210", "password": PASSWORD})
    done = verify(db_client, r.json(), inbox.last_code(PHONE), purpose="login")
    assert done.status_code == 200 and done.json()["user"]["phone_verified_at"] is not None


def test_a_disabled_account_gets_no_code(db_client, db_container, inbox, register_farmer):
    register_farmer()
    with db_container.engine.begin() as conn:
        conn.execute(text("UPDATE users SET is_active = false"))
    sent = len(inbox.sent)
    r = db_client.post(f"{API}/login", json={"phone": "9876543210", "password": PASSWORD})
    assert r.status_code == 403 and len(inbox.sent) == sent


# -------------------------------------------------------------------- resend
def test_resend_has_a_cooldown_and_replaces_the_code(db_client, inbox, clock):
    ch = start_register(db_client).json()
    old = inbox.last_code(PHONE)
    early = db_client.post(f"{API}/otp/resend", json={"challenge_id": ch["challenge_id"]})
    assert early.status_code == 429 and early.json()["error"]["code"] == "otp_cooldown"
    assert 0 < early.json()["error"]["details"]["retry_after_seconds"] <= 60 and early.headers["Retry-After"]
    later(clock, 60)
    r = db_client.post(f"{API}/otp/resend", json={"challenge_id": ch["challenge_id"]})
    assert r.status_code == 202 and r.json()["challenge_id"] == ch["challenge_id"]
    new = inbox.last_code(PHONE)
    if new != old:  # a 1-in-a-million chance that the new random code equals the old one
        assert verify(db_client, ch, old).json()["error"]["code"] == "invalid_otp"
    assert verify(db_client, ch, new).status_code == 201


def test_resending_does_not_reset_wrong_attempts_and_is_limited(db_client, inbox, clock):
    ch = start_register(db_client).json()
    for _ in range(3):
        verify(db_client, ch, wrong(inbox.last_code(PHONE)))
    for _ in range(3):  # otp_max_resends = 3
        later(clock, 60)
        r = db_client.post(f"{API}/otp/resend", json={"challenge_id": ch["challenge_id"]})
        assert r.status_code == 202 and r.json()["attempts_left"] == 2
    later(clock, 60)
    r = db_client.post(f"{API}/otp/resend", json={"challenge_id": ch["challenge_id"]})
    assert r.status_code == 429 and r.json()["error"]["code"] == "otp_resend_limit"


def test_unknown_challenges_reveal_nothing(db_client, inbox):
    fake = {"challenge_id": "00000000-0000-0000-0000-000000000000"}
    assert verify(db_client, fake, "123456").json()["error"]["code"] == "otp_challenge_ended"
    assert db_client.post(f"{API}/otp/resend", json=fake).json()["error"]["code"] == "otp_challenge_ended"


# --------------------------------------------------------------- rate limits
def test_codes_per_phone_are_rate_limited(db_client, db_container, inbox, clock, register_farmer, monkeypatch):
    register_farmer()
    monkeypatch.setattr(db_container.settings, "otp_max_sends_per_phone_per_hour", 3)
    statuses = []
    for _ in range(4):
        later(clock, 61)
        r = db_client.post(f"{API}/login", json={"phone": "9876543210", "password": PASSWORD})
        statuses.append(r.status_code)
    assert statuses == [202, 202, 429, 429]  # 1 sent at registration + 2 logins = 3 in the hour
    later(clock, 3600)
    assert db_client.post(f"{API}/login", json={"phone": "9876543210", "password": PASSWORD}).status_code == 202


def test_codes_per_client_address_are_rate_limited(db_client, db_container, inbox, monkeypatch):
    monkeypatch.setattr(db_container.settings, "otp_max_sends_per_client_per_hour", 2)
    assert start_register(db_client, "9000000001").status_code == 202
    assert start_register(db_client, "9000000002").status_code == 202
    r = start_register(db_client, "9000000003")  # same client, a third number
    assert r.status_code == 429 and r.json()["error"]["code"] == "otp_rate_limited"


def test_a_second_login_waits_while_a_code_is_still_open(db_client, inbox, register_farmer, clock):
    register_farmer()
    first = db_client.post(f"{API}/login", json={"phone": "9876543210", "password": PASSWORD})
    assert first.status_code == 202
    again = db_client.post(f"{API}/login", json={"phone": "9876543210", "password": PASSWORD})
    assert again.status_code == 429 and again.json()["error"]["code"] == "otp_cooldown"  # no SMS bombing
    verify(db_client, first.json(), inbox.last_code(PHONE), purpose="login")
    assert db_client.post(f"{API}/login", json={"phone": "9876543210", "password": PASSWORD}).status_code == 202


# ----------------------------------------------------------- SMS providers
def test_an_sms_failure_creates_nothing(db_client, db_container):
    db_container.sms = RecordingSms(fail=True)
    r = start_register(db_client)
    assert r.status_code == 503 and r.json()["error"]["code"] == "sms_unavailable"
    with db_container.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM users")) == 0
        assert conn.scalar(text("SELECT count(*) FROM otp_challenges")) == 0


def test_a_server_without_sms_says_so(db_client, db_container):
    db_container.sms = DisabledSms()
    r = start_register(db_client)
    assert r.status_code == 503 and r.json()["error"]["code"] == "sms_disabled"


def test_development_mode_is_labelled_and_never_claims_an_sms(db_client):
    ch = start_register(db_client).json()  # test settings use dev_console
    assert ch["delivery"] == "development_console" and ch["dev_code"] and len(ch["dev_code"]) == 6
    assert "no SMS was sent" in ch["message"]


def test_development_codes_are_random(db_client, clock):
    codes = set()
    for i in range(5):
        codes.add(start_register(db_client, f"90000000{i:02d}").json()["dev_code"])
    assert len(codes) > 1


def test_android_gateway_request_and_failures(caplog):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = request.read()
        return httpx.Response(202, json={"id": "x", "state": "Pending"})

    sms = AndroidGatewaySms(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="http://192.168.1.50:8080/",
        username="sms",
        password="secret-pass",
    )
    sms.send(PHONE, "Harvestique code: 123456")
    assert seen["url"] == "http://192.168.1.50:8080/message" and seen["auth"].startswith("Basic ")
    assert json.loads(seen["body"]) == {"textMessage": {"text": "Harvestique code: 123456"}, "phoneNumbers": [PHONE]}

    caplog.set_level(logging.DEBUG)
    for transport in (
        httpx.MockTransport(lambda r: httpx.Response(401)),
        httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("phone offline"))),
    ):
        failing = AndroidGatewaySms(
            client=httpx.Client(transport=transport), base_url="http://p:8080", username="u", password="p"
        )
        with pytest.raises(ProviderUnavailableError):
            failing.send(PHONE, "Harvestique code: 654321")
    assert "654321" not in caplog.text and "+919876543210" not in caplog.text  # no codes or full numbers in logs


def test_logout_ends_a_session_issued_after_otp(db_client, register_farmer):
    tokens = register_farmer()["tokens"]
    assert db_client.post(f"{API}/logout", headers=bearer(tokens["access_token"])).status_code == 204
    assert db_client.get(f"{API}/me", headers=bearer(tokens["access_token"])).status_code == 401
    assert db_client.post(f"{API}/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
