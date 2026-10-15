"""Virtual harvest inventory: reservations against uncertain (then measured) supply.

Every change locks the lot row, so two concurrent reservations cannot both pass the availability check.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.enums import LotStatus, OrderItemStatus, ReservationStatus
from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.domain.inventory import (
    InventoryError,
    check_fulfil,
    check_release,
    check_reservation,
    check_shrink,
    derive_lot,
)
from app.models.crop import CropCycle
from app.models.farm import Farm, FarmPlot
from app.models.intelligence import InventoryLot, InventoryReservation
from app.repositories.intelligence import ActualRepository, InventoryRepository, PredictionRepository
from app.schemas.common import Page
from app.schemas.intelligence import LotDetail, LotOut, ReservationIn, ReservationOut
from app.services._common import conflict_on_integrity

ZERO = Decimal(0)


def _translate(exc: InventoryError) -> Exception:
    if exc.code in ("over_allocation", "duplicate_booking", "lot_closed", "not_harvested", "reservation_not_active"):
        return ConflictError(exc.message, code=exc.code)
    return DomainValidationError(exc.message, code=exc.code)


class InventoryService:
    def __init__(
        self,
        *,
        session: Session,
        repo: InventoryRepository,
        predictions: PredictionRepository,
        actuals: ActualRepository,
    ) -> None:
        self._session = session
        self._repo = repo
        self._predictions = predictions
        self._actuals = actuals

    def sync_lot(self, cycle: CropCycle, owner_id: uuid.UUID) -> InventoryLot:
        """Create or refresh the cycle's lot from its latest prediction, measured actual and reservations."""
        lot = self._repo.lot_for_cycle(cycle.id)
        if lot is None:
            lot = InventoryLot(
                crop_cycle_id=cycle.id,
                owner_id=owner_id,
                status=LotStatus.OPEN,
                committable_kg=ZERO,
                committed_kg=ZERO,
                available_kg=ZERO,
                shortfall_kg=ZERO,
                basis="",
            )
            self._repo.add_lot(lot)
        latest = self._predictions.latest(cycle.id)
        actual = self._actuals.for_cycle(cycle.id)
        active, fulfilled = self._repo.totals(self._repo.reservations(lot.id))
        view = derive_lot(
            cycle.status, latest.p10_kg if latest else None, actual.quantity_kg if actual else None, active, fulfilled
        )
        lot.prediction_id = latest.id if latest else None
        lot.p10_kg, lot.p50_kg, lot.p90_kg = (
            (latest.p10_kg, latest.p50_kg, latest.p90_kg) if latest else (None, None, None)
        )
        lot.actual_kg = actual.quantity_kg if actual else None
        lot.status = view.status
        lot.committable_kg, lot.committed_kg = view.committable_kg, view.committed_kg
        lot.available_kg, lot.shortfall_kg, lot.basis = view.available_kg, view.shortfall_kg, view.basis
        return lot

    def list_lots(self, owner_id: uuid.UUID, *, limit: int, offset: int) -> Page[LotOut]:
        lots, total = self._repo.list_owned(owner_id, limit=limit, offset=offset)
        for lot in lots:
            self._resync(lot)
        self._session.commit()
        return Page[LotOut](items=[self._out(x) for x in lots], total=total, limit=limit, offset=offset)

    def get_lot(self, owner_id: uuid.UUID, lot_id: uuid.UUID) -> LotDetail:
        lot = self._require(owner_id, lot_id)
        self._resync(lot)
        self._session.commit()
        return self._detail(lot)

    def reserve(self, owner_id: uuid.UUID, lot_id: uuid.UUID, payload: ReservationIn) -> ReservationOut:
        lot = self._require(owner_id, lot_id, for_update=True)
        self._resync(lot)
        rows = self._repo.reservations(lot.id)
        active, fulfilled = self._repo.totals(rows)
        cycle = self._session.get(CropCycle, lot.crop_cycle_id)
        assert cycle is not None
        view = derive_lot(cycle.status, lot.p10_kg, lot.actual_kg, active, fulfilled)
        try:
            check_reservation(view, payload.quantity_kg, payload.booking_key, {r.booking_key for r in rows})
        except InventoryError as exc:
            raise _translate(exc) from exc
        with conflict_on_integrity(
            self._session, "This booking key has already been used for this lot", "duplicate_booking"
        ):
            row = self._repo.add_reservation(
                InventoryReservation(
                    lot_id=lot.id,
                    quantity_kg=payload.quantity_kg,
                    booking_key=payload.booking_key,
                    note=payload.note,
                    status=ReservationStatus.ACTIVE,
                )
            )
            self._resync(lot)
            self._session.commit()
        return ReservationOut.model_validate(row)

    def release(self, owner_id: uuid.UUID, reservation_id: uuid.UUID) -> ReservationOut:
        row, lot = self._locked_reservation(owner_id, reservation_id)
        try:
            check_release(row.status)
        except InventoryError as exc:
            raise _translate(exc) from exc
        row.status = ReservationStatus.RELEASED
        self._session.flush()
        self._resync(lot)
        self._session.commit()
        return ReservationOut.model_validate(row)

    def fulfil(self, owner_id: uuid.UUID, reservation_id: uuid.UUID) -> ReservationOut:
        row, lot = self._locked_reservation(owner_id, reservation_id)
        cycle = self._session.get(CropCycle, lot.crop_cycle_id)
        assert cycle is not None
        active, fulfilled = self._repo.totals(self._repo.reservations(lot.id))
        view = derive_lot(cycle.status, lot.p10_kg, lot.actual_kg, active, fulfilled)
        try:
            check_fulfil(view, row.status)
        except InventoryError as exc:
            raise _translate(exc) from exc
        row.status = ReservationStatus.FULFILLED
        self._session.flush()
        self._resync(lot)
        self._session.commit()
        return ReservationOut.model_validate(row)

    # ------------------------------------------- internal (used by harvest pools)

    def reserve_locked(
        self, lot: InventoryLot, quantity_kg: Decimal, booking_key: str, note: str
    ) -> InventoryReservation:
        """Reserve on a lot the CALLER has already row-locked. Raises InventoryError (no commit)."""
        self._resync(lot)
        rows = self._repo.reservations(lot.id)
        active, fulfilled = self._repo.totals(rows)
        cycle = self._session.get(CropCycle, lot.crop_cycle_id)
        assert cycle is not None
        view = derive_lot(cycle.status, lot.p10_kg, lot.actual_kg, active, fulfilled)
        check_reservation(view, quantity_kg, booking_key, {r.booking_key for r in rows})
        row = self._repo.add_reservation(
            InventoryReservation(
                lot_id=lot.id,
                quantity_kg=quantity_kg,
                booking_key=booking_key,
                note=note,
                status=ReservationStatus.ACTIVE,
            )
        )
        self._resync(lot)
        return row

    def shrink_locked(
        self, row: InventoryReservation, lot: InventoryLot, new_kg: Decimal, booking_key: str, note: str
    ) -> InventoryReservation:
        """Replace an active reservation by a smaller one (caller holds the lot lock)."""
        check_release(row.status)
        check_shrink(row.quantity_kg, new_kg)
        row.status = ReservationStatus.RELEASED
        self._session.flush()
        new = self._repo.add_reservation(
            InventoryReservation(
                lot_id=lot.id, quantity_kg=new_kg, booking_key=booking_key, note=note, status=ReservationStatus.ACTIVE
            )
        )
        self._resync(lot)
        return new

    def fulfil_locked(self, row: InventoryReservation, lot: InventoryLot) -> None:
        """Mark an active reservation fulfilled (caller holds the lot lock). Same rule as `fulfil`: only after the
        harvest has been MEASURED. Raises InventoryError."""
        cycle = self._session.get(CropCycle, lot.crop_cycle_id)
        assert cycle is not None
        active, fulfilled = self._repo.totals(self._repo.reservations(lot.id))
        check_fulfil(derive_lot(cycle.status, lot.p10_kg, lot.actual_kg, active, fulfilled), row.status)
        row.status = ReservationStatus.FULFILLED
        self._session.flush()
        self._resync(lot)

    def release_locked(self, row: InventoryReservation, lot: InventoryLot) -> None:
        check_release(row.status)
        row.status = ReservationStatus.RELEASED
        self._session.flush()
        self._resync(lot)

    def resync(self, lot: InventoryLot) -> None:
        self._resync(lot)

    # --------------------------------------------------------------- helpers

    def _resync(self, lot: InventoryLot) -> None:
        cycle = self._session.get(CropCycle, lot.crop_cycle_id)
        assert cycle is not None
        self.sync_lot(cycle, lot.owner_id)
        self._session.flush()

    def _require(self, owner_id: uuid.UUID, lot_id: uuid.UUID, *, for_update: bool = False) -> InventoryLot:
        lot = self._repo.get_owned_lot(lot_id, owner_id, for_update=for_update)
        if lot is None:
            raise NotFoundError("Inventory lot not found")
        return lot

    def _locked_reservation(
        self, owner_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> tuple[InventoryReservation, InventoryLot]:
        row = self._repo.get_owned_reservation(reservation_id, owner_id)
        if row is None:
            raise NotFoundError("Reservation not found")
        lot = self._require(owner_id, row.lot_id, for_update=True)
        self._session.refresh(row)
        return row, lot

    def _out(self, lot: InventoryLot) -> LotOut:
        """The lot with the crop, plot and farm it belongs to, so the farmer can tell lots apart."""
        cycle = self._session.get(CropCycle, lot.crop_cycle_id)
        plot = self._session.get(FarmPlot, cycle.plot_id) if cycle else None
        farm = self._session.get(Farm, plot.farm_id) if plot else None
        return LotOut.model_validate(lot).model_copy(
            update={
                "crop_name": cycle.crop.name if cycle else None,
                "plot_name": plot.name if plot else None,
                "farm_name": farm.name if farm else None,
                "sowing_date": cycle.sowing_date if cycle else None,
                **self._order_split(lot.id),
            }
        )

    def lot_out(self, lot: InventoryLot) -> LotOut:
        return self._out(lot)

    def _order_split(self, lot_id: uuid.UUID) -> dict[str, Decimal]:
        """Buyer orders on the lot by the farmer's answer: awaiting an answer, accepted and not yet delivered,
        delivered (measured, quality accepted). Released, declined and cancelled items count nowhere."""
        awaiting = confirmed = fulfilled = Decimal(0)
        for status, ordered, delivered in self._repo.order_quantities(lot_id):
            fulfilled += delivered or 0
            if status is OrderItemStatus.AWAITING_FARMER:
                awaiting += ordered or 0
            elif status is OrderItemStatus.ACCEPTED:
                confirmed += (ordered or 0) - (delivered or 0)
        return {"awaiting_confirmation_kg": awaiting, "confirmed_kg": confirmed, "fulfilled_kg": fulfilled}

    def _detail(self, lot: InventoryLot) -> LotDetail:
        base = self._out(lot).model_dump()
        return LotDetail(
            **base, reservations=[ReservationOut.model_validate(r) for r in self._repo.reservations(lot.id)]
        )
