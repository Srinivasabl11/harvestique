"""Authentication and identity DTOs: requests, responses and validation rules."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.core.enums import AccessStatus, BuyerType, PreferredLanguage, UserRole
from app.core.phone import normalize_phone
from app.schemas.base import PatchModel, StrictModel

# ------------------------------------------------------------ field types

PhoneNumber = Annotated[str, AfterValidator(normalize_phone)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


# Sign-in is password-only, so the passwords attackers try first are refused for every NEW password (sign-up,
# change, admin CLI). Compared case-insensitively. Existing passwords keep working until the person changes them.
COMMON_PASSWORDS = frozenset(
    {
        "password1", "password12", "password123", "passw0rd", "passw0rd1", "qwerty123", "qwerty12", "qwerty1234",
        "abc12345", "abcd1234", "abc123456", "1q2w3e4r", "1q2w3e4r5t", "q1w2e3r4", "a1b2c3d4", "asdf1234",
        "zxcv1234", "iloveyou1", "welcome1", "welcome123", "admin123", "admin1234", "letmein1", "test1234",
        "12345678a", "a12345678", "1234567a", "a1234567", "123456789a", "1234qwer", "india123", "india1234",
        "farmer123", "farmer1234", "kisan123", "harvestique1", "harvestique123",
    }
)  # fmt: skip


def validate_password_strength(password: str) -> str:
    """New-password policy: 8-128 chars, at least one letter and one digit, not a well-known password."""
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise ValueError(f"Password must be {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} characters long")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("Password must contain at least one letter and one digit")
    if password.lower() in COMMON_PASSWORDS:
        raise ValueError("This password is too common; choose one that is harder to guess")
    return password


NewPassword = Annotated[str, AfterValidator(validate_password_strength)]


# --------------------------------------------------------------- requests


class FarmerProfileInput(StrictModel):
    village: ShortText | None = None
    district: ShortText | None = None
    state: ShortText | None = None
    preferred_language: PreferredLanguage = PreferredLanguage.ENGLISH


class BuyerProfileInput(StrictModel):
    business_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
    buyer_type: BuyerType = BuyerType.OTHER
    city: ShortText | None = None
    district: ShortText | None = None
    state: ShortText | None = None


class _RegisterBase(StrictModel):
    phone: PhoneNumber
    password: NewPassword
    full_name: FullName
    email: EmailStr | None = None

    @field_validator("email")
    @classmethod
    def _lower_email(cls, value: str | None) -> str | None:
        return value.lower() if value else None


class RegisterFarmerRequest(_RegisterBase):
    role: Literal["farmer"]
    profile: FarmerProfileInput = Field(default_factory=FarmerProfileInput)


class RegisterBuyerRequest(_RegisterBase):
    role: Literal["buyer"]
    profile: BuyerProfileInput


# Public sign-up is limited to farmer/buyer: any other role (e.g. "admin") fails validation.
RegisterPayload = RegisterFarmerRequest | RegisterBuyerRequest
RegisterRequest = Annotated[RegisterPayload, Field(discriminator="role")]


class LoginRequest(StrictModel):
    phone: PhoneNumber
    password: Annotated[str, Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)]


class PasswordChangeRequest(StrictModel):
    """Set a new password with the current one (or the temporary one an admin issued). Needs no session, so it also
    works when sign-in is refused with `password_change_required`."""

    phone: PhoneNumber
    current_password: Annotated[str, Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)]
    new_password: NewPassword


class TourUpdate(StrictModel):
    version: Annotated[int, Field(ge=0, le=1000)]


class RefreshRequest(StrictModel):
    refresh_token: Annotated[str, Field(min_length=20, max_length=200)]


class AdminCreateRequest(StrictModel):
    """Used by the create-admin CLI only; there is no public endpoint for it."""

    phone: PhoneNumber
    password: NewPassword
    full_name: FullName
    email: EmailStr | None = None


class AccessUpdate(StrictModel):
    """Admin decision on a tester account: approve (or re-approve), suspend (keeps sessions), revoke (signs out)."""

    status: Literal["approved", "suspended", "revoked"]


# -------------------------------------------------------------- responses


class FarmerProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    village: str | None
    district: str | None
    state: str | None
    preferred_language: PreferredLanguage


class BuyerProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    business_name: str
    buyer_type: BuyerType
    city: str | None
    district: str | None
    state: str | None


class UserRead(BaseModel):
    """Public view of a user. Never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    phone: str
    email: str | None
    full_name: str
    role: UserRole
    is_active: bool
    access_status: AccessStatus = AccessStatus.APPROVED
    created_at: datetime
    last_login_at: datetime | None
    phone_verified_at: datetime | None = None
    must_change_password: bool = False
    tour_version_seen: int = 0
    farmer_profile: FarmerProfileRead | None
    buyer_profile: BuyerProfileRead | None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int = Field(description="Access-token lifetime in seconds")


class AuthResponse(BaseModel):
    user: UserRead
    tokens: TokenPair


class RegistrationOut(BaseModel):
    """Result of a sign-up. `approved`: the account can be used now and `user` + `tokens` are included. `pending`: an
    admin must approve it first; nothing else is returned (the same answer is given for a number that already has an
    account, so sign-up does not reveal who is registered)."""

    status: Literal["approved", "pending"]
    message: str
    user: UserRead | None = None
    tokens: TokenPair | None = None


class TemporaryPasswordOut(BaseModel):
    """An admin password reset. The temporary password is shown ONCE, here; it is stored only as a hash."""

    user: UserRead
    temporary_password: str
    message: str


class CurrentUser(BaseModel):
    """The authenticated caller, as seen by services (HTTP-agnostic)."""

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    role: UserRole
    session_id: uuid.UUID


class FarmerProfileUpdate(PatchModel):
    non_nullable = frozenset({"preferred_language"})
    village: ShortText | None = None
    district: ShortText | None = None
    state: ShortText | None = None
    preferred_language: PreferredLanguage | None = None


class BuyerProfileUpdate(PatchModel):
    non_nullable = frozenset({"business_name", "buyer_type"})
    business_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)] | None = None
    buyer_type: BuyerType | None = None
    city: ShortText | None = None
    district: ShortText | None = None
    state: ShortText | None = None
