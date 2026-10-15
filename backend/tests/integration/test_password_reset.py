"""Forgot password: phone code -> new password -> normal sign-in. No enumeration, single-use codes, rate limited."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.providers.sms.providers import RecordingSms
from tests.conftest import PASSWORD, bearer, login_and_verify

pytestmark = pytest.mark.integration
API = "/api/v1/auth"
PHONE = "+919876543210"
NEW = "NewHarvest456"


def forgot(client, phone="9876543210"):
    return client.post(f"{API}/password/forgot", json={"phone": phone})


def reset(client, challenge, code, password=NEW):
    return client.post(
        f"{API}/password/reset",
        json={"challenge_id": challenge["challenge_id"], "code": code, "new_password": password},
    )


def test_reset_changes_the_password_and_signs_out_every_session(db_client, register_farmer):
    old = register_farmer()["tokens"]
    r = forgot(db_client)
    assert r.status_code == 202 and r.json()["purpose"] == "password_reset" and "tokens" not in r.json()
    ch = r.json()
    assert reset(db_client, ch, ch["dev_code"]).status_code == 204
    assert db_client.get(f"{API}/me", headers=bearer(old["access_token"])).status_code == 401  # signed out
    assert db_client.post(f"{API}/refresh", json={"refresh_token": old["refresh_token"]}).status_code == 401
    wrong = db_client.post(f"{API}/login", json={"phone": "9876543210", "password": PASSWORD})
    assert wrong.status_code == 401  # the old password no longer works
    assert login_and_verify(db_client, "9876543210", NEW)["tokens"]["access_token"]  # normal sign-in (with code)


def test_a_reset_code_works_once_and_only_for_resets(db_client, register_farmer):
    register_farmer()
    ch = forgot(db_client).json()
    login_verify = db_client.post(
        f"{API}/login/verify", json={"challenge_id": ch["challenge_id"], "code": ch["dev_code"]}
    )
    assert login_verify.json()["error"]["code"] == "otp_challenge_ended"  # not a sign-in code
    assert reset(db_client, ch, ch["dev_code"]).status_code == 204
    again = reset(db_client, ch, ch["dev_code"], password="Another789")
    assert again.status_code == 401 and again.json()["error"]["code"] == "otp_challenge_ended"


def test_unknown_numbers_get_the_same_answer_and_no_sms(db_client, db_container, register_farmer):
    register_farmer()
    db_container.sms = RecordingSms()
    known = forgot(db_client, "9876543210")
    unknown = forgot(db_client, "9000011111")
    assert known.status_code == unknown.status_code == 202
    assert set(known.json()) == set(unknown.json())
    assert known.json()["message"].replace("+91******3210", "X") == unknown.json()["message"].replace(
        "+91******1111", "X"
    )
    assert [to for to, _ in db_container.sms.sent] == [PHONE]  # only the real account got a code
    r = reset(db_client, unknown.json(), "123456")
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_otp"


def test_an_unfinished_sign_up_cannot_be_taken_over_by_a_reset(db_client, db_container, fixed_clock):
    from datetime import timedelta

    body = {"role": "farmer", "phone": "9876543210", "password": PASSWORD, "full_name": "Pending Person"}
    assert db_client.post(f"{API}/register", json=body).status_code == 202  # never verified
    fixed_clock.advance_to(fixed_clock.now() + timedelta(seconds=61))  # past the sign-up code's resend cooldown
    ch = forgot(db_client).json()
    assert ch["dev_code"] is None  # treated like an unknown number
    with db_container.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM otp_challenges WHERE purpose='password_reset' AND decoy")) == 1


def test_wrong_codes_lock_the_reset(db_client, register_farmer):
    register_farmer()
    ch = forgot(db_client).json()
    bad = f"{(int(ch['dev_code']) + 1) % 1000000:06d}"
    for left in (4, 3, 2, 1, 0):
        r = reset(db_client, ch, bad)
        assert r.json()["error"]["details"]["attempts_left"] == left
    r = reset(db_client, ch, ch["dev_code"])
    assert r.status_code == 401 and r.json()["error"]["code"] == "otp_attempts_exhausted"
    assert login_and_verify(db_client, "9876543210", PASSWORD)  # the password did not change


@pytest.mark.parametrize("weak", ["short1", "lettersonly", "1234567890"])
def test_the_new_password_must_be_strong_and_a_weak_one_spends_no_attempt(db_client, register_farmer, weak):
    register_farmer()
    ch = forgot(db_client).json()
    r = reset(db_client, ch, ch["dev_code"], password=weak)
    assert r.status_code == 422 and weak not in r.text
    assert reset(db_client, ch, ch["dev_code"]).status_code == 204  # the code is still valid


def test_reset_requests_share_the_otp_rate_limits(db_client, db_container, register_farmer, fixed_clock, monkeypatch):
    from datetime import timedelta

    register_farmer()
    monkeypatch.setattr(db_container.settings, "otp_max_sends_per_phone_per_hour", 2)  # 1 used at registration
    assert forgot(db_client).status_code == 202
    fixed_clock.advance_to(fixed_clock.now() + timedelta(seconds=61))
    r = forgot(db_client)
    assert r.status_code == 429 and r.json()["error"]["code"] == "otp_rate_limited"
    early = forgot(db_client, "9000011111")  # unknown number: decoys do not count against a phone, but cooldown...
    assert early.status_code == 202


def test_the_tour_version_is_stored_per_account_and_never_goes_back(db_client, register_farmer, register_buyer):
    farmer = register_farmer()
    buyer = register_buyer()
    assert farmer["user"]["tour_version_seen"] == 0
    h = bearer(farmer["tokens"]["access_token"])
    assert db_client.post(f"{API}/me/tour", headers=h, json={"version": 1}).json()["tour_version_seen"] == 1
    assert db_client.post(f"{API}/me/tour", headers=h, json={"version": 0}).json()["tour_version_seen"] == 1
    assert db_client.get(f"{API}/me", headers=bearer(buyer["tokens"]["access_token"])).json()["tour_version_seen"] == 0
    assert db_client.post(f"{API}/me/tour", json={"version": 1}).status_code == 401
