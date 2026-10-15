"""Crop-cycle endpoints (farmer-only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import CropCycleServiceDep, FarmerDep, PageDep
from app.api.responses import ERR, WRITE_ERR
from app.core.enums import CycleStatus
from app.schemas.common import Page
from app.schemas.crop_cycles import CropCycleCreate, CropCycleRead, CropCycleUpdate

router = APIRouter()


@router.post(
    "/plots/{plot_id}/crop-cycles",
    response_model=CropCycleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Start a crop cycle on a plot",
    responses=WRITE_ERR,
)
def create_cycle(
    plot_id: uuid.UUID, payload: CropCycleCreate, farmer: FarmerDep, cycles: CropCycleServiceDep
) -> CropCycleRead:
    return cycles.create(farmer.user_id, plot_id, payload)


@router.get("/plots/{plot_id}/crop-cycles", response_model=Page[CropCycleRead], responses=ERR)
def list_plot_cycles(
    plot_id: uuid.UUID,
    farmer: FarmerDep,
    cycles: CropCycleServiceDep,
    page: PageDep,
    status: CycleStatus | None = None,
) -> Page[CropCycleRead]:
    return cycles.list_for_plot(farmer.user_id, plot_id, status=status, limit=page.limit, offset=page.offset)


@router.get("/farms/{farm_id}/crop-cycles", response_model=Page[CropCycleRead], responses=ERR)
def list_farm_cycles(
    farm_id: uuid.UUID,
    farmer: FarmerDep,
    cycles: CropCycleServiceDep,
    page: PageDep,
    status: CycleStatus | None = None,
) -> Page[CropCycleRead]:
    return cycles.list_for_farm(farmer.user_id, farm_id, status=status, limit=page.limit, offset=page.offset)


@router.get("/crop-cycles/{cycle_id}", response_model=CropCycleRead, responses=ERR)
def get_cycle(cycle_id: uuid.UUID, farmer: FarmerDep, cycles: CropCycleServiceDep) -> CropCycleRead:
    return cycles.get(farmer.user_id, cycle_id)


@router.patch("/crop-cycles/{cycle_id}", response_model=CropCycleRead, responses=WRITE_ERR)
def update_cycle(
    cycle_id: uuid.UUID, payload: CropCycleUpdate, farmer: FarmerDep, cycles: CropCycleServiceDep
) -> CropCycleRead:
    return cycles.update(farmer.user_id, cycle_id, payload)


@router.delete(
    "/crop-cycles/{cycle_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=WRITE_ERR,
)
def delete_cycle(cycle_id: uuid.UUID, farmer: FarmerDep, cycles: CropCycleServiceDep) -> Response:
    cycles.delete(farmer.user_id, cycle_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
