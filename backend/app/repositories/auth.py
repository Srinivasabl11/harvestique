"""Refresh-token (session), login-attempt and one-time-code persistence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session

from app.models.auth import LoginAttempt, OtpChallenge, RefreshToken


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

    def consecutive_failures(self, phone: str, *, since: datetime) -> tuple[int, datetime | None]:
        """Failures after `since` and after the phone's last successful login.

        Returns (count, time of the most recent failure).
        """
        last_success = (
            select(func.max(LoginAttempt.attempted_at))
            .where(LoginAttempt.phone == phone, LoginAttempt.succeeded.is_(True))
            .scalar_subquery()
        )
        stmt = select(func.count(), func.max(LoginAttempt.attempted_at)).where(
            LoginAttempt.phone == phone,
            LoginAttempt.succeeded.is_(False),
            LoginAttempt.attempted_at > since,
            LoginAttempt.attempted_at > func.coalesce(last_success, since),
        )
        count, latest = self.session.execute(stmt).one()
        return int(count), latest


class OtpChallengeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, challenge: OtpChallenge) -> OtpChallenge:
        self.session.add(challenge)
        self.session.flush()
        return challenge

    def get_for_update(self, challenge_id: uuid.UUID) -> OtpChallenge | None:
        """Row-locked: concurrent guesses against one challenge are counted one at a time."""
        return self.session.scalar(select(OtpChallenge).where(OtpChallenge.id == challenge_id).with_for_update())

    def sends_since(self, *, since: datetime, phone: str | None = None, client: str | None = None) -> int:
        """Codes sent (first sends and resends) to a phone, or requested from a client address, since `since`.

        Decoys (registrations of an existing number) send no SMS, so they do not count against that PHONE - otherwise
        anyone could block a real user's sign-in by "registering" their number - but they do count against the
        requesting CLIENT."""
        stmt = select(func.coalesce(func.sum(OtpChallenge.sends), 0)).where(OtpChallenge.created_at > since)
        if phone is not None:
            stmt = stmt.where(OtpChallenge.phone == phone, OtpChallenge.decoy.is_(False))
        if client is not None:
            stmt = stmt.where(OtpChallenge.client == client)
        return int(self.session.scalar(stmt) or 0)

    def last_open_send_at(self, phone: str, max_attempts: int) -> datetime | None:
        """When a still-usable code was last sent to this phone. A verified code, or one whose wrong attempts are
        used up, does not hold up the next one."""
        stmt = select(func.max(OtpChallenge.last_sent_at)).where(
            OtpChallenge.phone == phone,
            OtpChallenge.consumed_at.is_(None),
            OtpChallenge.decoy.is_(False),
            OtpChallenge.attempts < max_attempts,
        )
        return self.session.scalar(stmt)
