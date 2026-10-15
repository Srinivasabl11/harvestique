"""Saved planning scenarios: a crop plan (constraints) and its items (crop allocations + estimates).

Only *inputs* are stored. Results are recomputed on demand by the deterministic planning engine, so a
stored plan can never show stale numbers. Deleting a plan deletes its items (they are owned parts);
deleting a catalog crop that a plan item uses is refused (RESTRICT).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import CropSeason, DemandLevel, EstimateBasis, RiskLevel
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.crop import Crop


class CropPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "crop_plans"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_crop_plans_owner_id_name"),
        CheckConstraint("available_land_acres > 0", name="land_positive"),
        CheckConstraint("budget_inr IS NULL OR budget_inr > 0", name="budget_positive"),
        CheckConstraint("available_water_kl IS NULL OR available_water_kl > 0", name="water_positive"),
        CheckConstraint(
            "available_labour_person_days IS NULL OR available_labour_person_days > 0", name="labour_positive"
        ),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    farm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("farms.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    season: Mapped[CropSeason] = mapped_column(
        enum_column(CropSeason, name="plan_season", length=24), default=CropSeason.YEAR_ROUND
    )
    available_land_acres: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    budget_inr: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    available_water_kl: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    available_labour_person_days: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    items: Mapped[list[CropPlanItem]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="CropPlanItem.position",
        lazy="selectin",
    )


class CropPlanItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "crop_plan_items"
    __table_args__ = (
        CheckConstraint("area_acres > 0", name="area_positive"),
        CheckConstraint("duration_days > 0", name="duration_positive"),
        CheckConstraint("harvest_window_days BETWEEN 1 AND 365", name="harvest_window_range"),
        CheckConstraint("batches BETWEEN 1 AND 12", name="batches_range"),
        CheckConstraint(
            "batches = 1 OR (batch_interval_days IS NOT NULL AND batch_interval_days >= 1)",
            name="batch_interval_required",
        ),
        CheckConstraint(
            "yield_low_kg >= 0 AND yield_low_kg <= yield_expected_kg AND yield_expected_kg <= yield_high_kg "
            "AND yield_expected_kg > 0",
            name="yield_ordered",
        ),
        CheckConstraint(
            "price_low >= 0 AND price_low <= price_expected AND price_expected <= price_high AND price_expected > 0",
            name="price_ordered",
        ),
        CheckConstraint(
            "seed_cost >= 0 AND fertilizer_cost >= 0 AND pesticide_cost >= 0 AND irrigation_cost >= 0 "
            "AND machinery_cost >= 0 AND other_cost >= 0 AND labour_person_days >= 0 AND labour_wage >= 0 "
            "AND fixed_cost >= 0",
            name="costs_non_negative",
        ),
        CheckConstraint("cost_overrun_pct IS NULL OR cost_overrun_pct >= 0", name="overrun_non_negative"),
        CheckConstraint("demand_quantity_kg IS NULL OR demand_quantity_kg > 0", name="demand_positive"),
        CheckConstraint("water_kl_per_acre IS NULL OR water_kl_per_acre >= 0", name="water_non_negative"),
        Index("ix_crop_plan_items_plan_id_position", "plan_id", "position"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_plans.id", ondelete="CASCADE"))
    crop_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crops.id", ondelete="RESTRICT"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    crop_name: Mapped[str] = mapped_column(String(80))  # copied from the catalog when linked; free text otherwise
    area_acres: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    sowing_date: Mapped[date]
    duration_days: Mapped[int]
    harvest_window_days: Mapped[int]
    batches: Mapped[int] = mapped_column(default=1)
    batch_interval_days: Mapped[int | None]

    yield_low_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    yield_expected_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    yield_high_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    price_low: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    price_expected: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    price_high: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    seed_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))
    fertilizer_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))
    pesticide_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))
    irrigation_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))
    machinery_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))
    other_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))
    labour_person_days: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal(0))  # per acre
    labour_wage: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal(0))  # per person-day
    fixed_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    cost_overrun_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))

    water_kl_per_acre: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    demand_level: Mapped[DemandLevel] = mapped_column(
        enum_column(DemandLevel, name="demand_level", length=24), default=DemandLevel.MEDIUM
    )
    demand_quantity_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    declared_risk: Mapped[RiskLevel] = mapped_column(
        enum_column(RiskLevel, name="declared_risk", length=24), default=RiskLevel.MEDIUM
    )
    estimate_basis: Mapped[EstimateBasis] = mapped_column(
        enum_column(EstimateBasis, name="estimate_basis", length=24), default=EstimateBasis.LOCAL_KNOWLEDGE
    )
    notes: Mapped[str | None] = mapped_column(Text)

    plan: Mapped[CropPlan] = relationship(back_populates="items")
    crop: Mapped[Crop | None] = relationship(lazy="selectin")
