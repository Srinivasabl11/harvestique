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
    # History: when the person last proved by SMS code that they receive messages on `phone`. SMS codes are no longer
    # used, so new accounts keep NULL; an admin approving a tester is the check that the number is theirs.
    phone_verified_at: Mapped[datetime | None]
    # History: a sign-up whose SMS code was never entered. It cannot sign in and is replaced if the number registers
    # again. New sign-ups never set it.
    registration_pending: Mapped[bool] = mapped_column(default=False, server_default=false())
    # Set by an admin password reset (temporary password): no session is issued until the person sets a new password.
    must_change_password: Mapped[bool] = mapped_column(default=False, server_default=false())
    # Highest version of the first-login guided tour this person finished or skipped (0 = never shown).
    tour_version_seen: Mapped[int] = mapped_column(default=0, server_default="0")

    farmer_profile: Mapped[FarmerProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )
    buyer_profile: Mapped[BuyerProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )
