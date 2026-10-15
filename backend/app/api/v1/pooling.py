"""Buyer demand, future-harvest matching, harvest pools, dynamic reallocation, audit."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, status

from app.api.deps import BuyerDep, BuyerOrAdminDep, FarmerDep, PageDep, PoolServiceDep
from app.api.responses import ERR, WRITE_ERR
from app.schemas.common import Page
from app.schemas.intelligence import LotOut
from app.schemas.pooling import (
    DemandCreate,
    DemandOut,
    EventOut,
    LedgerOut,
    LotUpdate,
    MatchesOut,
    PoolCreate,
    PoolOut,
)

router = APIRouter()
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=80)]
RequiredKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=80)]


@router.post("/buyer-demands", response_model=DemandOut, status_code=status.HTTP_201_CREATED, responses=WRITE_ERR)
def create_demand(payload: DemandCreate, buyer: BuyerDep, pools: PoolServiceDep) -> DemandOut:
    return pools.create_demand(buyer.user_id, payload)


@router.get("/buyer-demands", response_model=Page[DemandOut], responses=ERR)
def list_demands(buyer: BuyerDep, pools: PoolServiceDep, page: PageDep) -> Page[DemandOut]:
    return pools.list_demands(buyer.user_id, limit=page.limit, offset=page.offset)


@router.get("/buyer-demands/{demand_id}", response_model=DemandOut, responses=ERR)
def get_demand(demand_id: uuid.UUID, buyer: BuyerDep, pools: PoolServiceDep) -> DemandOut:
    return pools.get_demand(buyer.user_id, demand_id)


@router.post(
    "/buyer-demands/{demand_id}/cancel",
    response_model=DemandOut,
    summary="Withdraw a demand that has no harvest pool yet",
    responses=WRITE_ERR,
)
def cancel_demand(demand_id: uuid.UUID, buyer: BuyerDep, pools: PoolServiceDep) -> DemandOut:
    return pools.cancel_demand(buyer.user_id, demand_id)


@router.get(
    "/buyer-demands/{demand_id}/matches",
    response_model=MatchesOut,
    summary="Ranked future-harvest supply for a demand",
    responses=ERR,
)
def matches(demand_id: uuid.UUID, buyer: BuyerDep, pools: PoolServiceDep) -> MatchesOut:
    return pools.matches(buyer.user_id, demand_id)


@router.post(
    "/buyer-demands/{demand_id}/pool",
    response_model=PoolOut,
    status_code=status.HTTP_201_CREATED,
    summary="Pool uncertain supply from several farms to meet the demand (repeat safely with Idempotency-Key)",
    responses=WRITE_ERR,
)
def create_pool(
    demand_id: uuid.UUID,
    buyer: BuyerDep,
    pools: PoolServiceDep,
    key: IdempotencyKey = None,
    payload: PoolCreate | None = None,
) -> PoolOut:
    return pools.create_pool(buyer.user_id, demand_id, payload or PoolCreate(), key)


@router.get("/pools", response_model=Page[PoolOut], summary="My pools (admins: all pools)", responses=ERR)
def list_pools(user: BuyerOrAdminDep, pools: PoolServiceDep, page: PageDep) -> Page[PoolOut]:
    return pools.list_pools(user, limit=page.limit, offset=page.offset)


@router.get("/pools/{pool_id}", response_model=PoolOut, responses=ERR)
def get_pool(pool_id: uuid.UUID, user: BuyerOrAdminDep, pools: PoolServiceDep) -> PoolOut:
    return pools.get_pool(user, pool_id)


@router.post(
    "/pools/{pool_id}/rebalance",
    response_model=EventOut,
    summary="Detect shortages and reallocate now (Idempotency-Key required)",
    responses=WRITE_ERR,
)
def rebalance(pool_id: uuid.UUID, user: BuyerOrAdminDep, pools: PoolServiceDep, key: RequiredKey) -> EventOut:
    return pools.rebalance(user, pool_id, key)


@router.get(
    "/pools/{pool_id}/events",
    response_model=list[EventOut],
    summary="Reallocation events (why and before/after)",
    responses=ERR,
)
def events(pool_id: uuid.UUID, user: BuyerOrAdminDep, pools: PoolServiceDep) -> list[EventOut]:
    return pools.events(user, pool_id)


@router.get(
    "/pools/{pool_id}/ledger",
    response_model=list[LedgerOut],
    summary="Append-only allocation audit ledger",
    responses=ERR,
)
def ledger(pool_id: uuid.UUID, user: BuyerOrAdminDep, pools: PoolServiceDep) -> list[LedgerOut]:
    return pools.ledger(user, pool_id)


@router.patch(
    "/inventory/lots/{lot_id}",
    response_model=LotOut,
    summary="Opt a lot into pooling / set its expected grade",
    responses=WRITE_ERR,
)
def update_lot(lot_id: uuid.UUID, payload: LotUpdate, farmer: FarmerDep, pools: PoolServiceDep) -> LotOut:
    return pools.update_lot(farmer.user_id, lot_id, payload)
