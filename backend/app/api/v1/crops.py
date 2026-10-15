"""Crop catalog: readable by any authenticated user, managed by admins."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import AdminDep, CropServiceDep, CurrentUserDep, PageDep
from app.api.responses import AUTH_NOT_FOUND, AUTH_ONLY, WRITE_ERR
from app.core.enums import CropCategory
from app.schemas.common import Page
from app.schemas.crops import CropCreate, CropRead, CropUpdate

router = APIRouter()


@router.get("", response_model=Page[CropRead], summary="Search the crop catalog", responses=AUTH_ONLY)
def list_crops(
    current: CurrentUserDep,
    crops: CropServiceDep,
    page: PageDep,
    search: Annotated[str | None, Query(max_length=80, description="Matches name or local name")] = None,
    category: CropCategory | None = None,
    include_inactive: Annotated[bool, Query(description="Admins only; ignored for other roles")] = False,
) -> Page[CropRead]:
    return crops.list_crops(
        role=current.role,
        search=search,
        category=category,
        include_inactive=include_inactive,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{crop_id}", response_model=CropRead, responses=AUTH_NOT_FOUND)
def get_crop(crop_id: uuid.UUID, current: CurrentUserDep, crops: CropServiceDep) -> CropRead:
    return crops.get_crop(crop_id, role=current.role)


@router.post(
    "",
    response_model=CropRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a crop to the catalog (admin)",
    responses=WRITE_ERR,
)
def create_crop(payload: CropCreate, _admin: AdminDep, crops: CropServiceDep) -> CropRead:
    return crops.create_crop(payload)


@router.patch("/{crop_id}", response_model=CropRead, summary="Edit or deactivate a crop (admin)", responses=WRITE_ERR)
def update_crop(crop_id: uuid.UUID, payload: CropUpdate, _admin: AdminDep, crops: CropServiceDep) -> CropRead:
    return crops.update_crop(crop_id, payload)


@router.delete(
    "/{crop_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an unused crop (admin)",
    responses=WRITE_ERR,
)
def delete_crop(crop_id: uuid.UUID, _admin: AdminDep, crops: CropServiceDep) -> Response:
    crops.delete_crop(crop_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
