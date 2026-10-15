"""Security primitives: password hashing, access-token (JWT) codec, refresh-token helpers.

Pure infrastructure: no database, no HTTP. Time is always passed in (`now`) so the
injected Clock - and therefore tests - control expiry.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cached_property
from typing import Any

import argon2
import jwt
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.enums import UserRole
from app.core.errors import AuthenticationError

# ---------------------------------------------------------------- passwords


class PasswordHasher:
    """Argon2id hashing. `verify` never raises on a bad password or malformed hash."""

    def __init__(self, *, time_cost: int, memory_kib: int, parallelism: int) -> None:
        self._ph = argon2.PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_kib,
            parallelism=parallelism,
            type=argon2.Type.ID,
        )

    def hash(self, password: str) -> str:
        return self._ph.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._ph.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        return self._ph.check_needs_rehash(password_hash)

    @cached_property
    def _dummy_hash(self) -> str:
        return self._ph.hash("harvestique-timing-equaliser")

    def verify_dummy(self, password: str) -> None:
        """Burn the same CPU as a real verification (unknown-phone logins)."""
        self.verify(self._dummy_hash, password)


# ----------------------------------------------------------- refresh tokens


def generate_refresh_token() -> str:
    """Opaque 384-bit random token. Only its SHA-256 digest is ever stored."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# -------------------------------------------------------------- access JWTs

_REQUIRED_CLAIMS = ["sub", "sid", "jti", "iat", "exp", "iss", "typ", "role"]


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    role: str
    jti: str
    issued_at: datetime
    expires_at: datetime


class TokenCodec:
    """Signs and verifies short-lived access tokens.

    Claims: sub=user id, sid=session (refresh-token family) id, role (informational -
    authorisation uses the database role), jti, iat, exp, iss, typ="access".
    """

    def __init__(self, *, secret: str, algorithm: str, issuer: str, access_ttl: timedelta) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._issuer = issuer
        self.access_ttl = access_ttl

    def encode_access(self, *, user_id: uuid.UUID, role: UserRole, session_id: uuid.UUID, now: datetime) -> str:
        payload: dict[str, Any] = {
            "sub": str(user_id),
            "sid": str(session_id),
            "role": role.value,
            "jti": uuid.uuid4().hex,
            "iat": int(now.timestamp()),
            "exp": int((now + self.access_ttl).timestamp()),
            "iss": self._issuer,
            "typ": "access",
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def decode_access(self, token: str, *, now: datetime) -> AccessClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],  # pinned: rejects alg=none / algorithm confusion
                issuer=self._issuer,
                options={
                    "require": _REQUIRED_CLAIMS,
                    # Expiry is checked below against the injected clock, not the wall clock.
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
            if payload["typ"] != "access":
                raise AuthenticationError("Invalid access token", code="invalid_token")
            claims = AccessClaims(
                user_id=uuid.UUID(str(payload["sub"])),
                session_id=uuid.UUID(str(payload["sid"])),
                role=str(payload["role"]),
                jti=str(payload["jti"]),
                issued_at=datetime.fromtimestamp(int(payload["iat"]), tz=now.tzinfo),
                expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=now.tzinfo),
            )
        except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
            raise AuthenticationError("Invalid access token", code="invalid_token") from exc
        if claims.expires_at <= now:
            raise AuthenticationError("Access token has expired", code="token_expired")
        return claims
