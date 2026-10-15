"""Expense, activity and observation DTOs."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import ActivityType, ExpenseCategory, GrowthStage, HealthStatus
from app.schemas.base import LongText, Money, PatchModel, Percent, StrictModel, Text255

# ---------------------------------------------------------------- expenses


class ExpenseCreate(StrictModel):
    """`crop_cycle_id` omitted/null = farm-level overhead. Amounts are INR."""

    crop_cycle_id: uuid.UUID | None = None
    category: ExpenseCategory
    amount: Money
    expense_date: date
    description: Text255 | None = None


class ExpenseUpdate(PatchModel):
    non_nullable = frozenset({"category", "amount", "expense_date"})

    crop_cycle_id: uuid.UUID | None = None
    category: ExpenseCategory | None = None
    amount: Money | None = None
    expense_date: date | None = None
    description: Text255 | None = None


class ExpenseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    farm_id: uuid.UUID
    crop_cycle_id: uuid.UUID | None
    category: ExpenseCategory
    amount: Money
    expense_date: date
    description: str | None
    created_at: datetime
    updated_at: datetime


# -------------------------------------------------------------- activities


class ActivityCreate(StrictModel):
    plot_id: uuid.UUID | None = None
    crop_cycle_id: uuid.UUID | None = None
    activity_type: ActivityType
    activity_date: date
    description: LongText | None = None


class ActivityUpdate(PatchModel):
    non_nullable = frozenset({"activity_type", "activity_date"})

    plot_id: uuid.UUID | None = None
    crop_cycle_id: uuid.UUID | None = None
    activity_type: ActivityType | None = None
    activity_date: date | None = None
    description: LongText | None = None


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    farm_id: uuid.UUID
    plot_id: uuid.UUID | None
    crop_cycle_id: uuid.UUID | None
    activity_type: ActivityType
    activity_date: date
    description: str | None
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------ observations


class ObservationCreate(StrictModel):
    observed_on: date
    growth_stage: GrowthStage | None = None
    health_status: HealthStatus
    estimated_loss_percent: Percent | None = None
    notes: LongText | None = None


class ObservationUpdate(PatchModel):
    non_nullable = frozenset({"observed_on", "health_status"})

    observed_on: date | None = None
    growth_stage: GrowthStage | None = None
    health_status: HealthStatus | None = None
    estimated_loss_percent: Percent | None = None
    notes: LongText | None = None


class ObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    crop_cycle_id: uuid.UUID
    observed_on: date
    growth_stage: GrowthStage | None
    health_status: HealthStatus
    estimated_loss_percent: Percent | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
