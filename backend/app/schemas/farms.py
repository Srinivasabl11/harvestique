"""Farm and plot DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.enums import IrrigationType, SoilType
from app.schemas.base import (
    Acres,
    Latitude,
    Longitude,
    LongText,
    Name100,
    Name120,
    PatchModel,
    StrictModel,
)

# ------------------------------------------------------------------- farms


class FarmCreate(StrictModel):
    name: Name120
    village: Name100 | None = None
    district: Name100 | None = None
    state: Name100 | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    total_area_acres: Acres
    notes: LongText | None = None

    @model_validator(mode="after")
    def _coordinates_come_in_pairs(self) -> FarmCreate:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class FarmUpdate(PatchModel):
    non_nullable = frozenset({"name", "total_area_acres", "is_active"})

    name: Name120 | None = None
    village: Name100 | None = None
    district: Name100 | None = None
    state: Name100 | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    total_area_acres: Acres | None = None
    notes: LongText | None = None
    is_active: bool | None = None


class FarmRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    village: str | None
    district: str | None
    state: str | None
    latitude: Latitude | None
    longitude: Longitude | None
    total_area_acres: Acres
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------- plots


class PlotCreate(StrictModel):
    name: Name100
    area_acres: Acres
    soil_type: SoilType | None = None
    irrigation_type: IrrigationType | None = None
    notes: LongText | None = None


class PlotUpdate(PatchModel):
    non_nullable = frozenset({"name", "area_acres", "is_active"})

    name: Name100 | None = None
    area_acres: Acres | None = None
    soil_type: SoilType | None = None
    irrigation_type: IrrigationType | None = None
    notes: LongText | None = None
    is_active: bool | None = None


class PlotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    farm_id: uuid.UUID
    name: str
    area_acres: Acres
    soil_type: SoilType | None
    irrigation_type: IrrigationType | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
