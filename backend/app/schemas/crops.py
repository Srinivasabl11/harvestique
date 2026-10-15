"""Crop catalog DTOs."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import CropCategory, CropGroup, CropSeason
from app.schemas.base import _AS_JSON_NUMBER, LongText, Name80, PatchModel, StrictModel

DurationDays = Annotated[int, Field(gt=0, le=3650)]
RefYield = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3), _AS_JSON_NUMBER]
RefCv = Annotated[Decimal, Field(ge=Decimal("0.01"), le=2, max_digits=4, decimal_places=3), _AS_JSON_NUMBER]
WaterNeed = Annotated[Decimal, Field(gt=0, max_digits=8, decimal_places=1), _AS_JSON_NUMBER]
Alias = Annotated[str, Field(min_length=1, max_length=60)]
Aliases = Annotated[list[Alias], Field(max_length=20)]
ScientificName = Annotated[str, Field(min_length=2, max_length=120)]


class CropCreate(StrictModel):
    name: Name80
    local_name: Name80 | None = None
    category: CropCategory
    typical_duration_days: DurationDays
    season: CropSeason | None = None
    notes: LongText | None = None
    reference_yield_kg_per_acre: RefYield | None = Field(
        default=None, description="Indicative yield (ASSUMPTION-grade)"
    )
    reference_yield_cv: RefCv | None = Field(default=None, description="Typical year-to-year variation (CV)")
    water_need_mm: WaterNeed | None = Field(default=None, description="Season water need in mm")
    scientific_name: ScientificName | None = None
    aliases: Aliases = Field(default_factory=list, description="Other names people search for (synonyms)")
    crop_group: CropGroup | None = None


class CropUpdate(PatchModel):
    non_nullable = frozenset({"name", "category", "typical_duration_days", "is_active"})

    name: Name80 | None = None
    local_name: Name80 | None = None
    category: CropCategory | None = None
    typical_duration_days: DurationDays | None = None
    season: CropSeason | None = None
    notes: LongText | None = None
    is_active: bool | None = None
    reference_yield_kg_per_acre: RefYield | None = Field(
        default=None, description="Indicative yield (ASSUMPTION-grade)"
    )
    reference_yield_cv: RefCv | None = Field(default=None, description="Typical year-to-year variation (CV)")
    water_need_mm: WaterNeed | None = Field(default=None, description="Season water need in mm")
    scientific_name: ScientificName | None = None
    aliases: Aliases | None = None
    crop_group: CropGroup | None = None


class CropRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    local_name: str | None
    category: CropCategory
    typical_duration_days: int
    season: CropSeason | None
    notes: str | None
    is_active: bool
    reference_yield_kg_per_acre: RefYield | None
    reference_yield_cv: RefCv | None
    water_need_mm: WaterNeed | None
    scientific_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    crop_group: CropGroup | None = None
