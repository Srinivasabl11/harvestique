"""Harvest pooling persistence. HarvestReservation = the Phase 4 `inventory_reservations` row an allocation points
to (no duplicate reservation table). Reallocation events and the ledger are APPEND-ONLY."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AllocationStatus, DemandStatus, PoolAlgorithm, PoolStatus, QualityGrade, ReallocationOutcome
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin, enum_column
from app.models.intelligence import JSONType


class BuyerDemand(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "buyer_demands"
    __table_args__ = (
        CheckConstraint("quantity_kg > 0", name="quantity_positive"),
        CheckConstraint("window_end >= window_start", name="window_ordered"),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="coordinates_paired"),
        CheckConstraint("max_distance_km IS NULL OR max_distance_km > 0", name="distance_positive"),
        CheckConstraint("min_confidence BETWEEN 0 AND 100 AND max_risk BETWEEN 0 AND 100", name="thresholds_range"),
    )

    buyer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id", ondelete="RESTRICT"), index=True)
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    min_grade: Mapped[QualityGrade] = mapped_column(
        enum_column(QualityGrade, name="min_grade", length=2), default=QualityGrade.C
    )
    window_start: Mapped[date]
    window_end: Mapped[date]
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    max_distance_km: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    min_confidence: Mapped[Decimal] = mapped_column(Numeric(4, 1), default=Decimal(0))
    max_risk: Mapped[Decimal] = mapped_column(Numeric(4, 1), default=Decimal(100))
    status: Mapped[DemandStatus] = mapped_column(
        enum_column(DemandStatus, name="demand_status", length=16), default=DemandStatus.OPEN
    )
    notes: Mapped[str | None] = mapped_column(Text)


class HarvestPool(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "harvest_pools"
    __table_args__ = (
        UniqueConstraint("demand_id", name="uq_harvest_pools_demand_id"),
        UniqueConstraint("buyer_id", "idempotency_key", name="uq_harvest_pools_buyer_id_idempotency_key"),
        CheckConstraint("allocated_kg >= 0 AND allocated_kg <= demand_kg", name="allocated_within_demand"),
        CheckConstraint("shortage_kg >= 0", name="shortage_non_negative"),
    )

    demand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buyer_demands.id", ondelete="RESTRICT"))
    buyer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    status: Mapped[PoolStatus] = mapped_column(enum_column(PoolStatus, name="pool_status", length=16))
    algorithm: Mapped[PoolAlgorithm] = mapped_column(enum_column(PoolAlgorithm, name="pool_algorithm", length=16))
    demand_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    allocated_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    shortage_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))  # unresolved after the last reallocation
    max_pool_risk: Mapped[Decimal] = mapped_column(Numeric(4, 1))
    max_share: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    weights: Mapped[dict[str, Any]] = mapped_column(JSONType)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    # Phase 6: a pool is closed when its order is cancelled or completed; closed pools are never rebalanced
    closed_at: Mapped[datetime | None]
    close_reason: Mapped[str | None] = mapped_column(String(80))


class HarvestPoolMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A farm lot that has supplied the pool, with its latest explainable score."""

    __tablename__ = "harvest_pool_members"
    __table_args__ = (UniqueConstraint("pool_id", "lot_id", name="uq_harvest_pool_members_pool_id_lot_id"),)

    pool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("harvest_pools.id", ondelete="RESTRICT"), index=True)
    lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_lots.id", ondelete="RESTRICT"), index=True)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    components: Mapped[dict[str, Any]] = mapped_column(JSONType)
    # Phase 6: the farmer declined this pool; the lot is never offered to it again
    excluded: Mapped[bool] = mapped_column(default=False, server_default=false())


class HarvestAllocation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "harvest_allocations"
    __table_args__ = (
        UniqueConstraint("pool_id", "lot_id", name="uq_harvest_allocations_pool_id_lot_id"),
        CheckConstraint("quantity_kg >= 0", name="quantity_non_negative"),
    )

    pool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("harvest_pools.id", ondelete="RESTRICT"), index=True)
    lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_lots.id", ondelete="RESTRICT"), index=True)
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("harvest_pool_members.id", ondelete="RESTRICT"))
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    status: Mapped[AllocationStatus] = mapped_column(enum_column(AllocationStatus, name="allocation_status", length=16))
    risk_level: Mapped[str] = mapped_column(String(20))
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_reservations.id", ondelete="RESTRICT")
    )
    reservation_seq: Mapped[int] = mapped_column(Integer, default=1)  # bumps when the reservation is replaced


class ReallocationEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "reallocation_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_reallocation_events_idempotency_key"),
        CheckConstraint("shortage_kg >= 0 AND replaced_kg >= 0 AND unresolved_kg >= 0", name="quantities_non_negative"),
        CheckConstraint("replaced_kg + unresolved_kg >= shortage_kg - 0.001", name="shortage_accounted"),
    )

    pool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("harvest_pools.id", ondelete="RESTRICT"), index=True)
    trigger: Mapped[str] = mapped_column(String(40))  # prediction_change / manual
    trigger_ref: Mapped[str | None] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    outcome: Mapped[ReallocationOutcome] = mapped_column(
        enum_column(ReallocationOutcome, name="reallocation_outcome", length=16)
    )
    algorithm: Mapped[str] = mapped_column(String(16))
    shortage_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    replaced_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unresolved_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    topped_up_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    steps: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    before: Mapped[dict[str, Any]] = mapped_column(JSONType)
    after: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AllocationLedger(UUIDPrimaryKeyMixin, Base):
    """Append-only audit trail: every quantity change of every allocation, with its reason."""

    __tablename__ = "allocation_ledger"
    __table_args__ = (CheckConstraint("quantity_before >= 0 AND quantity_after >= 0", name="quantities_non_negative"),)

    pool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("harvest_pools.id", ondelete="RESTRICT"), index=True)
    allocation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("harvest_allocations.id", ondelete="RESTRICT"))
    lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_lots.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(32))  # allocated / reduced / released / replacement_added / topped_up
    quantity_before: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    quantity_after: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    reason: Mapped[str] = mapped_column(Text)
    reallocation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reallocation_events.id", ondelete="RESTRICT")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
