"""Harvest pool persistence and the supply/candidate queries."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import AllocationStatus, OrderStatus, ReservationStatus
from app.models.crop import CropCycle
from app.models.farm import Farm, FarmPlot
from app.models.intelligence import InventoryLot, InventoryReservation, PredictionFeedback, YieldPrediction
from app.models.marketplace import BuyerOrder
from app.models.pooling import (
    AllocationLedger,
    BuyerDemand,
    HarvestAllocation,
    HarvestPool,
    HarvestPoolMember,
    ReallocationEvent,
)
from app.repositories.base import paginate


class PoolingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ---------------------------------------------------------------- demands
    def add(self, obj: object) -> None:
        self.session.add(obj)
        self.session.flush()

    def demand_owned(self, demand_id: uuid.UUID, buyer_id: uuid.UUID, *, lock: bool = False) -> BuyerDemand | None:
        stmt = select(BuyerDemand).where(BuyerDemand.id == demand_id, BuyerDemand.buyer_id == buyer_id)
        return self.session.scalar(stmt.with_for_update() if lock else stmt)

    def demands(self, buyer_id: uuid.UUID, *, limit: int, offset: int) -> tuple[list[BuyerDemand], int]:
        stmt = (
            select(BuyerDemand)
            .where(BuyerDemand.buyer_id == buyer_id)
            .order_by(BuyerDemand.created_at.desc(), BuyerDemand.id)
        )
        return paginate(self.session, stmt, limit=limit, offset=offset)

    # ----------------------------------------------------------------- supply
    def lots_for_crop(self, crop_id: uuid.UUID, *, lock: bool) -> list[tuple[InventoryLot, CropCycle, Farm]]:
        """Every lot of the crop, row-locked in id order when `lock` (a fixed order prevents deadlocks)."""
        stmt = (
            select(InventoryLot, CropCycle, Farm)
            .join(CropCycle, CropCycle.id == InventoryLot.crop_cycle_id)
            .join(FarmPlot, FarmPlot.id == CropCycle.plot_id)
            .join(Farm, Farm.id == FarmPlot.farm_id)
            .where(CropCycle.crop_id == crop_id)
            .order_by(InventoryLot.id)
        )
        if lock:
            stmt = stmt.with_for_update(of=InventoryLot)
        return [(lot, cycle, farm) for lot, cycle, farm in self.session.execute(stmt).all()]

    def latest_prediction(self, cycle_id: uuid.UUID) -> YieldPrediction | None:
        stmt = (
            select(YieldPrediction)
            .where(YieldPrediction.crop_cycle_id == cycle_id)
            .order_by(YieldPrediction.version.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def reliability(self, owner_id: uuid.UUID) -> tuple[int, int]:
        """(predictions whose actual fell inside p10-p90, predictions scored) for this farmer."""
        stmt = (
            select(func.count(), func.count().filter(PredictionFeedback.within_interval.is_(True)))
            .select_from(PredictionFeedback)
            .join(YieldPrediction, YieldPrediction.id == PredictionFeedback.prediction_id)
            .join(CropCycle, CropCycle.id == YieldPrediction.crop_cycle_id)
            .join(FarmPlot, FarmPlot.id == CropCycle.plot_id)
            .join(Farm, Farm.id == FarmPlot.farm_id)
            .where(Farm.owner_id == owner_id)
        )
        n, hits = self.session.execute(stmt).one()
        return int(hits), int(n)

    def active_reservations(self, lot_id: uuid.UUID) -> list[InventoryReservation]:
        stmt = (
            select(InventoryReservation)
            .where(InventoryReservation.lot_id == lot_id, InventoryReservation.status == ReservationStatus.ACTIVE)
            .order_by(InventoryReservation.created_at, InventoryReservation.id)
        )
        return list(self.session.scalars(stmt))

    # ------------------------------------------------------------------ pools
    def pool(self, pool_id: uuid.UUID, *, lock: bool = False) -> HarvestPool | None:
        stmt = select(HarvestPool).where(HarvestPool.id == pool_id)
        return self.session.scalar(stmt.with_for_update() if lock else stmt)

    def pool_for_demand(self, demand_id: uuid.UUID) -> HarvestPool | None:
        return self.session.scalar(select(HarvestPool).where(HarvestPool.demand_id == demand_id))

    def pools(self, buyer_id: uuid.UUID | None, *, limit: int, offset: int) -> tuple[list[HarvestPool], int]:
        stmt = select(HarvestPool).order_by(HarvestPool.created_at.desc(), HarvestPool.id)
        if buyer_id is not None:
            stmt = stmt.where(HarvestPool.buyer_id == buyer_id)
        return paginate(self.session, stmt, limit=limit, offset=offset)

    def pools_using_lot(self, lot_id: uuid.UUID) -> list[uuid.UUID]:
        stmt = (
            select(HarvestAllocation.pool_id)
            .join(HarvestPool, HarvestPool.id == HarvestAllocation.pool_id)
            .where(
                HarvestAllocation.lot_id == lot_id, HarvestAllocation.quantity_kg > 0, HarvestPool.closed_at.is_(None)
            )
            .order_by(HarvestAllocation.pool_id)
        )
        return list(dict.fromkeys(self.session.scalars(stmt)))

    def short_pools_for_crop(self, crop_id: uuid.UUID, lot_id: uuid.UUID) -> list[uuid.UUID]:
        """Open pools of the crop still below their demand that have not excluded this lot, oldest first (the
        buyer who asked first is topped up first)."""
        declined = select(HarvestPoolMember.pool_id).where(
            HarvestPoolMember.lot_id == lot_id, HarvestPoolMember.excluded.is_(True)
        )
        stmt = (
            select(HarvestPool.id)
            .join(BuyerDemand, BuyerDemand.id == HarvestPool.demand_id)
            .where(
                BuyerDemand.crop_id == crop_id,
                HarvestPool.closed_at.is_(None),
                HarvestPool.allocated_kg < HarvestPool.demand_kg,
                HarvestPool.id.not_in(declined),
            )
            .order_by(HarvestPool.created_at, HarvestPool.id)
        )
        return list(self.session.scalars(stmt))

    def order_for_pool(self, pool_id: uuid.UUID) -> tuple[uuid.UUID, OrderStatus] | None:
        row = self.session.execute(
            select(BuyerOrder.id, BuyerOrder.status).where(BuyerOrder.pool_id == pool_id)
        ).first()
        return (row[0], row[1]) if row else None

    def allocations(self, pool_id: uuid.UUID) -> list[HarvestAllocation]:
        stmt = (
            select(HarvestAllocation)
            .where(HarvestAllocation.pool_id == pool_id)
            .order_by(HarvestAllocation.created_at, HarvestAllocation.id)
        )
        return list(self.session.scalars(stmt))

    def member(self, pool_id: uuid.UUID, lot_id: uuid.UUID) -> HarvestPoolMember | None:
        return self.session.scalar(
            select(HarvestPoolMember).where(HarvestPoolMember.pool_id == pool_id, HarvestPoolMember.lot_id == lot_id)
        )

    def excluded_lots(self, pool_id: uuid.UUID) -> set[str]:
        stmt = select(HarvestPoolMember.lot_id).where(
            HarvestPoolMember.pool_id == pool_id, HarvestPoolMember.excluded.is_(True)
        )
        done = select(HarvestAllocation.lot_id).where(
            HarvestAllocation.pool_id == pool_id, HarvestAllocation.status == AllocationStatus.FULFILLED
        )
        return {str(x) for x in self.session.scalars(stmt)} | {str(x) for x in self.session.scalars(done)}

    def event_by_key(self, key: str) -> ReallocationEvent | None:
        return self.session.scalar(select(ReallocationEvent).where(ReallocationEvent.idempotency_key == key))

    def events(self, pool_id: uuid.UUID) -> list[ReallocationEvent]:
        return list(
            self.session.scalars(
                select(ReallocationEvent)
                .where(ReallocationEvent.pool_id == pool_id)
                .order_by(ReallocationEvent.created_at, ReallocationEvent.id)
            )
        )

    def ledger(self, pool_id: uuid.UUID) -> list[AllocationLedger]:
        return list(
            self.session.scalars(
                select(AllocationLedger)
                .where(AllocationLedger.pool_id == pool_id)
                .order_by(AllocationLedger.created_at, AllocationLedger.id)
            )
        )

    def allocation_times(self, reservation_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
        """When each pool allocation was FIRST made, keyed by its current reservation (stable across resizes)."""
        if not reservation_ids:
            return {}
        stmt = select(HarvestAllocation.reservation_id, HarvestAllocation.created_at).where(
            HarvestAllocation.reservation_id.in_(reservation_ids)
        )
        return {rid: created for rid, created in self.session.execute(stmt).all() if rid is not None}

    @staticmethod
    def allocated_total(rows: list[HarvestAllocation]) -> Decimal:
        return sum((a.quantity_kg for a in rows), Decimal(0))
