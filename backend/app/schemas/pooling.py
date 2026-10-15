"""Harvest pooling DTOs."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import AllocationStatus, DemandStatus, PoolAlgorithm, PoolStatus, QualityGrade, ReallocationOutcome
from app.schemas.base import _AS_JSON_NUMBER, JsonNumber, Latitude, Longitude, LongText, StrictModel

Kg = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3), _AS_JSON_NUMBER]
Score = Annotated[Decimal, Field(ge=0, le=100, max_digits=4, decimal_places=1), _AS_JSON_NUMBER]
Km = Annotated[Decimal, Field(gt=0, max_digits=8, decimal_places=1), _AS_JSON_NUMBER]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DemandCreate(StrictModel):
    crop_id: uuid.UUID
    quantity_kg: Kg
    window_start: date
    window_end: date
    min_grade: QualityGrade = QualityGrade.C
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    max_distance_km: Km | None = None
    min_confidence: Score = Decimal(0)
    max_risk: Score = Decimal(100)
    notes: LongText | None = None

    @model_validator(mode="after")
    def _rules(self) -> DemandCreate:
        if self.window_end < self.window_start:
            raise ValueError("window_end must not be before window_start")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class DemandOut(_Out):
    id: uuid.UUID
    crop_id: uuid.UUID
    quantity_kg: JsonNumber
    window_start: date
    window_end: date
    min_grade: QualityGrade
    latitude: JsonNumber | None
    longitude: JsonNumber | None
    max_distance_km: JsonNumber | None
    min_confidence: JsonNumber
    max_risk: JsonNumber
    status: DemandStatus
    notes: str | None
    created_at: datetime
    crop_name: str | None = None
    # buyer-facing progress, derived from the demand, its pool and its order (see domain/pooling/shortage.py)
    stage: str = Field(
        default="open",
        description=(
            "open, matching_supply_available, supply_reserved, partially_matched, no_matching_supply, "
            "awaiting_farmer_confirmation, confirmed, "
            "reallocation_required, in_fulfilment, fulfilled, partially_fulfilled, cancelled"
        ),
    )
    pool_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    allocated_kg: JsonNumber | None = Field(default=None, description="Reserved from predicted supply (pooled only)")
    remaining_kg: JsonNumber | None = Field(default=None, description="Quantity still not covered (pooled only)")
    matched_kg: JsonNumber | None = Field(
        default=None,
        description="Open demands only: eligible predicted supply that could cover it now (p10 estimates, capped at "
        "the quantity)",
    )
    shortage_kg: JsonNumber | None = Field(
        default=None, description="Open demands only: quantity current eligible supply cannot cover"
    )


class MatchOut(BaseModel):
    lot_id: uuid.UUID
    farm_ref: str = Field(description="Pseudonymous farm reference (not the farmer's identity)")
    eligible: bool
    reasons: list[str]
    score: JsonNumber
    components: dict[str, JsonNumber]
    available_kg: JsonNumber
    p50_kg: JsonNumber | None
    window_start: date
    window_end: date
    confidence: JsonNumber
    risk: JsonNumber | None
    reliability: JsonNumber
    distance_km: JsonNumber | None
    grade: QualityGrade = Field(description="The farmer's grade for this lot (indicative, not an official grade)")
    grade_basis: Literal["farmer_graded", "farmer_expected"] = Field(
        description="farmer_graded: the farmer graded the recorded harvest against the A/B/C checks; "
        "farmer_expected: the farmer's expectation before harvest. The hub's quality check decides acceptance."
    )


class MatchesOut(BaseModel):
    demand_id: uuid.UUID | None
    need_kg: JsonNumber
    eligible_supply_kg: JsonNumber
    shortfall_kg: JsonNumber = Field(description="need_kg minus eligible supply, never negative")
    eligible_count: int = Field(description="How many lots are eligible")
    matches: list[MatchOut]
    note: str
    fulfilment: str = Field(default="none", description="full / partial / none, for need_kg")
    shortage_kg: JsonNumber = Field(default=Decimal(0), description="need_kg minus eligible supply, never negative")
    excluded_reasons: dict[str, int] = Field(default_factory=dict, description="reason -> number of excluded lots")
    explanation: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(
        default_factory=list,
        description=(
            "create_pool, wait_for_supply, revise_dates, widen_distance, accept_lower_grade, relax_risk_limits, "
            "choose_other_crop (a different crop is only ever the buyer's explicit choice)"
        ),
    )


class WeightsIn(StrictModel):
    confidence: Annotated[Decimal, Field(ge=0, le=1)] = Decimal("0.25")
    safety: Annotated[Decimal, Field(ge=0, le=1)] = Decimal("0.20")
    reliability: Annotated[Decimal, Field(ge=0, le=1)] = Decimal("0.15")
    window: Annotated[Decimal, Field(ge=0, le=1)] = Decimal("0.15")
    proximity: Annotated[Decimal, Field(ge=0, le=1)] = Decimal("0.10")
    availability: Annotated[Decimal, Field(ge=0, le=1)] = Decimal("0.15")

    @model_validator(mode="after")
    def _sum(self) -> WeightsIn:
        if sum(self.model_dump().values()) != 1:
            raise ValueError("weights must sum to 1")
        return self


class PoolCreate(StrictModel):
    algorithm: PoolAlgorithm = Field(
        default=PoolAlgorithm.GREEDY,
        description=(
            "greedy (default) + dynamic reallocation; lp = risk/confidence-aware optimiser kept for research "
            "comparison (it did not outperform greedy in the simulated evaluation)"
        ),
    )
    weights: WeightsIn = Field(default_factory=WeightsIn)
    max_pool_risk: Score = Field(default=Decimal(50), description="LP only: maximum average risk of the pool's supply")
    max_share: Annotated[Decimal, Field(gt=0, le=1, max_digits=4, decimal_places=3)] = Field(
        default=Decimal("0.4"),
        description="LP only: diversification cap per farm (relaxed if it would cost fulfilment)",
    )


class AllocationOut(_Out):
    id: uuid.UUID
    lot_id: uuid.UUID
    quantity_kg: JsonNumber
    status: AllocationStatus
    risk_level: str
    reservation_id: uuid.UUID | None
    score: JsonNumber | None = None


class PoolOut(BaseModel):
    id: uuid.UUID
    demand_id: uuid.UUID
    status: PoolStatus
    algorithm: PoolAlgorithm
    demand_kg: JsonNumber
    allocated_kg: JsonNumber
    shortage_kg: JsonNumber
    unfilled_kg: JsonNumber = Field(
        description=(
            "demand_kg - allocated_kg: still not covered by any farm. Includes a shortfall the pool was created with "
            "(shortage_kg counts only supply lost after allocation)"
        )
    )
    closed: bool = Field(description="Closed pools (order cancelled or completed) are never rebalanced")
    fill_rate: JsonNumber
    version: int
    allocations: list[AllocationOut]
    notes: list[str]
    created_at: datetime
    updated_at: datetime


class EventOut(_Out):
    id: uuid.UUID
    pool_id: uuid.UUID
    trigger: str
    trigger_ref: str | None
    outcome: ReallocationOutcome
    algorithm: str
    shortage_kg: JsonNumber
    replaced_kg: JsonNumber
    unresolved_kg: JsonNumber
    topped_up_kg: JsonNumber
    steps: int
    duration_ms: int
    reason: str
    before: dict[str, Any]
    after: dict[str, Any]
    created_at: datetime


class LedgerOut(_Out):
    id: uuid.UUID
    allocation_id: uuid.UUID | None
    lot_id: uuid.UUID
    action: str
    quantity_before: JsonNumber
    quantity_after: JsonNumber
    reason: str
    reallocation_event_id: uuid.UUID | None
    created_at: datetime


class LotUpdate(StrictModel):
    pool_eligible: bool | None = None
    expected_grade: QualityGrade | None = None
