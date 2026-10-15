"""Refresh-token (session) and login-attempt persistence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session

from app.models.auth import LoginAttempt, RefreshToken


class RefreshTokenRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, token: RefreshToken) -> RefreshToken:
        self.session.add(token)
        self.session.flush()
        return token

    def get_by_hash_for_update(self, token_hash: str) -> RefreshToken | None:
        """Row-locked read: concurrent refreshes of one token serialise here."""
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        return self.session.scalar(stmt)

    def session_is_live(self, family_id: uuid.UUID, now: datetime) -> bool:
        stmt = select(
            exists().where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.rotated_at.is_(None),
                RefreshToken.expires_at > now,
            )
        )
        return bool(self.session.scalar(stmt))

    def revoke_all_for_user(self, user_id: uuid.UUID, now: datetime) -> None:
        """Every session of the user ends (after a password reset)."""
        self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    def revoke_family(self, family_id: uuid.UUID, now: datetime) -> None:
        self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )


class LoginAttemptRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(self, *, phone: str, succeeded: bool, at: datetime) -> None:
        self.session.add(LoginAttempt(phone=phone, succeeded=succeeded, attempted_at=at))
        self.session.flush()

    def consecutive_failures(self, phone: str, *, since: datetime) -> tuple[int, datetime | None, datetime | None]:
        """Failures after `since` and after the phone's last successful login.

        Returns (count, time of the oldest such failure, time of the most recent one).
        """
        last_success = (
            select(func.max(LoginAttempt.attempted_at))
            .where(LoginAttempt.phone == phone, LoginAttempt.succeeded.is_(True))
            .scalar_subquery()
        )
        stmt = select(func.count(), func.min(LoginAttempt.attempted_at), func.max(LoginAttempt.attempted_at)).where(
            LoginAttempt.phone == phone,
            LoginAttempt.succeeded.is_(False),
            LoginAttempt.attempted_at > since,
            LoginAttempt.attempted_at > func.coalesce(last_success, since),
        )
        count, earliest, latest = self.session.execute(stmt).one()
        return int(count), earliest, latest
