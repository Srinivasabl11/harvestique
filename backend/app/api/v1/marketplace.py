"""Marketplace: orders on harvest pools, farmer participation, collection hubs, batches, quality, fulfilment,
traceability, future-harvest search and buyer opportunities. Quantities only: no prices anywhere."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, Response, status

from app.api.deps import (
    AdminDep,
    BuyerDep,
    BuyerOrAdminDep,
    CurrentUserDep,
    FarmerDep,
    MarketplaceServiceDep,
    PageDep,
)
from app.api.responses import ERR, WRITE_ERR
from app.core.enums import OrderStatus, ParticipationStatus, QualityGrade
from app.schemas.common import Page
from app.schemas.marketplace import (
    BatchCreate,
    BatchOut,
    BatchTrace,
    FulfilmentOut,
    HubCreate,
    HubOut,
    HubUpdate,
    Opportunity,
    OrderCreate,
    OrderOut,
    OrderTrace,
    ParticipationDecline,
    ParticipationOut,
    ProgressUpdate,
    QualityIn,
    SupplySummary,
)
from app.schemas.pooling import MatchesOut

router = APIRouter()
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=80)]


# ---------------------------------------------------------------------- market
@router.get(
    "/market/supply",
    response_model=list[SupplySummary],
    summary="Future supply on offer per crop (p10 estimates)",
    responses=ERR,
)
def supply(_user: BuyerOrAdminDep, market: MarketplaceServiceDep) -> list[SupplySummary]:
    return market.supply_summary()


@router.get(
    "/market/harvests", response_model=MatchesOut, summary="Search eligible future harvests", responses=WRITE_ERR
)
def search(
    _buyer: BuyerDep,
    market: MarketplaceServiceDep,
    crop_id: uuid.UUID,
    quantity_kg: Annotated[Decimal, Query(gt=0, le=10_000_000)],
    window_start: date,
    window_end: date,
    min_grade: QualityGrade = QualityGrade.C,
    latitude: Annotated[Decimal | None, Query(ge=-90, le=90)] = None,
    longitude: Annotated[Decimal | None, Query(ge=-180, le=180)] = None,
    max_distance_km: Annotated[Decimal | None, Query(gt=0, le=5000)] = None,
) -> MatchesOut:
    return market.search(
        crop_id, quantity_kg, window_start, window_end, min_grade, latitude, longitude, max_distance_km
    )


@router.get(
    "/market/opportunities",
    response_model=list[Opportunity],
    summary="Open buyer demands for crops I grow",
    responses=ERR,
)
def opportunities(farmer: FarmerDep, market: MarketplaceServiceDep) -> list[Opportunity]:
    return market.opportunities(farmer.user_id)


# ---------------------------------------------------------------------- orders
@router.post(
    "/orders",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Order a harvest pool (farmers are asked to confirm)",
    responses=WRITE_ERR,
)
def place_order(
    payload: OrderCreate, buyer: BuyerDep, market: MarketplaceServiceDep, key: IdempotencyKey = None
) -> OrderOut:
    return market.place_order(buyer.user_id, payload, key)


@router.get("/orders", response_model=Page[OrderOut], summary="My orders (admins: all)", responses=ERR)
def list_orders(
    user: BuyerOrAdminDep,
    market: MarketplaceServiceDep,
    page: PageDep,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
) -> Page[OrderOut]:
    return market.list_orders(user, status_filter, limit=page.limit, offset=page.offset)


@router.get("/orders/{order_id}", response_model=OrderOut, responses=ERR)
def get_order(order_id: uuid.UUID, user: BuyerOrAdminDep, market: MarketplaceServiceDep) -> OrderOut:
    return market.get_order(user, order_id)


@router.post(
    "/orders/{order_id}/cancel",
    response_model=OrderOut,
    summary="Cancel before any produce is received",
    responses=WRITE_ERR,
)
def cancel_order(order_id: uuid.UUID, buyer: BuyerDep, market: MarketplaceServiceDep) -> OrderOut:
    return market.cancel_order(buyer.user_id, order_id)


@router.get(
    "/orders/{order_id}/trace",
    response_model=OrderTrace,
    summary="Order -> Pool -> Allocation -> Harvest -> Batch -> Quality -> Fulfilment",
    responses=ERR,
)
def order_trace(order_id: uuid.UUID, user: BuyerOrAdminDep, market: MarketplaceServiceDep) -> OrderTrace:
    return market.order_trace(user, order_id)


@router.get("/orders/{order_id}/batches", response_model=list[BatchOut], responses=ERR)
def order_batches(order_id: uuid.UUID, user: BuyerOrAdminDep, market: MarketplaceServiceDep) -> list[BatchOut]:
    return market.batches_for_order(user, order_id)


# --------------------------------------------------------------- participation
@router.get(
    "/participations", response_model=Page[ParticipationOut], summary="Supply requests sent to me", responses=ERR
)
def participations(
    farmer: FarmerDep,
    market: MarketplaceServiceDep,
    page: PageDep,
    status_filter: Annotated[ParticipationStatus | None, Query(alias="status")] = None,
) -> Page[ParticipationOut]:
    return market.participations(farmer.user_id, status_filter, limit=page.limit, offset=page.offset)


@router.post(
    "/participations/{participation_id}/progress",
    response_model=ParticipationOut,
    summary="Mark an accepted request as preparing, then ready (the buyer is notified)",
    responses=WRITE_ERR,
)
def participation_progress(
    participation_id: uuid.UUID, payload: ProgressUpdate, farmer: FarmerDep, market: MarketplaceServiceDep
) -> ParticipationOut:
    return market.progress(farmer.user_id, participation_id, payload.stage)


@router.post("/participations/{participation_id}/accept", response_model=ParticipationOut, responses=WRITE_ERR)
def accept(participation_id: uuid.UUID, farmer: FarmerDep, market: MarketplaceServiceDep) -> ParticipationOut:
    return market.accept(farmer.user_id, participation_id)


@router.post(
    "/participations/{participation_id}/decline",
    response_model=ParticipationOut,
    summary="Decline: supply released and replaced by dynamic reallocation",
    responses=WRITE_ERR,
)
def decline(
    participation_id: uuid.UUID, payload: ParticipationDecline, farmer: FarmerDep, market: MarketplaceServiceDep
) -> ParticipationOut:
    return market.decline(farmer.user_id, participation_id, payload.reason)


# ------------------------------------------------------------------------ hubs
@router.get("/hubs", response_model=list[HubOut], summary="Active collection hubs", responses=ERR)
def hubs(user: CurrentUserDep, market: MarketplaceServiceDep, include_inactive: bool = False) -> list[HubOut]:
    return market.list_hubs(include_inactive and user.role.value == "admin")


@router.post("/admin/hubs", response_model=HubOut, status_code=status.HTTP_201_CREATED, responses=WRITE_ERR)
def create_hub(payload: HubCreate, _admin: AdminDep, market: MarketplaceServiceDep) -> HubOut:
    return market.create_hub(payload)


@router.patch("/admin/hubs/{hub_id}", response_model=HubOut, responses=WRITE_ERR)
def update_hub(hub_id: uuid.UUID, payload: HubUpdate, _admin: AdminDep, market: MarketplaceServiceDep) -> HubOut:
    return market.update_hub(hub_id, payload)


# ------------------------------------------- collection, quality and fulfilment
@router.get("/admin/batches", response_model=Page[BatchOut], summary="Batches (hub operations)", responses=ERR)
def list_batches(
    _admin: AdminDep,
    market: MarketplaceServiceDep,
    page: PageDep,
    hub_id: uuid.UUID | None = None,
    awaiting_quality: bool = False,
) -> Page[BatchOut]:
    return market.list_batches(hub_id, awaiting_quality, limit=page.limit, offset=page.offset)


@router.post(
    "/admin/batches",
    response_model=BatchOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record produce received at a hub (measured)",
    responses=WRITE_ERR,
)
def receive_batch(payload: BatchCreate, admin: AdminDep, market: MarketplaceServiceDep) -> BatchOut:
    return market.receive_batch(admin.user_id, payload)


@router.delete(
    "/admin/batches/{batch_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Remove a batch entered by mistake (only before its quality check)",
    responses=WRITE_ERR,
)
def remove_batch(batch_id: uuid.UUID, _admin: AdminDep, market: MarketplaceServiceDep) -> Response:
    market.remove_batch(batch_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/admin/batches/{batch_id}/quality",
    response_model=BatchOut,
    summary="Record the quality check of a batch (measured, once)",
    responses=WRITE_ERR,
)
def record_quality(batch_id: uuid.UUID, payload: QualityIn, admin: AdminDep, market: MarketplaceServiceDep) -> BatchOut:
    return market.record_quality(admin.user_id, batch_id, payload)


@router.post(
    "/admin/order-items/{item_id}/fulfil",
    response_model=FulfilmentOut,
    summary="Count quality-accepted produce towards the order",
    responses=WRITE_ERR,
)
def fulfil(item_id: uuid.UUID, admin: AdminDep, market: MarketplaceServiceDep) -> FulfilmentOut:
    return market.fulfil_item(admin.user_id, item_id)


@router.get(
    "/trace/batches/{code}",
    response_model=BatchTrace,
    summary="Trace a batch code back to its farm, harvest and prediction",
    responses=ERR,
)
def batch_trace(
    code: Annotated[str, Path(min_length=6, max_length=24, pattern=r"^[A-Za-z0-9-]+$")],
    user: CurrentUserDep,
    market: MarketplaceServiceDep,
) -> BatchTrace:
    return market.batch_trace(user, code)
