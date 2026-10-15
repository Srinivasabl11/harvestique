"""Authentication persistence: refresh tokens (sessions) and login attempts (lockout)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import OtpPurpose
from app.models.base import Base, UUIDPrimaryKeyMixin, enum_column


class RefreshToken(UUIDPrimaryKeyMixin, Base):
    """One opaque refresh token. A *session* is a family of rotated tokens (`family_id`).

    A family is live while it has a token that is neither rotated nor revoked nor expired.
    The access-token claim `sid` equals `family_id`, so revoking the family ends the session
    immediately, not just at access-token expiry.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256 hex, never the raw token
    expires_at: Mapped[datetime]
    rotated_at: Mapped[datetime | None]  # set when exchanged for a new token (reuse => theft signal)
    revoked_at: Mapped[datetime | None]  # set on logout / reuse detection
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class LoginAttempt(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_phone_attempted_at", "phone", "attempted_at"),)

    phone: Mapped[str] = mapped_column(String(16))
    succeeded: Mapped[bool]
    attempted_at: Mapped[datetime]


class OtpChallenge(UUIDPrimaryKeyMixin, Base):
    """One pending phone-verification step (registration or login).

    The code is never stored: only HMAC-SHA256(server secret, challenge id + code). A challenge is single-use
    (`consumed_at`), expires, and allows `max_attempts` wrong codes in total, resends included. A *decoy* challenge
    answers a registration for a number that already has an account: the response looks the same (no account
    enumeration) but no SMS is sent and no code can ever pass.
    """

    __tablename__ = "otp_challenges"
    __table_args__ = (
        Index("ix_otp_challenges_phone_created_at", "phone", "created_at"),
        Index("ix_otp_challenges_client_created_at", "client", "created_at"),
    )

    # SET NULL, not CASCADE: replacing an abandoned sign-up must not erase the send history the rate limits count
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    purpose: Mapped[OtpPurpose] = mapped_column(enum_column(OtpPurpose, name="otp_purpose", length=16))
    phone: Mapped[str] = mapped_column(String(16))
    code_hash: Mapped[str] = mapped_column(String(64))
    decoy: Mapped[bool] = mapped_column(default=False, server_default=false())
    expires_at: Mapped[datetime]
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    sends: Mapped[int] = mapped_column(default=1, server_default="1")
    last_sent_at: Mapped[datetime]
    consumed_at: Mapped[datetime | None]
    client: Mapped[str | None] = mapped_column(String(64))  # requester address, for per-client rate limits
    created_at: Mapped[datetime]
