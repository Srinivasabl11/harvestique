"""Crop catalog (global, admin-managed) and crop cycles (one crop on one plot)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Numeric, String, Text, text, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import CropCategory, CropGroup, CropSeason, CycleStatus
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column


class Crop(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "crops"
    __table_args__ = (
        CheckConstraint("typical_duration_days > 0 AND typical_duration_days <= 3650", name="duration_range"),
    )

    name: Mapped[str] = mapped_column(String(80), unique=True)
    local_name: Mapped[str | None] = mapped_column(String(80))  # e.g. Kannada script
    category: Mapped[CropCategory] = mapped_column(enum_column(CropCategory, name="crop_category", length=24))
    typical_duration_days: Mapped[int]  # sowing -> end of harvest; admin-editable default
    season: Mapped[CropSeason | None] = mapped_column(enum_column(CropSeason, name="crop_season", length=24))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    # Indicative agronomic references (ASSUMPTION-grade data, used only when better evidence is missing)
    reference_yield_kg_per_acre: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    reference_yield_cv: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    water_need_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    # catalogue metadata (migration 0015): searchable, never used to change a crop's identity
    scientific_name: Mapped[str | None] = mapped_column(String(120))
    aliases: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=list, server_default=text("'[]'")
    )
    crop_group: Mapped[CropGroup | None] = mapped_column(enum_column(CropGroup, name="crop_group", length=24))


class CropCycle(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "crop_cycles"
    __table_args__ = (
        CheckConstraint("area_acres > 0", name="area_positive"),
        CheckConstraint(
            "expected_harvest_date IS NULL OR expected_harvest_date > sowing_date", name="expected_after_sowing"
        ),
        CheckConstraint(
            "actual_harvest_date IS NULL OR actual_harvest_date >= sowing_date", name="actual_not_before_sowing"
        ),
        CheckConstraint(
            "(status = 'harvested') = (actual_harvest_date IS NOT NULL)", name="harvest_date_iff_harvested"
        ),
        Index("ix_crop_cycles_plot_id_sowing_date", "plot_id", "sowing_date"),
    )

    plot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farm_plots.id", ondelete="RESTRICT"))
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id", ondelete="RESTRICT"), index=True)
    variety: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[CycleStatus] = mapped_column(
        enum_column(CycleStatus, name="cycle_status", length=24), default=CycleStatus.PLANNED
    )
    area_acres: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    sowing_date: Mapped[date]
    expected_harvest_date: Mapped[date | None]
    actual_harvest_date: Mapped[date | None]
    notes: Mapped[str | None] = mapped_column(Text)

    crop: Mapped[Crop] = relationship(lazy="selectin")

    @property
    def crop_name(self) -> str:
        return self.crop.name
