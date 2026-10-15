import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.core.enums import UserRole
from app.core.errors import AuthenticationError
from app.core.security import PasswordHasher, TokenCodec, generate_refresh_token, hash_refresh_token
from app.schemas.auth import AdminCreateRequest, validate_password_strength

SECRET = "unit-test-secret-" + "s" * 32
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def _hasher(**kw):
    return PasswordHasher(**{"time_cost": 1, "memory_kib": 8, "parallelism": 1, **kw})


def _codec(**kw):
    args = {"secret": SECRET, "algorithm": "HS256", "issuer": "harvestique", "access_ttl": timedelta(minutes=15)}
    return TokenCodec(**{**args, **kw})


# ------------------------------------------------------------- passwords


def test_hash_is_argon2id_salted_and_verifiable():
    h = _hasher()
    a, b = h.hash("Secret123"), h.hash("Secret123")
    assert a.startswith("$argon2id$") and a != b  # random salt
    assert "Secret123" not in a
    assert h.verify(a, "Secret123")
    assert not h.verify(a, "secret123")


def test_verify_never_raises_on_garbage_hash():
    assert _hasher().verify("not-a-hash", "whatever") is False


def test_needs_rehash_when_parameters_strengthen():
    old = _hasher().hash("Secret123")
    assert not _hasher().needs_rehash(old)
    assert _hasher(time_cost=2).needs_rehash(old)


def test_dummy_verify_is_silent():
    _hasher().verify_dummy("anything")


# ---------------------------------------------------------- refresh tokens


def test_refresh_tokens_are_unique_and_hashed_deterministically():
    t1, t2 = generate_refresh_token(), generate_refresh_token()
    assert t1 != t2 and len(t1) >= 60
    assert hash_refresh_token(t1) == hash_refresh_token(t1)
    assert len(hash_refresh_token(t1)) == 64 and t1 not in hash_refresh_token(t1)


# -------------------------------------------------------------------- JWT


def _issue(codec=None, now=NOW):
    uid, sid = uuid.uuid4(), uuid.uuid4()
    token = (codec or _codec()).encode_access(user_id=uid, role=UserRole.FARMER, session_id=sid, now=now)
    return token, uid, sid


def test_access_token_roundtrip_and_claims():
    token, uid, sid = _issue()
    claims = _codec().decode_access(token, now=NOW + timedelta(minutes=1))
    assert (claims.user_id, claims.session_id, claims.role) == (uid, sid, "farmer")
    assert claims.expires_at - claims.issued_at == timedelta(minutes=15)


def test_expired_token_has_distinct_code():
    token, *_ = _issue()
    with pytest.raises(AuthenticationError) as exc:
        _codec().decode_access(token, now=NOW + timedelta(minutes=15, seconds=1))
    assert exc.value.code == "token_expired"


def test_wrong_secret_rejected():
    token, *_ = _issue(_codec(secret="another-secret-" + "z" * 32))
    with pytest.raises(AuthenticationError) as exc:
        _codec().decode_access(token, now=NOW)
    assert exc.value.code == "invalid_token"


def test_wrong_issuer_rejected():
    token, *_ = _issue(_codec(issuer="someone-else"))
    with pytest.raises(AuthenticationError):
        _codec().decode_access(token, now=NOW)


def test_unsigned_alg_none_token_rejected():
    forged = jwt.encode({"sub": str(uuid.uuid4())}, key="", algorithm="none")
    with pytest.raises(AuthenticationError):
        _codec().decode_access(forged, now=NOW)


def test_missing_required_claim_rejected():
    payload = {"sub": str(uuid.uuid4()), "exp": int((NOW + timedelta(hours=1)).timestamp())}
    with pytest.raises(AuthenticationError):
        _codec().decode_access(jwt.encode(payload, SECRET, algorithm="HS256"), now=NOW)


def test_non_access_token_type_rejected():
    token, *_ = _issue()
    claims = jwt.decode(token, SECRET, algorithms=["HS256"], options={"verify_exp": False, "verify_iat": False})
    claims["typ"] = "refresh"
    with pytest.raises(AuthenticationError):
        _codec().decode_access(jwt.encode(claims, SECRET, algorithm="HS256"), now=NOW)


@pytest.mark.parametrize("junk", ["", "abc", "a.b.c", "Bearer x"])
def test_garbage_rejected(junk):
    with pytest.raises(AuthenticationError):
        _codec().decode_access(junk, now=NOW)


# ----------------------------------------------------------- password policy


@pytest.mark.parametrize("pw", ["Short1", "alllettersnodigit", "12345678901", "a" * 129 + "1"])
def test_weak_passwords_rejected(pw):
    with pytest.raises(ValueError):
        validate_password_strength(pw)


def test_acceptable_password_passes():
    assert validate_password_strength("Harvest123") == "Harvest123"


def test_admin_request_normalises_and_validates():
    ok = AdminCreateRequest(phone="9000000001", password="AdminPass123", full_name="Admin", email="A@X.com")
    assert ok.phone == "+919000000001"
    with pytest.raises(ValidationError):
        AdminCreateRequest(phone="9000000001", password="weak", full_name="Admin")
