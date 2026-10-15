"""Farm activity endpoints (farmer-only)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Response, status

from app.api.deps import ActivityServiceDep, FarmerDep, PageDep
from app.api.responses import ERR, WRITE_ERR
from app.core.enums import ActivityType
from app.schemas.common import Page
from app.schemas.farm_records import ActivityCreate, ActivityRead, ActivityUpdate

router = APIRouter()


@router.post(
    "/farms/{farm_id}/activities", response_model=ActivityRead, status_code=status.HTTP_201_CREATED, responses=WRITE_ERR
)
def create_activity(
    farm_id: uuid.UUID, payload: ActivityCreate, farmer: FarmerDep, activities: ActivityServiceDep
) -> ActivityRead:
    return activities.create(farmer.user_id, farm_id, payload)


@router.get("/farms/{farm_id}/activities", response_model=Page[ActivityRead], responses=ERR)
def list_activities(
    farm_id: uuid.UUID,
    farmer: FarmerDep,
    activities: ActivityServiceDep,
    page: PageDep,
    plot_id: uuid.UUID | None = None,
    crop_cycle_id: uuid.UUID | None = None,
    activity_type: ActivityType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Page[ActivityRead]:
    return activities.list_for_farm(
        farmer.user_id,
        farm_id,
        plot_id=plot_id,
        crop_cycle_id=crop_cycle_id,
        activity_type=activity_type,
        date_from=date_from,
        date_to=date_to,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/activities/{activity_id}", response_model=ActivityRead, responses=ERR)
def get_activity(activity_id: uuid.UUID, farmer: FarmerDep, activities: ActivityServiceDep) -> ActivityRead:
    return activities.get(farmer.user_id, activity_id)


@router.patch("/activities/{activity_id}", response_model=ActivityRead, responses=WRITE_ERR)
def update_activity(
    activity_id: uuid.UUID, payload: ActivityUpdate, farmer: FarmerDep, activities: ActivityServiceDep
) -> ActivityRead:
    return activities.update(farmer.user_id, activity_id, payload)


@router.delete(
    "/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, responses=ERR
)
def delete_activity(activity_id: uuid.UUID, farmer: FarmerDep, activities: ActivityServiceDep) -> Response:
    activities.delete(farmer.user_id, activity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
