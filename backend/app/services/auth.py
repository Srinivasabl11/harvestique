"""Authentication use cases: register, login (both finished by a one-time SMS code), refresh, logout,
authenticate, create-admin.

HTTP-agnostic. Commits its own transactions (the request session is rolled back only
on unexpected exceptions, so failure paths that must persist state - failed-login
counters, reuse-detection revocation - commit *before* raising).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.config import Settings
from app.core.enums import OtpPurpose, UserRole
from app.core.errors import (
    AuthenticationError,
    ConflictError,
    PermissionDeniedError,
    ProviderUnavailableError,
    TooManyRequestsError,
)
from app.core.security import (
    PasswordHasher,
    TokenCodec,
    generate_refresh_token,
    hash_refresh_token,
)
from app.models.auth import OtpChallenge, RefreshToken
from app.models.profiles import BuyerProfile, FarmerProfile
from app.models.user import User
from app.providers.sms.base import SmsSender, mask_phone
from app.repositories.auth import LoginAttemptRepository, OtpChallengeRepository, RefreshTokenRepository
from app.repositories.users import UserRepository
from app.schemas.auth import (
    AdminCreateRequest,
    AuthResponse,
    CurrentUser,
    LoginRequest,
    OtpChallengeOut,
    OtpResendRequest,
    OtpVerifyRequest,
    PasswordForgotRequest,
    PasswordResetRequest,
    RegisterBuyerRequest,
    RegisterPayload,
    TokenPair,
    UserRead,
)

logger = logging.getLogger(__name__)

INVALID_CREDENTIALS = "Invalid phone number or password"
WRONG_CODE = "The code is not correct"
CHALLENGE_ENDED = "This verification has ended. Please start again."


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
        otps: OtpChallengeRepository,
        sms: SmsSender,
    ) -> None:
        self._session = session
        self._users = users
        self._refresh = refresh_tokens
        self._attempts = login_attempts
        self._hasher = hasher
        self._codec = codec
        self._clock = clock
        self._settings = settings
        self._otps = otps
        self._sms = sms
        # codes are stored as HMAC(server key, challenge id + code): a database copy alone cannot test guesses
        self._otp_key = hashlib.sha256(
            b"harvestique-otp:" + settings.jwt_secret_key.get_secret_value().encode()
        ).digest()

    # ------------------------------------------------------------ register

    def register(self, payload: RegisterPayload, *, client: str | None = None) -> OtpChallengeOut:
        """Step 1: create the account as *pending* and send a code. Tokens come only from `verify`.

        A number that already has an account gets the same answer (a decoy challenge, no SMS, no code can pass),
        so this endpoint does not reveal who is registered. An unfinished earlier sign-up for the number is replaced.
        """
        self._require_sms()
        now = self._clock.now()
        self._check_send_limits(payload.phone, client, now)
        existing = self._users.get_by_phone(payload.phone)
        if existing is not None and not existing.registration_pending:
            challenge, code = self._new_challenge(None, OtpPurpose.REGISTER, payload.phone, client, now, decoy=True)
            self._session.commit()
            logger.info("registration for an existing number answered with a decoy challenge")
            return self._challenge_out(challenge, code, now)
        if existing is not None:  # an abandoned sign-up: never verified, never signed in, holds no data
            self._session.delete(existing)
            self._session.flush()
        user = self._build_user(
            phone=payload.phone,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            role=UserRole.BUYER if isinstance(payload, RegisterBuyerRequest) else UserRole.FARMER,
        )
        user.registration_pending = True
        if isinstance(payload, RegisterBuyerRequest):
            user.buyer_profile = BuyerProfile(**payload.profile.model_dump())
        else:
            user.farmer_profile = FarmerProfile(**payload.profile.model_dump())
        self._persist_new_user(user)
        challenge, code = self._new_challenge(user.id, OtpPurpose.REGISTER, payload.phone, client, now)
        self._deliver(challenge, code)  # raises before commit: no half-created account if the SMS fails
        self._session.commit()
        logger.info("registration started id=%s role=%s", user.id, user.role.value)
        return self._challenge_out(challenge, code, now)

    def verify(self, purpose: OtpPurpose, payload: OtpVerifyRequest) -> AuthResponse:
        """Step 2 (registration or login): check the code; only now are tokens issued."""
        now = self._clock.now()
        _challenge, user = self._consume(purpose, payload.challenge_id, payload.code, now)
        user.phone_verified_at = user.phone_verified_at or now
        user.registration_pending = False
        user.last_login_at = now
        tokens = self._issue_tokens(user, family_id=None, now=now)
        self._session.commit()
        logger.info("phone verified (%s) user_id=%s", purpose.value, user.id)
        return AuthResponse(user=UserRead.model_validate(user), tokens=tokens)

    # ------------------------------------------------------- password reset

    def forgot_password(self, payload: PasswordForgotRequest, *, client: str | None = None) -> OtpChallengeOut:
        """Step 1 of a reset: a code goes to the number IF it has a (finished) account. The answer is the same
        either way, so the endpoint cannot be used to find out who is registered."""
        self._require_sms()
        now = self._clock.now()
        self._check_send_limits(payload.phone, client, now)
        user = self._users.get_by_phone(payload.phone)
        if user is None or user.registration_pending or not user.is_active:
            challenge, code = self._new_challenge(
                None, OtpPurpose.PASSWORD_RESET, payload.phone, client, now, decoy=True
            )
            self._session.commit()
            return self._challenge_out(challenge, code, now)
        challenge, code = self._new_challenge(user.id, OtpPurpose.PASSWORD_RESET, user.phone, client, now)
        self._deliver(challenge, code)
        self._session.commit()
        logger.info("password reset requested user_id=%s", user.id)
        return self._challenge_out(challenge, code, now)

    def reset_password(self, payload: PasswordResetRequest) -> None:
        """Step 2: the code and a new password. The code is single-use; every existing session is signed out, and
        the person then signs in normally (password + login code)."""
        now = self._clock.now()
        _challenge, user = self._consume(OtpPurpose.PASSWORD_RESET, payload.challenge_id, payload.code, now)
        user.password_hash = self._hasher.hash(payload.new_password)
        user.phone_verified_at = user.phone_verified_at or now  # the code proved the number
        self._refresh.revoke_all_for_user(user.id, now)
        self._attempts.record(phone=user.phone, succeeded=True, at=now)  # clears a lockout from forgotten guesses
        self._session.commit()
        logger.info("password reset completed user_id=%s", user.id)

    # ----------------------------------------------------------------- tour

    def mark_tour_seen(self, current: CurrentUser, version: int) -> UserRead:
        user = self._users.get(current.user_id)
        if user is None:
            raise AuthenticationError("Invalid access token", code="invalid_token")
        user.tour_version_seen = max(user.tour_version_seen, version)  # never goes back
        self._session.commit()
        return UserRead.model_validate(user)

    def _consume(
        self, purpose: OtpPurpose, challenge_id: uuid.UUID, code: str, now: datetime
    ) -> tuple[OtpChallenge, User]:
        """Check a code (attempts, expiry, single use) and mark the challenge used. Wrong codes are counted and
        committed before raising."""
        challenge = self._otps.get_for_update(challenge_id)
        if challenge is None or challenge.purpose is not purpose or challenge.consumed_at is not None:
            raise AuthenticationError(CHALLENGE_ENDED, code="otp_challenge_ended")
        if challenge.attempts >= self._settings.otp_max_attempts:
            raise AuthenticationError(
                "Too many wrong codes. Please start again.", code="otp_attempts_exhausted", details={"attempts_left": 0}
            )
        if challenge.expires_at <= now:
            raise AuthenticationError("This code has expired. Request a new code.", code="otp_expired")
        if challenge.decoy or not hmac.compare_digest(self._hash(challenge.id, code), challenge.code_hash):
            challenge.attempts += 1
            self._session.commit()  # persist the attempt before raising
            left = max(0, self._settings.otp_max_attempts - challenge.attempts)
            raise AuthenticationError(
                f"{WRONG_CODE}. {left} attempts left.", code="invalid_otp", details={"attempts_left": left}
            )
        user = self._users.get(challenge.user_id) if challenge.user_id else None
        if user is None:
            raise AuthenticationError(CHALLENGE_ENDED, code="otp_challenge_ended")
        if not user.is_active:
            raise PermissionDeniedError("This account has been disabled", code="account_disabled")
        challenge.consumed_at = now
        return challenge, user

    def resend(self, payload: OtpResendRequest, *, client: str | None = None) -> OtpChallengeOut:
        """A new code for the same challenge (the old one stops working). Wrong attempts are NOT reset."""
        now = self._clock.now()
        self._require_sms()
        challenge = self._otps.get_for_update(payload.challenge_id)
        if (
            challenge is None
            or challenge.consumed_at is not None
            or challenge.attempts >= self._settings.otp_max_attempts
        ):
            raise AuthenticationError(CHALLENGE_ENDED, code="otp_challenge_ended")
        wait = self._cooldown_left(challenge.last_sent_at, now)
        if wait > 0:
            raise TooManyRequestsError(
                f"Please wait {wait} seconds before asking for another code.",
                code="otp_cooldown",
                details={"retry_after_seconds": wait},
                headers={"Retry-After": str(wait)},
            )
        if challenge.sends > self._settings.otp_max_resends:
            raise TooManyRequestsError(
                "No more codes can be sent for this attempt. Please start again.", code="otp_resend_limit"
            )
        self._check_send_limits(challenge.phone, client, now, cooldown=False)
        code = self._code()
        challenge.code_hash = self._hash(challenge.id, code)
        challenge.sends += 1
        challenge.last_sent_at = now
        challenge.expires_at = now + timedelta(seconds=self._settings.otp_ttl_seconds)
        if not challenge.decoy:
            self._deliver(challenge, code)
        self._session.commit()
        return self._challenge_out(challenge, code, now)

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

    def login(self, payload: LoginRequest, *, client: str | None = None) -> OtpChallengeOut:
        """Step 1: phone + password. A correct password does NOT sign in: it sends a fresh one-time code, and
        tokens are issued only by `verify(LOGIN, ...)`."""
        now = self._clock.now()
        self._enforce_not_locked(payload.phone, now)

        user = self._users.get_by_phone(payload.phone)
        if user is None:
            self._hasher.verify_dummy(payload.password)  # equalise timing: no phone enumeration
            password_ok = False
        else:
            password_ok = self._hasher.verify(user.password_hash, payload.password)

        if user is None or not password_ok:
            self._attempts.record(phone=payload.phone, succeeded=False, at=now)
            self._session.commit()  # persist the failure counter before raising
            raise AuthenticationError(INVALID_CREDENTIALS, code="invalid_credentials")

        if not user.is_active:
            raise PermissionDeniedError("This account has been disabled", code="account_disabled")

        self._require_sms()
        self._check_send_limits(payload.phone, client, now)
        if self._hasher.needs_rehash(user.password_hash):
            user.password_hash = self._hasher.hash(payload.password)
        self._attempts.record(phone=payload.phone, succeeded=True, at=now)
        challenge, code = self._new_challenge(user.id, OtpPurpose.LOGIN, user.phone, client, now)
        self._deliver(challenge, code)
        self._session.commit()
        return self._challenge_out(challenge, code, now)

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
        if not user.is_active:
            raise PermissionDeniedError("This account has been disabled", code="account_disabled")

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
        if not user.is_active:
            raise PermissionDeniedError("This account has been disabled", code="account_disabled")
        if not self._refresh.session_is_live(claims.session_id, now):
            raise AuthenticationError("This session has ended; please sign in again", code="session_revoked")
        return CurrentUser(user_id=user.id, role=user.role, session_id=claims.session_id)

    # ------------------------------------------------------------ helpers

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

    # ------------------------------------------------------- one-time codes

    def _require_sms(self) -> None:
        if not self._sms.is_enabled():
            raise ProviderUnavailableError(
                "Phone verification is not available on this server (no SMS provider is configured)",
                code="sms_disabled",
            )

    def _code(self) -> str:
        n = self._settings.otp_length
        return f"{secrets.randbelow(10**n):0{n}d}"

    def _hash(self, challenge_id: uuid.UUID, code: str) -> str:
        return hmac.new(self._otp_key, f"{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()

    def _new_challenge(
        self,
        user_id: uuid.UUID | None,
        purpose: OtpPurpose,
        phone: str,
        client: str | None,
        now: datetime,
        *,
        decoy: bool = False,
    ) -> tuple[OtpChallenge, str]:
        challenge = OtpChallenge(
            id=uuid.uuid4(),
            user_id=user_id,
            purpose=purpose,
            phone=phone,
            decoy=decoy,
            expires_at=now + timedelta(seconds=self._settings.otp_ttl_seconds),
            attempts=0,
            sends=1,
            last_sent_at=now,
            client=(client or None) and client[:64],
            created_at=now,
            code_hash="",
        )
        code = self._code()
        challenge.code_hash = self._hash(challenge.id, code)
        self._otps.add(challenge)
        return challenge, code

    def _deliver(self, challenge: OtpChallenge, code: str) -> None:
        minutes = max(1, self._settings.otp_ttl_seconds // 60)
        text = (
            f"Harvestique code: {code}. It expires in {minutes} minutes. "
            "Never share it; Harvestique will never ask for it."
        )
        try:
            self._sms.send(challenge.phone, text)
        except ProviderUnavailableError:
            self._session.rollback()
            raise ProviderUnavailableError(
                "The verification SMS could not be sent. Please try again later.", code="sms_unavailable"
            ) from None

    def _cooldown_left(self, last: datetime | None, now: datetime) -> int:
        if last is None:
            return 0
        left = self._settings.otp_resend_cooldown_seconds - (now - last).total_seconds()
        return max(0, math.ceil(left))

    def _check_send_limits(self, phone: str, client: str | None, now: datetime, *, cooldown: bool = True) -> None:
        hour = now - timedelta(hours=1)
        if (
            cooldown
            and (wait := self._cooldown_left(self._otps.last_open_send_at(phone, self._settings.otp_max_attempts), now))
            > 0
        ):
            raise TooManyRequestsError(
                f"A code was just sent. Please wait {wait} seconds.",
                code="otp_cooldown",
                details={"retry_after_seconds": wait},
                headers={"Retry-After": str(wait)},
            )
        if self._otps.sends_since(since=hour, phone=phone) >= self._settings.otp_max_sends_per_phone_per_hour or (
            client is not None
            and self._otps.sends_since(since=hour, client=client[:64])
            >= self._settings.otp_max_sends_per_client_per_hour
        ):
            raise TooManyRequestsError(
                "Too many codes were requested. Please try again in an hour.",
                code="otp_rate_limited",
                details={"retry_after_seconds": 3600},
                headers={"Retry-After": "3600"},
            )

    def _challenge_out(self, challenge: OtpChallenge, code: str, now: datetime) -> OtpChallengeOut:
        dev = self._sms.exposes_codes and self._settings.app_env != "production"
        hint = mask_phone(challenge.phone)
        if dev:
            message = (
                "DEVELOPMENT MODE: no SMS was sent. The code is shown here only because this server has no SMS "
                "provider; a production server sends it by SMS."
            )
        elif challenge.purpose is OtpPurpose.REGISTER:
            message = f"If this number can be registered, a {len(code)}-digit code was sent by SMS to {hint}."
        elif challenge.purpose is OtpPurpose.PASSWORD_RESET:
            message = f"If an account uses this number, a {len(code)}-digit code was sent by SMS to {hint}."
        else:
            message = f"A {len(code)}-digit code was sent by SMS to {hint}."
        return OtpChallengeOut(
            challenge_id=challenge.id,
            purpose=challenge.purpose,
            phone_hint=hint,
            code_length=self._settings.otp_length,
            expires_in=max(0, int((challenge.expires_at - now).total_seconds())),
            resend_after=self._cooldown_left(challenge.last_sent_at, now),
            attempts_left=max(0, self._settings.otp_max_attempts - challenge.attempts),
            delivery="development_console" if dev else "sms",
            dev_code=code if dev and not challenge.decoy else None,
            message=message,
        )

    def _enforce_not_locked(self, phone: str, now: datetime) -> None:
        window = timedelta(minutes=self._settings.login_lockout_minutes)
        failures, latest = self._attempts.consecutive_failures(phone, since=now - window)
        if failures >= self._settings.login_max_failed_attempts and latest is not None:
            retry_after = max(1, math.ceil((latest + window - now).total_seconds()))
            raise TooManyRequestsError(
                "Too many failed sign-in attempts. Try again later.",
                code="account_locked",
                details={"retry_after_seconds": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
