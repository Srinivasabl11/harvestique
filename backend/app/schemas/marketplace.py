"""Marketplace DTOs: orders, participation, hubs, batches, quality, traceability, market search.

Quantities only; no price is ever returned or computed. `data_kind` fields say where each number comes from.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.enums import (
    BatchStatus,
    BuyerType,
    DataKind,
    FarmerProgress,
    OrderItemStatus,
    OrderStatus,
    ParticipationStatus,
    PoolStatus,
    QualityGrade,
    QualityResult,
)
from app.schemas.base import _AS_JSON_NUMBER, JsonNumber, Latitude, Longitude, LongText, StrictModel

Kg = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3), _AS_JSON_NUMBER]
KgOrZero = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3), _AS_JSON_NUMBER]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ orders
class OrderCreate(StrictModel):
    pool_id: uuid.UUID
    delivery_hub_id: uuid.UUID | None = None
    notes: LongText | None = None


class OrderItemOut(BaseModel):
    id: uuid.UUID
    allocation_id: uuid.UUID
    lot_id: uuid.UUID
    farm_ref: str = Field(description="Pseudonymous farm reference")
    quantity_kg: JsonNumber = Field(description="Committed share (p10-based ESTIMATE until fulfilled)")
    fulfilled_kg: JsonNumber = Field(description="MEASURED quantity accepted at quality check and delivered")
    status: OrderItemStatus
    participation_status: ParticipationStatus
    farmer_progress: FarmerProgress | None = Field(default=None, description="preparing / ready, set by the farmer")


class OrderOut(BaseModel):
    id: uuid.UUID
    pool_id: uuid.UUID
    status: OrderStatus
    crop_name: str
    ordered_kg: JsonNumber
    committed_kg: JsonNumber
    confirmed_kg: JsonNumber = Field(description="Accepted by farmers, plus anything already delivered")
    awaiting_kg: JsonNumber = Field(description="Asked of farmers who have not accepted yet")
    uncovered_kg: JsonNumber = Field(description="Ordered but no supply found yet (the remaining shortage)")
    fulfilled_kg: JsonNumber
    pool_status: PoolStatus
    pool_shortage_kg: JsonNumber
    delivery_hub_id: uuid.UUID | None
    window_start: date
    window_end: date
    notes: str | None
    items: list[OrderItemOut]
    created_at: datetime
    updated_at: datetime
    disclaimer: str = (
        "Committed quantities are pessimistic (p10) predictions and can change; Harvestique reallocates "
        "automatically when they fall. Nothing is guaranteed until produce is received and quality-checked."
    )


# ----------------------------------------------------------- participation
class ParticipationDecline(StrictModel):
    reason: Reason


class ProgressUpdate(StrictModel):
    stage: FarmerProgress


class ParticipationOut(BaseModel):
    id: uuid.UUID
    status: ParticipationStatus
    order_id: uuid.UUID
    order_status: OrderStatus
    order_item_id: uuid.UUID
    item_status: OrderItemStatus
    lot_id: uuid.UUID
    crop_cycle_id: uuid.UUID
    crop_name: str
    quantity_kg: JsonNumber
    fulfilled_kg: JsonNumber
    window_start: date
    window_end: date
    min_grade: QualityGrade
    buyer_business: str
    buyer_type: BuyerType
    delivery_hub_id: uuid.UUID | None
    responded_at: datetime | None
    reason: str | None
    progress: FarmerProgress | None = None
    progress_at: datetime | None = None
    created_at: datetime


# -------------------------------------------------------------------- hubs
class HubCreate(StrictModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
    district: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    address: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None

    @model_validator(mode="after")
    def _pair(self) -> HubCreate:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class HubUpdate(StrictModel):
    is_active: bool | None = None
    address: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = None


class HubOut(_Out):
    id: uuid.UUID
    name: str
    district: str | None
    address: str | None
    latitude: JsonNumber | None
    longitude: JsonNumber | None
    is_active: bool


# ------------------------------------------------------- batches & quality
class BatchCreate(StrictModel):
    order_item_id: uuid.UUID
    hub_id: uuid.UUID
    received_kg: Kg
    notes: LongText | None = None


class QualityIn(StrictModel):
    grade: QualityGrade | None = Field(default=None, description="Required unless the whole batch is rejected")
    accepted_kg: KgOrZero
    rejected_kg: KgOrZero
    moisture_percent: Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)] | None = None
    defects: LongText | None = None

    @model_validator(mode="after")
    def _grade(self) -> QualityIn:
        if self.accepted_kg > 0 and self.grade is None:
            raise ValueError("grade is required when any quantity is accepted")
        return self


class QualityOut(_Out):
    id: uuid.UUID
    batch_id: uuid.UUID
    grade: QualityGrade | None
    result: QualityResult
    accepted_kg: JsonNumber
    rejected_kg: JsonNumber
    moisture_percent: JsonNumber | None
    defects: str | None
    checked_at: datetime
    data_kind: DataKind = DataKind.MEASURED


class BatchOut(BaseModel):
    id: uuid.UUID
    code: str
    order_item_id: uuid.UUID
    order_id: uuid.UUID
    lot_id: uuid.UUID
    hub_id: uuid.UUID
    hub_name: str
    received_kg: JsonNumber
    received_at: datetime
    status: BatchStatus
    notes: str | None
    quality: QualityOut | None
    data_kind: DataKind = DataKind.MEASURED


class FulfilmentOut(BaseModel):
    order_item_id: uuid.UUID
    item_status: OrderItemStatus
    accepted_kg: JsonNumber
    fulfilled_kg: JsonNumber
    order_status: OrderStatus
    order_fulfilled_kg: JsonNumber
    note: str


# ------------------------------------------------------------ traceability
class TraceStep(BaseModel):
    step: str
    at: datetime | date | None
    data_kind: DataKind | str
    detail: dict[str, Any]


class TraceItem(BaseModel):
    order_item_id: uuid.UUID
    farm_ref: str
    status: OrderItemStatus
    steps: list[TraceStep]


class OrderTrace(BaseModel):
    order_id: uuid.UUID
    order_status: OrderStatus
    crop_name: str
    ordered_kg: JsonNumber
    fulfilled_kg: JsonNumber
    pool: dict[str, Any]
    reallocations: list[dict[str, Any]]
    items: list[TraceItem]
    chain: str = "Order -> Pool -> Farm Allocation -> Harvest -> Collection Batch -> Quality -> Fulfilment"


class BatchTrace(BaseModel):
    batch: BatchOut
    order_id: uuid.UUID
    order_status: OrderStatus
    pool_id: uuid.UUID
    crop_name: str
    farm_ref: str
    allocation_kg: JsonNumber
    harvest: dict[str, Any]
    prediction: dict[str, Any] | None


# ------------------------------------------------------------------ market
class SupplySummary(BaseModel):
    crop_id: uuid.UUID
    crop_name: str
    lots: int
    available_kg: JsonNumber
    earliest_harvest_start: date | None
    latest_harvest_end: date | None
    data_kind: DataKind = DataKind.ESTIMATE
    note: str = "Sum of p10 (pessimistic) predicted quantities still uncommitted on opted-in lots."


class Opportunity(BaseModel):
    demand_id: uuid.UUID
    crop_id: uuid.UUID
    crop_name: str
    quantity_kg: JsonNumber
    window_start: date
    window_end: date
    min_grade: QualityGrade
    buyer_type: BuyerType
    pooled: bool
    my_matching_cycles: int
