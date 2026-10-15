"""Planning DTOs: validated inputs (ranges, costs, crop items, plans, allocation requests)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import CropSeason, DemandLevel, EstimateBasis, RankBy, RiskLevel
from app.schemas.base import (
    _AS_JSON_NUMBER,
    Acres,
    LongText,
    Name80,
    Name120,
    PatchModel,
    StrictModel,
)

MAX_ITEMS = 30
MAX_CANDIDATES = 20


KgNonNeg = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=3), _AS_JSON_NUMBER]
KgPositive = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3), _AS_JSON_NUMBER]
PriceNonNeg = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2), _AS_JSON_NUMBER]
PricePositive = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2), _AS_JSON_NUMBER]
CostPerAcre = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2), _AS_JSON_NUMBER]
FixedCost = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2), _AS_JSON_NUMBER]
PersonDays = Annotated[Decimal, Field(ge=0, max_digits=8, decimal_places=2), _AS_JSON_NUMBER]
Wage = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2), _AS_JSON_NUMBER]
WaterPerAcre = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2), _AS_JSON_NUMBER]
DemandKg = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3), _AS_JSON_NUMBER]
OverrunPct = Annotated[Decimal, Field(ge=0, le=500, max_digits=6, decimal_places=2), _AS_JSON_NUMBER]
BudgetInr = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2), _AS_JSON_NUMBER]
WaterKl = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3), _AS_JSON_NUMBER]
LabourDays = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2), _AS_JSON_NUMBER]
SharePct = Annotated[Decimal, Field(gt=0, le=100, max_digits=5, decimal_places=2), _AS_JSON_NUMBER]

Duration = Annotated[int, Field(gt=0, le=3650)]
HarvestWindow = Annotated[int, Field(ge=1, le=365)]
Batches = Annotated[int, Field(ge=1, le=12)]
BatchInterval = Annotated[int, Field(ge=1, le=365)]


def _check_order(low: Decimal, expected: Decimal, high: Decimal) -> None:
    if not low <= expected <= high:
        raise ValueError("must satisfy low <= expected <= high")


class YieldRangeIn(StrictModel):
    """Yield per acre in kg: a pessimistic, an expected and an optimistic figure."""

    low: KgNonNeg
    expected: KgPositive
    high: KgNonNeg

    @model_validator(mode="after")
    def _ordered(self) -> YieldRangeIn:
        _check_order(self.low, self.expected, self.high)
        return self


class PriceRangeIn(StrictModel):
    """Price per kg in INR, net of transport and commission."""

    low: PriceNonNeg
    expected: PricePositive
    high: PriceNonNeg

    @model_validator(mode="after")
    def _ordered(self) -> PriceRangeIn:
        _check_order(self.low, self.expected, self.high)
        return self


class CostIn(StrictModel):
    """Per-acre costs in INR. Labour = person-days per acre x daily wage. Omitted costs count as 0."""

    seed_per_acre: CostPerAcre = Decimal(0)
    fertilizer_per_acre: CostPerAcre = Decimal(0)
    pesticide_per_acre: CostPerAcre = Decimal(0)
    irrigation_per_acre: CostPerAcre = Decimal(0)
    machinery_per_acre: CostPerAcre = Decimal(0)
    other_per_acre: CostPerAcre = Decimal(0)
    labour_person_days_per_acre: PersonDays = Decimal(0)
    labour_wage_per_day: Wage = Decimal(0)
    fixed_cost: FixedCost = Decimal(0)
    overrun_pct: OverrunPct | None = Field(
        default=None,
        description="Allowance for costs running over; omitted = 5/10/20% for low/medium/high declared risk",
    )


def _sane_date(value: date) -> date:
    if not 2000 <= value.year <= 2100:
        raise ValueError("sowing_date must be between years 2000 and 2100")
    return value


class ItemCore(StrictModel):
    """Everything about a crop in a plan except how much land it gets."""

    crop_name: Name80 | None = None
    sowing_date: date
    duration_days: Duration | None = Field(default=None, description="Sowing to start of harvest")
    harvest_window_days: HarvestWindow = Field(default=14, description="Days over which the crop is harvested and sold")
    batches: Batches = Field(default=1, description="Staggered planting: the area is split into this many sowings")
    batch_interval_days: BatchInterval | None = None
    yield_per_acre_kg: YieldRangeIn
    price_per_kg: PriceRangeIn
    cost: CostIn = Field(default_factory=CostIn)
    water_kl_per_acre: WaterPerAcre | None = None
    demand_level: DemandLevel = DemandLevel.MEDIUM
    demand_quantity_kg: DemandKg | None = Field(default=None, description="The most the market can absorb, in kg")
    declared_risk: RiskLevel = RiskLevel.MEDIUM
    estimate_basis: EstimateBasis = EstimateBasis.LOCAL_KNOWLEDGE

    @model_validator(mode="after")
    def _core_rules(self) -> ItemCore:
        _sane_date(self.sowing_date)
        if self.batches > 1 and self.batch_interval_days is None:
            raise ValueError("batch_interval_days is required when batches > 1")
        return self


def _batch_area_ok(area: Decimal, batches: int) -> None:
    if area / batches < Decimal("0.001"):
        raise ValueError("each batch must be at least 0.001 acre; reduce batches or increase area_acres")


class CalcItem(ItemCore):
    """A crop in a stateless calculation: crop_name and duration_days are required (no catalog)."""

    area_acres: Acres

    @model_validator(mode="after")
    def _required_and_sized(self) -> CalcItem:
        if not self.crop_name:
            raise ValueError("crop_name is required")
        if self.duration_days is None:
            raise ValueError("duration_days is required")
        _batch_area_ok(self.area_acres, self.batches)
        return self


class PlanItemCreate(ItemCore):
    """A crop in a saved plan. Link a catalog crop with crop_id (name and duration default from it)."""

    crop_id: uuid.UUID | None = None
    area_acres: Acres
    notes: LongText | None = None

    @model_validator(mode="after")
    def _identified_and_sized(self) -> PlanItemCreate:
        if self.crop_id is None and not (self.crop_name and self.duration_days):
            raise ValueError("provide crop_id, or both crop_name and duration_days")
        _batch_area_ok(self.area_acres, self.batches)
        return self


class PlanItemUpdate(PatchModel):
    """Partial update. Ranges and `cost` are replaced as whole objects."""

    non_nullable = frozenset(
        {
            "crop_name",
            "area_acres",
            "sowing_date",
            "duration_days",
            "harvest_window_days",
            "batches",
            "yield_per_acre_kg",
            "price_per_kg",
            "cost",
            "demand_level",
            "declared_risk",
            "estimate_basis",
        }
    )

    crop_id: uuid.UUID | None = None
    crop_name: Name80 | None = None
    area_acres: Acres | None = None
    sowing_date: date | None = None
    duration_days: Duration | None = None
    harvest_window_days: HarvestWindow | None = None
    batches: Batches | None = None
    batch_interval_days: BatchInterval | None = None
    yield_per_acre_kg: YieldRangeIn | None = None
    price_per_kg: PriceRangeIn | None = None
    cost: CostIn | None = None
    water_kl_per_acre: WaterPerAcre | None = None
    demand_level: DemandLevel | None = None
    demand_quantity_kg: DemandKg | None = None
    declared_risk: RiskLevel | None = None
    estimate_basis: EstimateBasis | None = None
    notes: LongText | None = None

    @model_validator(mode="after")
    def _sane(self) -> PlanItemUpdate:
        if self.sowing_date is not None:
            _sane_date(self.sowing_date)
        return self


# ------------------------------------------------------------------- plans


class _Constraints(StrictModel):
    """Limits the plan must respect. Only land is mandatory; the others are optional (omitted = unlimited)."""

    season: CropSeason = CropSeason.YEAR_ROUND
    budget_inr: BudgetInr | None = None
    available_water_kl: WaterKl | None = None
    available_labour_person_days: LabourDays | None = None


class CalcRequest(_Constraints):
    available_land_acres: Acres
    items: list[CalcItem] = Field(min_length=1, max_length=MAX_ITEMS)


class CropPlanCreate(_Constraints):
    name: Name120
    description: LongText | None = None
    farm_id: uuid.UUID | None = None
    available_land_acres: Acres | None = Field(default=None, description="Omit to use the linked farm's total area")
    items: list[PlanItemCreate] = Field(default_factory=list, max_length=MAX_ITEMS)

    @model_validator(mode="after")
    def _land_known(self) -> CropPlanCreate:
        if self.available_land_acres is None and self.farm_id is None:
            raise ValueError("provide available_land_acres, or farm_id to use that farm's area")
        return self


class CropPlanUpdate(PatchModel):
    non_nullable = frozenset({"name", "season", "available_land_acres"})

    name: Name120 | None = None
    description: LongText | None = None
    farm_id: uuid.UUID | None = None
    season: CropSeason | None = None
    available_land_acres: Acres | None = None
    budget_inr: BudgetInr | None = None
    available_water_kl: WaterKl | None = None
    available_labour_person_days: LabourDays | None = None


class CropPlanDuplicate(StrictModel):
    name: Name120


# --------------------------------------------------------------- allocation


class CandidateIn(ItemCore):
    """A crop the farmer would consider growing; the allocator decides how much."""

    min_area_acres: Acres = Field(default=Decimal("0.1"), description="Smaller allocations are not worth making")
    max_area_acres: Acres | None = None

    @model_validator(mode="after")
    def _complete(self) -> CandidateIn:
        if not self.crop_name:
            raise ValueError("crop_name is required")
        if self.duration_days is None:
            raise ValueError("duration_days is required")
        if self.max_area_acres is not None and self.max_area_acres < self.min_area_acres:
            raise ValueError("max_area_acres cannot be below min_area_acres")
        return self


class AllocationRequestIn(_Constraints):
    available_land_acres: Acres
    rank_by: RankBy = RankBy.MARGIN_PER_ACRE
    max_crop_share_pct: SharePct = Field(
        default=Decimal(100), description="No single candidate may take more than this share of the land"
    )
    candidates: list[CandidateIn] = Field(min_length=1, max_length=MAX_CANDIDATES)


# --------------------------------------------------------------- read models


class RangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    low: Annotated[Decimal, _AS_JSON_NUMBER]
    expected: Annotated[Decimal, _AS_JSON_NUMBER]
    high: Annotated[Decimal, _AS_JSON_NUMBER]


class PlanItemRead(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    crop_id: uuid.UUID | None
    crop_name: str
    position: int
    area_acres: Acres
    sowing_date: date
    duration_days: int
    harvest_window_days: int
    batches: int
    batch_interval_days: int | None
    yield_per_acre_kg: RangeOut
    price_per_kg: RangeOut
    cost: CostIn
    water_kl_per_acre: WaterPerAcre | None
    demand_level: DemandLevel
    demand_quantity_kg: DemandKg | None
    declared_risk: RiskLevel
    estimate_basis: EstimateBasis
    notes: str | None
    created_at: datetime
    updated_at: datetime


class CropPlanRead(BaseModel):
    id: uuid.UUID
    farm_id: uuid.UUID | None
    name: str
    description: str | None
    season: CropSeason
    available_land_acres: Acres
    budget_inr: BudgetInr | None
    available_water_kl: WaterKl | None
    available_labour_person_days: LabourDays | None
    items: list[PlanItemRead]
    created_at: datetime
    updated_at: datetime


class CropPlanSummary(BaseModel):
    id: uuid.UUID
    farm_id: uuid.UUID | None
    name: str
    season: CropSeason
    available_land_acres: Acres
    budget_inr: BudgetInr | None
    item_count: int
    created_at: datetime
    updated_at: datetime
