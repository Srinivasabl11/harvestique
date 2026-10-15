"""Reminder, notification, calendar and dashboard DTOs."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.enums import DataKind, NotificationCategory, Recurrence, ReminderStatus, ReminderType
from app.schemas.base import JsonNumber, LongText, PatchModel, StrictModel

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("due_at must include a timezone offset (e.g. 2026-10-08T07:00:00+05:30)")
    return v


class ReminderCreate(StrictModel):
    reminder_type: ReminderType
    title: Title
    notes: LongText | None = None
    due_at: datetime
    recurrence: Recurrence = Recurrence.NONE
    farm_id: uuid.UUID | None = None
    crop_cycle_id: uuid.UUID | None = None

    _tz = field_validator("due_at")(_aware)


class ReminderUpdate(PatchModel):
    non_nullable = frozenset({"title", "due_at", "recurrence", "reminder_type"})
    reminder_type: ReminderType | None = None
    title: Title | None = None
    notes: LongText | None = None
    due_at: datetime | None = None
    recurrence: Recurrence | None = None

    @field_validator("due_at")
    @classmethod
    def _tz(cls, v: datetime | None) -> datetime | None:
        return None if v is None else _aware(v)


class ReminderOut(_Out):
    id: uuid.UUID
    reminder_type: ReminderType
    title: str
    notes: str | None
    due_at: datetime
    recurrence: Recurrence
    status: ReminderStatus
    farm_id: uuid.UUID | None
    crop_cycle_id: uuid.UUID | None
    source: str
    created_at: datetime


class ReminderSuggestion(BaseModel):
    reminder_type: ReminderType
    title: str
    reason: str = Field(description="Which recorded data triggered the suggestion")
    due_at: datetime
    farm_id: uuid.UUID | None
    crop_cycle_id: uuid.UUID | None
    basis: DataKind


class NotificationOut(_Out):
    id: uuid.UUID
    category: NotificationCategory
    title: str
    body: str
    severity: str
    data: dict[str, Any]
    read_at: datetime | None
    created_at: datetime


class UnreadCount(BaseModel):
    unread: int


CalendarKind = Literal[
    "sowing", "expected_harvest", "predicted_harvest_window", "activity", "reminder", "collection", "delivery_window"
]


class CalendarEvent(BaseModel):
    kind: CalendarKind
    title: str
    start: date
    end: date | None
    data_kind: DataKind | Literal["user_entered", "scheduled"]
    farm_id: uuid.UUID | None = None
    crop_cycle_id: uuid.UUID | None = None
    ref_id: uuid.UUID | None = None


class CalendarOut(BaseModel):
    start: date
    end: date
    events: list[CalendarEvent]


class DashboardOut(BaseModel):
    generated_at: datetime
    users: dict[str, int]
    farms: int
    active_cycles: int
    lots: dict[str, int]
    available_kg: JsonNumber = Field(description="Sum of p10-based available supply over opted-in lots (estimate)")
    demands: dict[str, int]
    pools: dict[str, int]
    orders: dict[str, int]
    reallocation_events_30d: dict[str, int]
    batches_awaiting_quality: int
    quality: dict[str, JsonNumber] = Field(description="MEASURED: received / accepted / rejected kg")
    predictions_scored: int
    calibration_note: str
