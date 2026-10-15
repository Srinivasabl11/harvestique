"""Persistence for the intelligence layer. Owner scoping follows the farm chain like Phase 2."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Select, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.enums import CycleStatus, OrderItemStatus, PredictionStatus, ReservationStatus, WeatherKind
from app.models.crop import CropCycle
from app.models.farm import Farm, FarmPlot
from app.models.intelligence import (
    CalibrationProfile,
    HarvestActual,
    InventoryLot,
    InventoryReservation,
    PredictionFeedback,
    WeatherDaily,
    YieldPrediction,
)
from app.models.marketplace import BuyerOrderItem
from app.repositories.base import paginate


class WeatherRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, rows: Iterable[dict[str, object]]) -> None:
        rows = list(rows)
        if not rows:
            return
        stmt = insert(WeatherDaily).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_weather_daily_point_day_kind",
            set_={c: stmt.excluded[c] for c in ("tmin_c", "tmax_c", "rain_mm", "et0_mm", "source", "fetched_at")},
        )
        self.session.execute(stmt)

    def rows(self, lat: Decimal, lon: Decimal, kind: WeatherKind, start: date, end: date) -> list[WeatherDaily]:
        stmt = (
            select(WeatherDaily)
            .where(WeatherDaily.lat_key == lat, WeatherDaily.lon_key == lon, WeatherDaily.kind == kind)
            .where(WeatherDaily.day >= start, WeatherDaily.day <= end)
            .order_by(WeatherDaily.day)
        )
        return list(self.session.scalars(stmt))

    def last_fetched(self, lat: Decimal, lon: Decimal, kind: WeatherKind) -> datetime | None:
        stmt = select(func.max(WeatherDaily.fetched_at)).where(
            WeatherDaily.lat_key == lat, WeatherDaily.lon_key == lon, WeatherDaily.kind == kind
        )
        return self.session.scalar(stmt)


def _owned_cycle_ids(owner_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    return (
        select(CropCycle.id)
        .join(FarmPlot, FarmPlot.id == CropCycle.plot_id)
        .join(Farm, Farm.id == FarmPlot.farm_id)
        .where(Farm.owner_id == owner_id)
    )


class PredictionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def lock_cycle(self, cycle_id: uuid.UUID, owner_id: uuid.UUID) -> CropCycle | None:
        """Row lock on the cycle: serialises version numbering and inventory sync."""
        stmt = (
            select(CropCycle)
            .join(FarmPlot, FarmPlot.id == CropCycle.plot_id)
            .join(Farm, Farm.id == FarmPlot.farm_id)
            .where(CropCycle.id == cycle_id, Farm.owner_id == owner_id)
            .with_for_update(of=CropCycle)
        )
        return self.session.scalar(stmt)

    def latest(self, cycle_id: uuid.UUID) -> YieldPrediction | None:
        stmt = (
            select(YieldPrediction)
            .where(YieldPrediction.crop_cycle_id == cycle_id)
            .order_by(YieldPrediction.version.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def add(self, row: YieldPrediction) -> YieldPrediction:
        self.session.add(row)
        self.session.flush()
        return row

    def list_for_cycle(self, cycle_id: uuid.UUID, *, limit: int, offset: int) -> tuple[list[YieldPrediction], int]:
        stmt = (
            select(YieldPrediction)
            .where(YieldPrediction.crop_cycle_id == cycle_id)
            .order_by(YieldPrediction.version.desc())
        )
        return paginate(self.session, stmt, limit=limit, offset=offset)

    def all_for_cycle(self, cycle_id: uuid.UUID) -> list[YieldPrediction]:
        stmt = (
            select(YieldPrediction).where(YieldPrediction.crop_cycle_id == cycle_id).order_by(YieldPrediction.version)
        )
        return list(self.session.scalars(stmt))

    def get_owned(self, prediction_id: uuid.UUID, owner_id: uuid.UUID) -> YieldPrediction | None:
        stmt = select(YieldPrediction).where(
            YieldPrediction.id == prediction_id, YieldPrediction.crop_cycle_id.in_(_owned_cycle_ids(owner_id))
        )
        return self.session.scalar(stmt)

    def latest_for_open_cycles(self, farm_id: uuid.UUID) -> list[tuple[CropCycle, YieldPrediction]]:
        latest = (
            select(YieldPrediction.crop_cycle_id, func.max(YieldPrediction.version).label("v"))
            .group_by(YieldPrediction.crop_cycle_id)
            .subquery()
        )
        stmt = (
            select(CropCycle, YieldPrediction)
            .join(FarmPlot, FarmPlot.id == CropCycle.plot_id)
            .join(YieldPrediction, YieldPrediction.crop_cycle_id == CropCycle.id)
            .join(
                latest,
                (latest.c.crop_cycle_id == YieldPrediction.crop_cycle_id) & (latest.c.v == YieldPrediction.version),
            )
            .where(FarmPlot.farm_id == farm_id, CropCycle.status.in_([CycleStatus.PLANNED, CycleStatus.GROWING]))
            .order_by(CropCycle.sowing_date, CropCycle.id)
        )
        return [(c, p) for c, p in self.session.execute(stmt).all()]


class ActualRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def batches_received(self, actual_id: uuid.UUID) -> int:
        """Produce batches made from this harvest (collected at a hub): the harvest can no longer be corrected."""
        from app.models.marketplace import ProduceBatch

        stmt = select(func.count()).select_from(ProduceBatch).where(ProduceBatch.harvest_actual_id == actual_id)
        return int(self.session.scalar(stmt) or 0)

    def for_cycle(self, cycle_id: uuid.UUID) -> HarvestActual | None:
        return self.session.scalar(select(HarvestActual).where(HarvestActual.crop_cycle_id == cycle_id))

    def add(self, row: HarvestActual) -> HarvestActual:
        self.session.add(row)
        self.session.flush()
        return row

    def history(
        self, owner_id: uuid.UUID, crop_id: uuid.UUID, exclude_cycle: uuid.UUID
    ) -> list[tuple[Decimal, Decimal, date]]:
        """(quantity, area, harvest date) of the owner's recorded harvests of this crop."""
        stmt = (
            select(HarvestActual.quantity_kg, CropCycle.area_acres, HarvestActual.harvest_start_date)
            .join(CropCycle, CropCycle.id == HarvestActual.crop_cycle_id)
            .where(
                CropCycle.crop_id == crop_id,
                CropCycle.id != exclude_cycle,
                CropCycle.id.in_(_owned_cycle_ids(owner_id)),
            )
            .order_by(HarvestActual.harvest_start_date)
        )
        return [(q, a, d) for q, a, d in self.session.execute(stmt).all()]


class FeedbackRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def delete_for_actual(self, actual_id: uuid.UUID) -> None:
        self.session.execute(delete(PredictionFeedback).where(PredictionFeedback.harvest_actual_id == actual_id))

    def add(self, row: PredictionFeedback) -> None:
        self.session.add(row)

    def for_cycle(self, cycle_id: uuid.UUID) -> list[tuple[PredictionFeedback, YieldPrediction]]:
        stmt = (
            select(PredictionFeedback, YieldPrediction)
            .join(YieldPrediction, YieldPrediction.id == PredictionFeedback.prediction_id)
            .where(YieldPrediction.crop_cycle_id == cycle_id)
            .order_by(YieldPrediction.version)
        )
        return [(f, p) for f, p in self.session.execute(stmt).all()]

    def outcomes(self, crop_id: uuid.UUID | None) -> list[tuple[YieldPrediction, HarvestActual, PredictionFeedback]]:
        """One outcome per harvested cycle: its LAST usable prediction (made before the actual was recorded)."""
        latest_ok = (
            select(YieldPrediction.crop_cycle_id, func.max(YieldPrediction.version).label("v"))
            .where(YieldPrediction.status == PredictionStatus.OK)
            .group_by(YieldPrediction.crop_cycle_id)
            .subquery()
        )
        stmt = (
            select(YieldPrediction, HarvestActual, PredictionFeedback)
            .join(
                latest_ok,
                (latest_ok.c.crop_cycle_id == YieldPrediction.crop_cycle_id)
                & (latest_ok.c.v == YieldPrediction.version),
            )
            .join(HarvestActual, HarvestActual.crop_cycle_id == YieldPrediction.crop_cycle_id)
            .join(PredictionFeedback, PredictionFeedback.prediction_id == YieldPrediction.id)
            .join(CropCycle, CropCycle.id == YieldPrediction.crop_cycle_id)
        )
        if crop_id is not None:
            stmt = stmt.where(CropCycle.crop_id == crop_id)
        return [(p, a, f) for p, a, f in self.session.execute(stmt.order_by(HarvestActual.created_at)).all()]


class CalibrationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def latest(self, scope: str) -> CalibrationProfile | None:
        stmt = (
            select(CalibrationProfile)
            .where(CalibrationProfile.scope == scope)
            .order_by(CalibrationProfile.version.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def next_version(self, scope: str) -> int:
        current = self.session.scalar(
            select(func.max(CalibrationProfile.version)).where(CalibrationProfile.scope == scope)
        )
        return (current or 0) + 1

    def add(self, row: CalibrationProfile) -> CalibrationProfile:
        self.session.add(row)
        self.session.flush()
        return row

    def latest_all(self) -> list[CalibrationProfile]:
        latest = (
            select(CalibrationProfile.scope, func.max(CalibrationProfile.version).label("v"))
            .group_by(CalibrationProfile.scope)
            .subquery()
        )
        stmt = (
            select(CalibrationProfile)
            .join(latest, (latest.c.scope == CalibrationProfile.scope) & (latest.c.v == CalibrationProfile.version))
            .order_by(CalibrationProfile.scope)
        )
        return list(self.session.scalars(stmt))


class InventoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def lot_for_cycle(self, cycle_id: uuid.UUID) -> InventoryLot | None:
        return self.session.scalar(select(InventoryLot).where(InventoryLot.crop_cycle_id == cycle_id))

    def add_lot(self, lot: InventoryLot) -> InventoryLot:
        self.session.add(lot)
        self.session.flush()
        return lot

    def get_owned_lot(self, lot_id: uuid.UUID, owner_id: uuid.UUID, *, for_update: bool = False) -> InventoryLot | None:
        stmt = select(InventoryLot).where(InventoryLot.id == lot_id, InventoryLot.owner_id == owner_id)
        if for_update:
            stmt = stmt.with_for_update()
        return self.session.scalar(stmt)

    def list_owned(self, owner_id: uuid.UUID, *, limit: int, offset: int) -> tuple[list[InventoryLot], int]:
        stmt = (
            select(InventoryLot)
            .where(InventoryLot.owner_id == owner_id)
            .order_by(InventoryLot.created_at.desc(), InventoryLot.id)
        )
        return paginate(self.session, stmt, limit=limit, offset=offset)

    def reservations(self, lot_id: uuid.UUID) -> list[InventoryReservation]:
        stmt = (
            select(InventoryReservation)
            .where(InventoryReservation.lot_id == lot_id)
            .order_by(InventoryReservation.created_at, InventoryReservation.id)
        )
        return list(self.session.scalars(stmt))

    def order_quantities(self, lot_id: uuid.UUID) -> list[tuple[OrderItemStatus, Decimal, Decimal]]:
        """(status, ordered kg, fulfilled kg) per buyer order item status on this lot."""
        stmt = (
            select(BuyerOrderItem.status, func.sum(BuyerOrderItem.quantity_kg), func.sum(BuyerOrderItem.fulfilled_kg))
            .where(BuyerOrderItem.lot_id == lot_id)
            .group_by(BuyerOrderItem.status)
        )
        return [(s, q, f) for s, q, f in self.session.execute(stmt)]

    def get_owned_reservation(self, reservation_id: uuid.UUID, owner_id: uuid.UUID) -> InventoryReservation | None:
        stmt = (
            select(InventoryReservation)
            .join(InventoryLot, InventoryLot.id == InventoryReservation.lot_id)
            .where(InventoryReservation.id == reservation_id, InventoryLot.owner_id == owner_id)
        )
        return self.session.scalar(stmt)

    def add_reservation(self, row: InventoryReservation) -> InventoryReservation:
        self.session.add(row)
        self.session.flush()
        return row

    @staticmethod
    def totals(rows: Sequence[InventoryReservation]) -> tuple[Decimal, Decimal]:
        active = sum((r.quantity_kg for r in rows if r.status is ReservationStatus.ACTIVE), Decimal(0))
        fulfilled = sum((r.quantity_kg for r in rows if r.status is ReservationStatus.FULFILLED), Decimal(0))
        return active, fulfilled
