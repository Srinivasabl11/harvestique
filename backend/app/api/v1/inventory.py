"""Virtual harvest inventory (farmer-only; owners manage commitments against their own predicted crops)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import FarmerDep, InventoryServiceDep, PageDep
from app.api.responses import ERR, WRITE_ERR
from app.schemas.common import Page
from app.schemas.intelligence import LotDetail, LotOut, ReservationIn, ReservationOut

router = APIRouter()


@router.get("/inventory/lots", response_model=Page[LotOut], responses=ERR)
def list_lots(farmer: FarmerDep, inventory: InventoryServiceDep, page: PageDep) -> Page[LotOut]:
    return inventory.list_lots(farmer.user_id, limit=page.limit, offset=page.offset)


@router.get("/inventory/lots/{lot_id}", response_model=LotDetail, responses=ERR)
def get_lot(lot_id: uuid.UUID, farmer: FarmerDep, inventory: InventoryServiceDep) -> LotDetail:
    return inventory.get_lot(farmer.user_id, lot_id)


@router.post(
    "/inventory/lots/{lot_id}/reservations",
    response_model=ReservationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Commit part of a lot (never more than can be safely promised)",
    responses=WRITE_ERR,
)
def reserve(
    lot_id: uuid.UUID, payload: ReservationIn, farmer: FarmerDep, inventory: InventoryServiceDep
) -> ReservationOut:
    return inventory.reserve(farmer.user_id, lot_id, payload)


@router.post("/inventory/reservations/{reservation_id}/release", response_model=ReservationOut, responses=WRITE_ERR)
def release(reservation_id: uuid.UUID, farmer: FarmerDep, inventory: InventoryServiceDep) -> ReservationOut:
    return inventory.release(farmer.user_id, reservation_id)


@router.post("/inventory/reservations/{reservation_id}/fulfil", response_model=ReservationOut, responses=WRITE_ERR)
def fulfil(reservation_id: uuid.UUID, farmer: FarmerDep, inventory: InventoryServiceDep) -> ReservationOut:
    return inventory.fulfil(farmer.user_id, reservation_id)
