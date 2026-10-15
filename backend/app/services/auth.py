"""Authentication use cases: register, login, password change, admin password reset, refresh, logout,
authenticate, create-admin.

Sign-in is phone + password (no SMS codes). New sign-ups can wait for an admin's approval (NEW_ACCOUNT_ACCESS=pending),
which is how a tester's identity is checked. Forgotten passwords are reset by an admin, who gets a one-time temporary
password; the person must set their own before any session is issued.

HTTP-agnostic. Commits its own transactions (the request session is rolled back only
on unexpected exceptions, so failure paths that must persist state - failed-login
counters, reuse-detection revocation - commit *before* raising).
"""

from __future__ import annotations

import logging
import math
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.config import Settings
from app.core.enums import AccessStatus, UserRole
from app.core.errors import (
    AuthenticationError,
    ConflictError,
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
    TooManyRequestsError,
)
from app.core.security import (
    PasswordHasher,
    TokenCodec,
    generate_refresh_token,
    hash_refresh_token,
)
from app.models.auth import RefreshToken
from app.models.profiles import BuyerProfile, FarmerProfile
from app.models.user import User
from app.repositories.auth import LoginAttemptRepository, RefreshTokenRepository
from app.repositories.users import UserRepository
from app.schemas.auth import (
    AccessUpdate,
    AdminCreateRequest,
    AuthResponse,
    CurrentUser,
    LoginRequest,
    PasswordChangeRequest,
    RegisterBuyerRequest,
    RegisterPayload,
    RegistrationOut,
    TemporaryPasswordOut,
    TokenPair,
    UserRead,
)

logger = logging.getLogger(__name__)

INVALID_CREDENTIALS = "Invalid phone number or password"
SIGN_UP_RECEIVED = (
    "Thank you. Your account is waiting for approval by the Harvestique team. "
    "You can sign in with your password once it is approved."
)
ACCESS_DENIED = {
    AccessStatus.PENDING: (
        "Your account is waiting for approval by the Harvestique team. Please try again later.",
        "access_pending",
    ),
    AccessStatus.SUSPENDED: ("Your access has been suspended by the Harvestique team.", "access_suspended"),
    AccessStatus.REVOKED: ("Your access to Harvestique has been removed.", "access_revoked"),
}
# Temporary passwords: no look-alike characters (0/o, 1/l/i), lower case only, so they are easy to read out and type.
_TEMP_LETTERS = "abcdefghjkmnpqrstuvwxyz"
_TEMP_DIGITS = "23456789"


def generate_temporary_password() -> str:
    """12 random characters (about 59 bits) shown as xxxx-xxxx-xxxx; always has a letter and a digit."""
    alphabet = _TEMP_LETTERS + _TEMP_DIGITS
    while True:
        chars = "".join(secrets.choice(alphabet) for _ in range(12))
        if any(c in _TEMP_LETTERS for c in chars) and any(c in _TEMP_DIGITS for c in chars):
            return "-".join(chars[i : i + 4] for i in range(0, 12, 4))


