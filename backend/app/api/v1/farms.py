"""Farm endpoints (farmer-only; each farmer sees only their own farms)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import FarmerDep, FarmServiceDep, PageDep
from app.api.responses import ERR, WRITE_ERR
from app.schemas.common import Page
from app.schemas.farms import FarmCreate, FarmRead, FarmUpdate

router = APIRouter()


@router.post(
    "",
    response_model=FarmRead,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERR,
)
def create_farm(payload: FarmCreate, farmer: FarmerDep, farms: FarmServiceDep) -> FarmRead:
    return farms.create(farmer.user_id, payload)


@router.get("", response_model=Page[FarmRead], summary="List my farms", responses=ERR)
def list_farms(
    farmer: FarmerDep, farms: FarmServiceDep, page: PageDep, include_archived: bool = False
) -> Page[FarmRead]:
    return farms.list_owned(farmer.user_id, include_archived=include_archived, limit=page.limit, offset=page.offset)


@router.get("/{farm_id}", response_model=FarmRead, responses=ERR)
def get_farm(farm_id: uuid.UUID, farmer: FarmerDep, farms: FarmServiceDep) -> FarmRead:
    return farms.get(farmer.user_id, farm_id)


@router.patch("/{farm_id}", response_model=FarmRead, responses=WRITE_ERR)
def update_farm(farm_id: uuid.UUID, payload: FarmUpdate, farmer: FarmerDep, farms: FarmServiceDep) -> FarmRead:
    return farms.update(farmer.user_id, farm_id, payload)


@router.delete(
    "/{farm_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an empty farm (otherwise archive it)",
    responses=WRITE_ERR,
)
def delete_farm(farm_id: uuid.UUID, farmer: FarmerDep, farms: FarmServiceDep) -> Response:
    farms.delete(farmer.user_id, farm_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
