"""Crop cycle DTOs."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import CycleStatus
from app.schemas.base import Acres, LongText, Name80, PatchModel, StrictModel


class CropCycleCreate(StrictModel):
    """`area_acres` defaults to the whole plot. `status` may be planned (default), growing, or
    harvested (back-filling history; requires actual_harvest_date). Abandoned is not a valid start."""

    crop_id: uuid.UUID
    variety: Name80 | None = None
    status: CycleStatus = CycleStatus.PLANNED
    area_acres: Acres | None = None
    sowing_date: date
    expected_harvest_date: date | None = None
    actual_harvest_date: date | None = None
    notes: LongText | None = None


class CropCycleUpdate(PatchModel):
    """The crop and plot of a cycle are immutable: delete and recreate to change them."""

    non_nullable = frozenset({"status", "area_acres", "sowing_date"})

    variety: Name80 | None = None
    status: CycleStatus | None = None
    area_acres: Acres | None = None
    sowing_date: date | None = None
    expected_harvest_date: date | None = None
    actual_harvest_date: date | None = None
    notes: LongText | None = None


class CropCycleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plot_id: uuid.UUID
    crop_id: uuid.UUID
    crop_name: str
    variety: str | None
    status: CycleStatus
    area_acres: Acres
    sowing_date: date
    expected_harvest_date: date | None
    actual_harvest_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