class AuthService:
    def __init__(
        self,
        *,
        session: Session,
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        login_attempts: LoginAttemptRepository,
        hasher: PasswordHasher,
        codec: TokenCodec,
        clock: Clock,
        settings: Settings,
    ) -> None:
        self._session = session
        self._users = users
        self._refresh = refresh_tokens
        self._attempts = login_attempts
        self._hasher = hasher
        self._codec = codec
        self._clock = clock
        self._settings = settings

    # ------------------------------------------------------------ register

    def register(self, payload: RegisterPayload) -> RegistrationOut:
        """Create a farmer or buyer account.

        With NEW_ACCOUNT_ACCESS=approved (development) the account is usable at once and signed in. With "pending"
        (production) it waits for an admin and no tokens are issued; a number that already has an account gets that
        same answer and nothing is created or changed, so sign-up cannot reveal or take over who is registered.
        """
        now = self._clock.now()
        pending = self._settings.new_account_access == "pending"
        existing = self._users.get_by_phone(payload.phone)
        if existing is not None and not existing.registration_pending:
            if not pending:
                raise ConflictError("This phone number is already registered", code="phone_already_registered")
            self._hasher.hash(payload.password)  # same work as a real sign-up: the timing reveals nothing either
            logger.info("sign-up for an existing number answered without creating anything")
            return RegistrationOut(status="pending", message=SIGN_UP_RECEIVED)
        if self._users.count_sign_ups_since(now - timedelta(hours=1)) >= self._settings.registrations_max_per_hour:
            raise TooManyRequestsError(
                "Too many new accounts were created in the last hour. Please try again later.",
                code="registration_rate_limited",
                details={"retry_after_seconds": 3600},
                headers={"Retry-After": "3600"},
            )
        if existing is not None:  # a sign-up from the SMS-code era that was never finished: holds no data
            self._session.delete(existing)
            self._session.flush()
        user = self._build_user(
            phone=payload.phone,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            role=UserRole.BUYER if isinstance(payload, RegisterBuyerRequest) else UserRole.FARMER,
        )
        if pending:
            user.access_status = AccessStatus.PENDING
        if isinstance(payload, RegisterBuyerRequest):
            user.buyer_profile = BuyerProfile(**payload.profile.model_dump())
        else:
            user.farmer_profile = FarmerProfile(**payload.profile.model_dump())
        self._persist_new_user(user)
        if pending:
            self._session.commit()
            logger.info("sign-up waiting for approval id=%s role=%s", user.id, user.role.value)
            return RegistrationOut(status="pending", message=SIGN_UP_RECEIVED)
        user.last_login_at = now
        tokens = self._issue_tokens(user, family_id=None, now=now)
        self._session.commit()
        logger.info("registered id=%s role=%s", user.id, user.role.value)
        return RegistrationOut(
            status="approved", message="Account created.", user=UserRead.model_validate(user), tokens=tokens
        )

    # ----------------------------------------------------------------- tour

    def mark_tour_seen(self, current: CurrentUser, version: int) -> UserRead:
        user = self._users.get(current.user_id)
        if user is None:
            raise AuthenticationError("Invalid access token", code="invalid_token")
        user.tour_version_seen = max(user.tour_version_seen, version)  # never goes back
        self._session.commit()
        return UserRead.model_validate(user)

    def create_admin(self, payload: AdminCreateRequest) -> UserRead:
        """Operator action (CLI). Admins are never created through the public API."""
        user = self._build_user(
            phone=payload.phone,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            role=UserRole.ADMIN,
        )
        self._persist_new_user(user)
        self._session.commit()
        logger.info("admin created id=%s", user.id)
        return UserRead.model_validate(user)

    # --------------------------------------------------------------- login

    def login(self, payload: LoginRequest) -> AuthResponse:
        """Phone + password. Failures are counted per phone (lockout); a blocked or waiting account gets no session,
        and neither does one holding an admin-issued temporary password (it must be changed first)."""
        now = self._clock.now()
        user = self._check_password(payload.phone, payload.password, now)
        if user.must_change_password:
            self._session.commit()  # keep the successful-attempt record
            raise PermissionDeniedError("Please set a new password to continue.", code="password_change_required")
        user.last_login_at = now
        tokens = self._issue_tokens(user, family_id=None, now=now)
        self._session.commit()
        return AuthResponse(user=UserRead.model_validate(user), tokens=tokens)

    # ----------------------------------------------------------- passwords

    def change_password(self, payload: PasswordChangeRequest) -> AuthResponse:
        """Replace the password, proven by the current (or temporary) one. Every other session is signed out and a
        fresh one is returned, so this also finishes the sign-in after an admin reset."""
        now = self._clock.now()
        user = self._check_password(payload.phone, payload.current_password, now)
        if payload.new_password == payload.current_password:
            self._session.commit()  # keep the successful-attempt record
            raise DomainValidationError(
                "The new password must be different from the current one.", code="password_unchanged"
            )
        user.password_hash = self._hasher.hash(payload.new_password)
        user.must_change_password = False
        self._refresh.revoke_all_for_user(user.id, now)
        user.last_login_at = now
        tokens = self._issue_tokens(user, family_id=None, now=now)
        self._session.commit()
        logger.info("password changed user_id=%s", user.id)
        return AuthResponse(user=UserRead.model_validate(user), tokens=tokens)

    def admin_reset_password(self, admin: CurrentUser, user_id: uuid.UUID) -> TemporaryPasswordOut:
        """An admin gives a farmer or buyer a temporary password (after checking who is asking, outside the app).
        Every session of that person ends, any sign-in lockout is cleared, and they must choose a new password at
        their next sign-in. Admin passwords are set only with the operator command (app.cli.set_password)."""
        user = self._users.get(user_id)
        if user is None:
            raise NotFoundError("User not found")
        if user.role is UserRole.ADMIN:
            raise PermissionDeniedError("Admin passwords cannot be reset here", code="admin_password_fixed")
        now = self._clock.now()
        temporary = generate_temporary_password()
        user.password_hash = self._hasher.hash(temporary)
        user.must_change_password = True
        self._refresh.revoke_all_for_user(user.id, now)
        self._attempts.record(phone=user.phone, succeeded=True, at=now)  # clears a lockout from forgotten guesses
        self._session.commit()
        logger.info("temporary password issued user_id=%s by admin_id=%s", user.id, admin.user_id)
        return TemporaryPasswordOut(
            user=UserRead.model_validate(user),
            temporary_password=temporary,
            message=(
                "Give this temporary password to the person privately. It is shown only now. At their next sign-in "
                "they must choose a new password; all their devices have been signed out."
            ),
        )

    def operator_set_password(self, phone: str, password: str) -> UserRead:
        """Operator command (CLI, any role including admin): set a password chosen with the person. Sessions end and
        any lockout is cleared; no change is forced."""
        user = self._users.get_by_phone(phone)
        if user is None:
            raise NotFoundError("No account uses this phone number")
        now = self._clock.now()
        user.password_hash = self._hasher.hash(password)
        user.must_change_password = False
        self._refresh.revoke_all_for_user(user.id, now)
        self._attempts.record(phone=user.phone, succeeded=True, at=now)
        self._session.commit()
        logger.info("password set by operator user_id=%s", user.id)
        return UserRead.model_validate(user)

    # ------------------------------------------------------------- refresh

    def refresh(self, raw_refresh_token: str) -> TokenPair:
        now = self._clock.now()
        token = self._refresh.get_by_hash_for_update(hash_refresh_token(raw_refresh_token))
        if token is None:
            raise AuthenticationError("Invalid refresh token", code="invalid_refresh_token")
        if token.revoked_at is not None:
            raise AuthenticationError("This session has ended; please sign in again", code="session_revoked")
        if token.rotated_at is not None:
            # An already-exchanged token came back: either a replay or a stolen copy.
            # Kill the whole session so neither party keeps access.
            self._refresh.revoke_family(token.family_id, now)
            self._session.commit()
            logger.warning("refresh token reuse detected user_id=%s session=%s", token.user_id, token.family_id)
            raise AuthenticationError(
                "Refresh token was already used; please sign in again", code="refresh_token_reused"
            )
        if token.expires_at <= now:
            raise AuthenticationError("Refresh token has expired", code="refresh_token_expired")

        user = self._users.get(token.user_id)
        if user is None:
            raise AuthenticationError("Invalid refresh token", code="invalid_refresh_token")
        self._require_access(user)

        token.rotated_at = now
        tokens = self._issue_tokens(user, family_id=token.family_id, now=now)
        self._session.commit()
        return tokens

    # -------------------------------------------------------------- logout

    def logout(self, current: CurrentUser) -> None:
        """End the caller's current session (this device). Other sessions are untouched."""
        self._refresh.revoke_family(current.session_id, self._clock.now())
        self._session.commit()

    # ------------------------------------------------------- authenticate

    def authenticate(self, access_token: str) -> CurrentUser:
        """Validate a bearer token and return the caller. Raises 401/403 AppErrors.

        Beyond signature/expiry it checks, against the database, that the user still
        exists and is active and that the session was not logged out or revoked -
        so logout and account disabling take effect immediately.
        Role comes from the database, never from the token.
        """
        now = self._clock.now()
        claims = self._codec.decode_access(access_token, now=now)
        user = self._users.get(claims.user_id)
        if user is None:
            raise AuthenticationError("Invalid access token", code="invalid_token")
        self._require_access(user)
        if not self._refresh.session_is_live(claims.session_id, now):
            raise AuthenticationError("This session has ended; please sign in again", code="session_revoked")
        return CurrentUser(user_id=user.id, role=user.role, session_id=claims.session_id)

    # ------------------------------------------------------ tester access

    def set_access(self, admin: CurrentUser, user_id: uuid.UUID, payload: AccessUpdate) -> UserRead:
        """Admin decision on one account. Takes effect on that person's next request (every request checks it)."""
        user = self._users.get(user_id)
        if user is None:
            raise NotFoundError("User not found")
        if user.role is UserRole.ADMIN:
            raise PermissionDeniedError("Admin accounts cannot be changed here", code="admin_access_fixed")
        now = self._clock.now()
        user.access_status = AccessStatus(payload.status)
        user.access_changed_at = now
        if user.access_status is AccessStatus.REVOKED:
            self._refresh.revoke_all_for_user(user.id, now)
        self._session.commit()
        logger.info("access set to %s user_id=%s by admin_id=%s", payload.status, user.id, admin.user_id)
        return UserRead.model_validate(user)

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _require_access(user: User) -> None:
        if not user.is_active:
            raise PermissionDeniedError("This account has been disabled", code="account_disabled")
        denied = ACCESS_DENIED.get(user.access_status)
        if denied is not None:
            raise PermissionDeniedError(denied[0], code=denied[1])

    def _build_user(self, *, phone: str, email: str | None, password: str, full_name: str, role: UserRole) -> User:
        if self._users.get_by_phone(phone) is not None:
            raise ConflictError("This phone number is already registered", code="phone_already_registered")
        if email and self._users.get_by_email(email) is not None:
            raise ConflictError("This email is already registered", code="email_already_registered")
        return User(
            phone=phone,
            email=email,
            password_hash=self._hasher.hash(password),
            full_name=full_name,
            role=role,
        )

    def _persist_new_user(self, user: User) -> None:
        try:
            self._users.add(user)  # flushes: assigns id, surfaces unique violations
        except IntegrityError as exc:  # lost a race with a concurrent identical sign-up
            self._session.rollback()
            raise ConflictError("This phone number or email is already registered", code="already_registered") from exc

    def _issue_tokens(self, user: User, *, family_id: uuid.UUID | None, now: datetime) -> TokenPair:
        session_id = family_id or uuid.uuid4()
        raw = generate_refresh_token()
        self._refresh.add(
            RefreshToken(
                user_id=user.id,
                family_id=session_id,
                token_hash=hash_refresh_token(raw),
                expires_at=now + timedelta(days=self._settings.refresh_token_expire_days),
            )
        )
        access = self._codec.encode_access(user_id=user.id, role=user.role, session_id=session_id, now=now)
        return TokenPair(
            access_token=access,
            refresh_token=raw,
            expires_in=int(self._codec.access_ttl.total_seconds()),
        )

    def _check_password(self, phone: str, password: str, now: datetime) -> User:
        """The credential check shared by login and password change: lockout first, then the password (failures are
        recorded and committed before raising), then the account's access. Records the successful attempt."""
        self._enforce_not_locked(phone, now)
        user = self._users.get_by_phone(phone)
        if user is None or user.registration_pending:
            self._hasher.verify_dummy(password)  # equalise timing: no phone enumeration
            password_ok = False
        else:
            password_ok = self._hasher.verify(user.password_hash, password)
        if user is None or not password_ok:
            self._attempts.record(phone=phone, succeeded=False, at=now)
            self._session.commit()  # persist the failure counter before raising
            raise AuthenticationError(INVALID_CREDENTIALS, code="invalid_credentials")
        self._require_access(user)
        if self._hasher.needs_rehash(user.password_hash):
            user.password_hash = self._hasher.hash(password)
        self._attempts.record(phone=phone, succeeded=True, at=now)
        return user

    def _enforce_not_locked(self, phone: str, now: datetime) -> None:
        """Two windows per phone: N failures in a short window (locked until it has passed since the LAST failure),
        and a daily cap (locked until the OLDEST failure of the day is 24 hours old)."""
        windows = (
            (timedelta(minutes=self._settings.login_lockout_minutes), self._settings.login_max_failed_attempts, False),
            (timedelta(days=1), self._settings.login_max_failed_attempts_per_day, True),
        )
        for window, limit, from_oldest in windows:
            failures, earliest, latest = self._attempts.consecutive_failures(phone, since=now - window)
            if failures < limit or earliest is None or latest is None:
                continue
            until = (earliest if from_oldest else latest) + window
            retry_after = max(1, math.ceil((until - now).total_seconds()))
            raise TooManyRequestsError(
                "Too many failed sign-in attempts. Try again later.",
                code="account_locked",
                details={"retry_after_seconds": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
