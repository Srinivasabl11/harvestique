"""Records a farmer keeps against a farm / crop cycle: expenses, activities, observations."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ActivityType, ExpenseCategory, GrowthStage, HealthStatus
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column


class FarmExpense(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Money spent (INR). `crop_cycle_id` NULL = farm-level overhead."""

    __tablename__ = "farm_expenses"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_farm_expenses_farm_id_expense_date", "farm_id", "expense_date"),
    )

    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id", ondelete="RESTRICT"))
    crop_cycle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("crop_cycles.id", ondelete="RESTRICT"), index=True
    )
    category: Mapped[ExpenseCategory] = mapped_column(enum_column(ExpenseCategory, name="expense_category", length=24))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    expense_date: Mapped[date]
    description: Mapped[str | None] = mapped_column(String(255))


class FarmActivity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A piece of work done on the farm (log entry, not a future task)."""

    __tablename__ = "farm_activities"
    __table_args__ = (Index("ix_farm_activities_farm_id_activity_date", "farm_id", "activity_date"),)

    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id", ondelete="RESTRICT"))
    plot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("farm_plots.id", ondelete="RESTRICT"), index=True)
    crop_cycle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("crop_cycles.id", ondelete="RESTRICT"), index=True
    )
    activity_type: Mapped[ActivityType] = mapped_column(enum_column(ActivityType, name="activity_type", length=24))
    activity_date: Mapped[date]
    description: Mapped[str | None] = mapped_column(Text)


class CropObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A field observation of a crop cycle's condition."""

    __tablename__ = "crop_observations"
    __table_args__ = (
        CheckConstraint(
            "estimated_loss_percent IS NULL OR (estimated_loss_percent >= 0 AND estimated_loss_percent <= 100)",
            name="loss_percent_range",
        ),
        Index("ix_crop_observations_crop_cycle_id_observed_on", "crop_cycle_id", "observed_on"),
    )

    crop_cycle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_cycles.id", ondelete="RESTRICT"))
    observed_on: Mapped[date]
    growth_stage: Mapped[GrowthStage | None] = mapped_column(enum_column(GrowthStage, name="growth_stage", length=24))
    health_status: Mapped[HealthStatus] = mapped_column(enum_column(HealthStatus, name="health_status", length=24))
    estimated_loss_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    notes: Mapped[str | None] = mapped_column(Text)
