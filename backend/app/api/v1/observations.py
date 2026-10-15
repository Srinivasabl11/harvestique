"""Crop observation endpoints (farmer-only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import FarmerDep, ObservationServiceDep, PageDep
from app.api.responses import ERR, WRITE_ERR
from app.schemas.common import Page
from app.schemas.farm_records import ObservationCreate, ObservationRead, ObservationUpdate

router = APIRouter()


@router.post(
    "/crop-cycles/{cycle_id}/observations",
    response_model=ObservationRead,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERR,
)
def create_observation(
    cycle_id: uuid.UUID, payload: ObservationCreate, farmer: FarmerDep, observations: ObservationServiceDep
) -> ObservationRead:
    return observations.create(farmer.user_id, cycle_id, payload)


@router.get("/crop-cycles/{cycle_id}/observations", response_model=Page[ObservationRead], responses=ERR)
def list_observations(
    cycle_id: uuid.UUID, farmer: FarmerDep, observations: ObservationServiceDep, page: PageDep
) -> Page[ObservationRead]:
    return observations.list_for_cycle(farmer.user_id, cycle_id, limit=page.limit, offset=page.offset)


@router.get("/observations/{observation_id}", response_model=ObservationRead, responses=ERR)
def get_observation(
    observation_id: uuid.UUID, farmer: FarmerDep, observations: ObservationServiceDep
) -> ObservationRead:
    return observations.get(farmer.user_id, observation_id)


@router.patch("/observations/{observation_id}", response_model=ObservationRead, responses=WRITE_ERR)
def update_observation(
    observation_id: uuid.UUID, payload: ObservationUpdate, farmer: FarmerDep, observations: ObservationServiceDep
) -> ObservationRead:
    return observations.update(farmer.user_id, observation_id, payload)


@router.delete(
    "/observations/{observation_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, responses=ERR
)
def delete_observation(observation_id: uuid.UUID, farmer: FarmerDep, observations: ObservationServiceDep) -> Response:
    observations.delete(farmer.user_id, observation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
