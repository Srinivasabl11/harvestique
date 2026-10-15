"""Marketplace persistence: orders on pools, farmer participation, collection hubs, produce batches, quality.

Quantities only. Harvestique never stores or computes a price for an order (none is invented). Every quantity is
labelled by where it comes from: allocations are p10-based ESTIMATES, batches and quality checks are MEASURED.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import (
    BatchStatus,
    FarmerProgress,
    OrderItemStatus,
    OrderStatus,
    ParticipationStatus,
    QualityGrade,
    QualityResult,
)
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin, enum_column


class BuyerOrder(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    """A buyer's order placed on a harvest pool (one order per pool)."""

    __tablename__ = "buyer_orders"
    __table_args__ = (
        UniqueConstraint("pool_id", name="uq_buyer_orders_pool_id"),
        UniqueConstraint("buyer_id", "idempotency_key", name="uq_buyer_orders_buyer_id_idempotency_key"),
        CheckConstraint("ordered_kg > 0", name="ordered_positive"),
        CheckConstraint("fulfilled_kg >= 0 AND fulfilled_kg <= ordered_kg", name="fulfilled_within_order"),
    )

    buyer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    pool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("harvest_pools.id", ondelete="RESTRICT"))
    status: Mapped[OrderStatus] = mapped_column(enum_column(OrderStatus, name="order_status", length=24))
    ordered_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))  # the demand quantity
    fulfilled_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal(0))
    delivery_hub_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collection_hubs.id", ondelete="RESTRICT"))
    notes: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))


class FarmerParticipation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The farmer's answer to supplying one allocation of an ordered pool."""

    __tablename__ = "farmer_participations"
    __table_args__ = (UniqueConstraint("allocation_id", name="uq_farmer_participations_allocation_id"),)

    allocation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("harvest_allocations.id", ondelete="RESTRICT"))
    farmer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    status: Mapped[ParticipationStatus] = mapped_column(
        enum_column(ParticipationStatus, name="participation_status", length=16)
    )
    responded_at: Mapped[datetime | None]
    reason: Mapped[str | None] = mapped_column(String(255))
    # after accepting: "preparing" -> "ready" (forward only); the buyer is notified at each step
    progress: Mapped[FarmerProgress | None] = mapped_column(
        enum_column(FarmerProgress, name="farmer_progress", length=16)
    )
    progress_at: Mapped[datetime | None]


class BuyerOrderItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One farm's share of an order; mirrors a pool allocation and its reservation."""

    __tablename__ = "buyer_order_items"
    __table_args__ = (
        UniqueConstraint("allocation_id", name="uq_buyer_order_items_allocation_id"),
        CheckConstraint("quantity_kg >= 0 AND fulfilled_kg >= 0", name="quantities_non_negative"),
        CheckConstraint("fulfilled_kg <= quantity_kg", name="fulfilled_within_item"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buyer_orders.id", ondelete="RESTRICT"), index=True)
    allocation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("harvest_allocations.id", ondelete="RESTRICT"))
    lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_lots.id", ondelete="RESTRICT"), index=True)
    farmer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    participation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farmer_participations.id", ondelete="RESTRICT"))
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))  # current committed share (estimate)
    fulfilled_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal(0))  # measured, accepted
    status: Mapped[OrderItemStatus] = mapped_column(enum_column(OrderItemStatus, name="order_item_status", length=24))


class CollectionHub(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "collection_hubs"
    __table_args__ = (
        UniqueConstraint("name", name="uq_collection_hubs_name"),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="coordinates_paired"),
    )

    name: Mapped[str] = mapped_column(String(120))
    district: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(String(255))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())


class ProduceBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Produce physically received at a hub for one order item (MEASURED weight)."""

    __tablename__ = "produce_batches"
    __table_args__ = (
        UniqueConstraint("code", name="uq_produce_batches_code"),
        CheckConstraint("received_kg > 0", name="received_positive"),
        Index("ix_produce_batches_order_item_id", "order_item_id"),
    )

    code: Mapped[str] = mapped_column(String(24))  # human-readable, printed on the sack/crate
    order_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buyer_order_items.id", ondelete="RESTRICT"))
    lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_lots.id", ondelete="RESTRICT"))
    harvest_actual_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("harvest_actuals.id", ondelete="RESTRICT"))
    hub_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collection_hubs.id", ondelete="RESTRICT"), index=True)
    received_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    received_at: Mapped[datetime]
    received_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[BatchStatus] = mapped_column(enum_column(BatchStatus, name="batch_status", length=16))
    notes: Mapped[str | None] = mapped_column(Text)


class QualityCheck(UUIDPrimaryKeyMixin, Base):
    """MEASURED quality verification of a batch (one per batch, never edited)."""

    __tablename__ = "quality_checks"
    __table_args__ = (
        UniqueConstraint("batch_id", name="uq_quality_checks_batch_id"),
        CheckConstraint("accepted_kg >= 0 AND rejected_kg >= 0", name="quantities_non_negative"),
        CheckConstraint(
            "moisture_percent IS NULL OR (moisture_percent >= 0 AND moisture_percent <= 100)", name="moisture_range"
        ),
        CheckConstraint(
            "(result = 'accepted' AND rejected_kg = 0 AND accepted_kg > 0)"
            " OR (result = 'rejected' AND accepted_kg = 0)"
            " OR (result = 'partially_accepted' AND accepted_kg > 0 AND rejected_kg > 0)",
            name="result_matches_quantities",
        ),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("produce_batches.id", ondelete="RESTRICT"))
    inspector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    grade: Mapped[QualityGrade | None] = mapped_column(enum_column(QualityGrade, name="quality_grade", length=2))
    result: Mapped[QualityResult] = mapped_column(enum_column(QualityResult, name="quality_result", length=24))
    accepted_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    rejected_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    moisture_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    defects: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime]
