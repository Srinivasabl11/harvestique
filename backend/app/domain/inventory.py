"""Uncertainty-aware virtual harvest inventory (pure rules).

Before harvest a lot may only promise its pessimistic quantity (p10): what remains available is
committable - (active + fulfilled reservations), never negative. After harvest the measured quantity
replaces the forecast. If a new prediction drops below what is already committed, the lot becomes
AT_RISK with an explicit shortfall (nothing is silently re-allocated).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal

from app.core.enums import CycleStatus, LotStatus, ReservationStatus

D = Decimal
ZERO = D(0)


class InventoryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class LotView:
    status: LotStatus
    committable_kg: Decimal
    committed_kg: Decimal  # active + fulfilled
    available_kg: Decimal  # >= 0 always
    shortfall_kg: Decimal  # >= 0; > 0 means AT_RISK
    basis: str


def derive_lot(
    cycle_status: CycleStatus,
    p10: Decimal | None,
    actual_kg: Decimal | None,
    active_kg: Decimal,
    fulfilled_kg: Decimal,
) -> LotView:
    committed = active_kg + fulfilled_kg
    if cycle_status is CycleStatus.ABANDONED:
        committable, base_status, basis = ZERO, LotStatus.CANCELLED, "crop cycle abandoned"
    elif actual_kg is not None:
        committable, base_status, basis = actual_kg, LotStatus.HARVESTED, "measured harvest"
    elif p10 is not None:
        committable, base_status, basis = p10, LotStatus.OPEN, "predicted p10 (pessimistic) quantity"
    else:
        committable, base_status, basis = ZERO, LotStatus.OPEN, "no usable prediction yet"
    shortfall = max(ZERO, committed - committable)
    status = base_status
    if shortfall > 0 and base_status is not LotStatus.CANCELLED:
        status = LotStatus.AT_RISK
    return LotView(status, committable, committed, max(ZERO, committable - committed), shortfall, basis)


def check_reservation(view: LotView, quantity_kg: Decimal, booking_key: str, existing_keys: Collection[str]) -> None:
    if quantity_kg <= 0:
        raise InventoryError("quantity_not_positive", "Reserved quantity must be greater than zero")
    if view.status is LotStatus.CANCELLED:
        raise InventoryError("lot_closed", "This lot is cancelled (crop cycle abandoned)")
    if booking_key in existing_keys:
        raise InventoryError("duplicate_booking", "This booking key has already been used for this lot")
    if quantity_kg > view.available_kg:
        raise InventoryError(
            "over_allocation",
            f"Only {view.available_kg} kg can be safely committed ({view.basis}); requested {quantity_kg} kg",
        )


def check_shrink(old_kg: Decimal, new_kg: Decimal) -> None:
    """Replacing a commitment by a SMALLER one can never over-allocate, so it needs no availability check
    (the lot may still be over-committed by others until they are cut too)."""
    if not ZERO < new_kg < old_kg:
        raise InventoryError("not_a_reduction", "A shrink must keep a positive quantity below the current one")


def check_fulfil(view: LotView, reservation_status: ReservationStatus) -> None:
    if reservation_status is not ReservationStatus.ACTIVE:
        raise InventoryError("reservation_not_active", "Only an active reservation can be fulfilled")
    if view.status not in (LotStatus.HARVESTED, LotStatus.AT_RISK) or view.basis != "measured harvest":
        raise InventoryError("not_harvested", "A reservation can be fulfilled only after the harvest is recorded")


def check_release(reservation_status: ReservationStatus) -> None:
    if reservation_status is not ReservationStatus.ACTIVE:
        raise InventoryError("reservation_not_active", "Only an active reservation can be released")
