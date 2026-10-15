"""Marketplace persistence and read queries (orders, participation, hubs, batches, quality, dashboard)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import CycleStatus, DemandStatus, LotStatus, OrderStatus, ParticipationStatus
from app.models.crop import Crop, CropCycle
from app.models.farm import Farm, FarmPlot
from app.models.intelligence import HarvestActual, InventoryLot, PredictionFeedback, YieldPrediction
from app.models.marketplace import (
    BuyerOrder,
    BuyerOrderItem,
    CollectionHub,
    FarmerParticipation,
    ProduceBatch,
    QualityCheck,
)
from app.models.pooling import BuyerDemand
from app.repositories.base import paginate


class MarketplaceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, obj: object) -> None:
        self.session.add(obj)
        self.session.flush()

    # ----------------------------------------------------------------- orders
    def order(self, order_id: uuid.UUID, *, lock: bool = False) -> BuyerOrder | None:
        stmt = select(BuyerOrder).where(BuyerOrder.id == order_id)
        return self.session.scalar(stmt.with_for_update() if lock else stmt)

    def order_for_pool(self, pool_id: uuid.UUID, *, lock: bool = False) -> BuyerOrder | None:
        stmt = select(BuyerOrder).where(BuyerOrder.pool_id == pool_id)
        return self.session.scalar(stmt.with_for_update() if lock else stmt)

    def orders(
        self, buyer_id: uuid.UUID | None, status: OrderStatus | None, *, limit: int, offset: int
    ) -> tuple[list[BuyerOrder], int]:
        stmt = select(BuyerOrder).order_by(BuyerOrder.created_at.desc(), BuyerOrder.id)
        if buyer_id is not None:
            stmt = stmt.where(BuyerOrder.buyer_id == buyer_id)
        if status is not None:
            stmt = stmt.where(BuyerOrder.status == status)
        return paginate(self.session, stmt, limit=limit, offset=offset)

    def items(self, order_id: uuid.UUID) -> list[BuyerOrderItem]:
        stmt = (
            select(BuyerOrderItem)
            .where(BuyerOrderItem.order_id == order_id)
            .order_by(BuyerOrderItem.created_at, BuyerOrderItem.id)
        )
        return list(self.session.scalars(stmt))

    def item(self, item_id: uuid.UUID) -> BuyerOrderItem | None:
        return self.session.get(BuyerOrderItem, item_id)

    def item_for_allocation(self, allocation_id: uuid.UUID) -> BuyerOrderItem | None:
        return self.session.scalar(select(BuyerOrderItem).where(BuyerOrderItem.allocation_id == allocation_id))

    def any_batch(self, order_id: uuid.UUID) -> bool:
        stmt = (
            select(func.count())
            .select_from(ProduceBatch)
            .join(BuyerOrderItem, BuyerOrderItem.id == ProduceBatch.order_item_id)
            .where(BuyerOrderItem.order_id == order_id)
        )
        return bool(self.session.scalar(stmt))

    # ---------------------------------------------------------- participation
    def participation(self, participation_id: uuid.UUID) -> FarmerParticipation | None:
        return self.session.get(FarmerParticipation, participation_id)

    def participations(
        self, farmer_id: uuid.UUID, status: ParticipationStatus | None, *, limit: int, offset: int
    ) -> tuple[list[FarmerParticipation], int]:
        stmt = select(FarmerParticipation).where(FarmerParticipation.farmer_id == farmer_id)
        if status is not None:
            stmt = stmt.where(FarmerParticipation.status == status)
        return paginate(
            self.session,
            stmt.order_by(FarmerParticipation.created_at.desc(), FarmerParticipation.id),
            limit=limit,
            offset=offset,
        )

    def item_for_participation(self, participation_id: uuid.UUID) -> BuyerOrderItem | None:
        return self.session.scalar(select(BuyerOrderItem).where(BuyerOrderItem.participation_id == participation_id))

    # ------------------------------------------------------------- lots/farms
    def lot_context(self, lot_id: uuid.UUID) -> tuple[InventoryLot, CropCycle, Farm]:
        stmt = (
            select(InventoryLot, CropCycle, Farm)
            .join(CropCycle, CropCycle.id == InventoryLot.crop_cycle_id)
            .join(FarmPlot, FarmPlot.id == CropCycle.plot_id)
            .join(Farm, Farm.id == FarmPlot.farm_id)
            .where(InventoryLot.id == lot_id)
        )
        lot, cycle, farm = self.session.execute(stmt).one()
        return lot, cycle, farm

    def harvest_for_cycle(self, cycle_id: uuid.UUID) -> HarvestActual | None:
        return self.session.scalar(select(HarvestActual).where(HarvestActual.crop_cycle_id == cycle_id))

    def predictions(self, cycle_id: uuid.UUID) -> list[YieldPrediction]:
        stmt = (
            select(YieldPrediction).where(YieldPrediction.crop_cycle_id == cycle_id).order_by(YieldPrediction.version)
        )
        return list(self.session.scalars(stmt))

    # ------------------------------------------------------------------- hubs
    def hub(self, hub_id: uuid.UUID) -> CollectionHub | None:
        return self.session.get(CollectionHub, hub_id)

    def hubs(self, active_only: bool) -> list[CollectionHub]:
        stmt = select(CollectionHub).order_by(CollectionHub.name)
        if active_only:
            stmt = stmt.where(CollectionHub.is_active.is_(True))
        return list(self.session.scalars(stmt))

    # ---------------------------------------------------------------- batches
    def batches_for_item(self, item_id: uuid.UUID) -> list[ProduceBatch]:
        stmt = (
            select(ProduceBatch)
            .where(ProduceBatch.order_item_id == item_id)
            .order_by(ProduceBatch.received_at, ProduceBatch.id)
        )
        return list(self.session.scalars(stmt))

    def batch(self, batch_id: uuid.UUID, *, lock: bool = False) -> ProduceBatch | None:
        stmt = select(ProduceBatch).where(ProduceBatch.id == batch_id)
        return self.session.scalar(stmt.with_for_update() if lock else stmt)

    def batch_by_code(self, code: str) -> ProduceBatch | None:
        return self.session.scalar(select(ProduceBatch).where(ProduceBatch.code == code.upper()))

    def batches(
        self, hub_id: uuid.UUID | None, awaiting_quality: bool, *, limit: int, offset: int
    ) -> tuple[list[ProduceBatch], int]:
        stmt = select(ProduceBatch).order_by(ProduceBatch.received_at.desc(), ProduceBatch.id)
        if hub_id is not None:
            stmt = stmt.where(ProduceBatch.hub_id == hub_id)
        if awaiting_quality:
            stmt = stmt.where(~select(QualityCheck.id).where(QualityCheck.batch_id == ProduceBatch.id).exists())
        return paginate(self.session, stmt, limit=limit, offset=offset)

    def quality(self, batch_id: uuid.UUID) -> QualityCheck | None:
        return self.session.scalar(select(QualityCheck).where(QualityCheck.batch_id == batch_id))

    # ----------------------------------------------------------------- market
    def supply_summary(self) -> list[tuple[uuid.UUID, str, int, Decimal, date | None, date | None]]:
        latest = (
            select(YieldPrediction.crop_cycle_id, func.max(YieldPrediction.version).label("v"))
            .group_by(YieldPrediction.crop_cycle_id)
            .subquery()
        )
        stmt = (
            select(
                Crop.id,
                Crop.name,
                func.count(InventoryLot.id),
                func.coalesce(func.sum(InventoryLot.available_kg), 0),
                func.min(YieldPrediction.harvest_start_p10),
                func.max(YieldPrediction.harvest_end_p90),
            )
            .select_from(InventoryLot)
            .join(CropCycle, CropCycle.id == InventoryLot.crop_cycle_id)
            .join(Crop, Crop.id == CropCycle.crop_id)
            .join(latest, latest.c.crop_cycle_id == CropCycle.id)
            .join(
                YieldPrediction,
                (YieldPrediction.crop_cycle_id == latest.c.crop_cycle_id) & (YieldPrediction.version == latest.c.v),
            )
            .where(
                InventoryLot.pool_eligible.is_(True),
                InventoryLot.status == LotStatus.OPEN,
                InventoryLot.available_kg > 0,
            )
            .group_by(Crop.id, Crop.name)
            .order_by(Crop.name)
        )
        return [(a, b, int(c), Decimal(d), e, f) for a, b, c, d, e, f in self.session.execute(stmt).all()]

    def open_demands_for_farmer(self, farmer_id: uuid.UUID) -> list[tuple[BuyerDemand, str, int]]:
        """Open demands for crops the farmer has planned or growing cycles of (with how many such cycles)."""
        mine = (
            select(CropCycle.crop_id, func.count(CropCycle.id).label("n"))
            .join(FarmPlot, FarmPlot.id == CropCycle.plot_id)
            .join(Farm, Farm.id == FarmPlot.farm_id)
            .where(Farm.owner_id == farmer_id, CropCycle.status.in_([CycleStatus.PLANNED, CycleStatus.GROWING]))
            .group_by(CropCycle.crop_id)
            .subquery()
        )
        stmt = (
            select(BuyerDemand, Crop.name, mine.c.n)
            .join(mine, mine.c.crop_id == BuyerDemand.crop_id)
            .join(Crop, Crop.id == BuyerDemand.crop_id)
            .where(BuyerDemand.status.in_([DemandStatus.OPEN, DemandStatus.POOLED]))
            .order_by(BuyerDemand.window_start, BuyerDemand.id)
        )
        return [(d, name, int(n)) for d, name, n in self.session.execute(stmt).all()]

    def farmers_growing(self, crop_id: uuid.UUID) -> list[uuid.UUID]:
        stmt = (
            select(Farm.owner_id)
            .join(FarmPlot, FarmPlot.farm_id == Farm.id)
            .join(CropCycle, CropCycle.plot_id == FarmPlot.id)
            .where(CropCycle.crop_id == crop_id, CropCycle.status.in_([CycleStatus.PLANNED, CycleStatus.GROWING]))
            .distinct()
        )
        return list(self.session.scalars(stmt))

    # ----------------------------------------------------------------- counts
    def count_by(self, column: object, model: type) -> dict[str, int]:
        rows = self.session.execute(select(column, func.count()).select_from(model).group_by(column)).all()  # type: ignore[call-overload]
        return {str(getattr(k, "value", k)): int(n) for k, n in rows}

    def scalar(self, stmt: object) -> object:
        return self.session.scalar(stmt)  # type: ignore[call-overload]

    def received_since(self, since: datetime) -> int:
        stmt = select(func.count()).select_from(ProduceBatch).where(ProduceBatch.received_at >= since)
        return int(self.session.scalar(stmt) or 0)

    def feedback_for_cycle(self, cycle_id: uuid.UUID) -> list[tuple[int, PredictionFeedback]]:
        """(prediction version, PredictionFeedback) for every scored version of the cycle."""
        stmt = (
            select(YieldPrediction.version, PredictionFeedback)
            .join(PredictionFeedback, PredictionFeedback.prediction_id == YieldPrediction.id)
            .where(YieldPrediction.crop_cycle_id == cycle_id)
            .order_by(YieldPrediction.version)
        )
        return [(int(v), f) for v, f in self.session.execute(stmt).all()]
