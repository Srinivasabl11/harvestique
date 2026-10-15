"""Farms and the plots they are divided into.

Deletion policy: foreign keys are RESTRICT. A parent with children cannot be deleted
(the service reports 409); archive it with is_active=false instead.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import IrrigationType, SoilType
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column


class Farm(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "farms"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_farms_owner_id_name"),
        CheckConstraint("total_area_acres > 0", name="area_positive"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="coordinates_paired"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(120))
    village: Mapped[str | None] = mapped_column(String(100))
    district: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    total_area_acres: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())


class FarmPlot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "farm_plots"
    __table_args__ = (
        UniqueConstraint("farm_id", "name", name="uq_farm_plots_farm_id_name"),
        CheckConstraint("area_acres > 0", name="area_positive"),
    )

    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(100))
    area_acres: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    soil_type: Mapped[SoilType | None] = mapped_column(enum_column(SoilType, name="soil_type", length=24))
    irrigation_type: Mapped[IrrigationType | None] = mapped_column(
        enum_column(IrrigationType, name="irrigation_type", length=24)
    )
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
