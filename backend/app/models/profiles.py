"""Role-specific profile rows (exactly one per farmer / buyer user; admins have none)."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import BuyerType, PreferredLanguage
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.user import User


class FarmerProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "farmer_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    village: Mapped[str | None] = mapped_column(String(100))
    district: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    preferred_language: Mapped[PreferredLanguage] = mapped_column(
        enum_column(PreferredLanguage, name="preferred_language", length=5),
        default=PreferredLanguage.ENGLISH,
    )

    user: Mapped[User] = relationship(back_populates="farmer_profile")


class BuyerProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "buyer_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    business_name: Mapped[str] = mapped_column(String(160))
    buyer_type: Mapped[BuyerType] = mapped_column(
        enum_column(BuyerType, name="buyer_type", length=16), default=BuyerType.OTHER
    )
    city: Mapped[str | None] = mapped_column(String(100))
    district: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))

    user: Mapped[User] = relationship(back_populates="buyer_profile")
