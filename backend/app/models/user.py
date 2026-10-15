"""User account (one row per person, any role)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AccessStatus, UserRole
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column

if TYPE_CHECKING:
    from app.models.profiles import BuyerProfile, FarmerProfile


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    phone: Mapped[str] = mapped_column(String(16), unique=True)  # E.164, normalised
    email: Mapped[str | None] = mapped_column(String(254), unique=True)  # stored lower-case
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[UserRole] = mapped_column(enum_column(UserRole, name="user_role", length=16))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    # Admin-controlled tester access (see AccessStatus). Accounts that existed before this column are approved.
    access_status: Mapped[AccessStatus] = mapped_column(
        enum_column(AccessStatus, name="access_status", length=16),
        default=AccessStatus.APPROVED,
        server_default=AccessStatus.APPROVED.value,
    )
    access_changed_at: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]
    # Set when the person proves they receive SMS on `phone` (registration or login code). Accounts created before
    # phone verification existed keep NULL until their next login, which verifies them.
    phone_verified_at: Mapped[datetime | None]
    # A sign-up whose code was never entered: it cannot sign in and is replaced if the number registers again.
    registration_pending: Mapped[bool] = mapped_column(default=False, server_default=false())
    # Highest version of the first-login guided tour this person finished or skipped (0 = never shown).
    tour_version_seen: Mapped[int] = mapped_column(default=0, server_default="0")

    farmer_profile: Mapped[FarmerProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )
    buyer_profile: Mapped[BuyerProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )
