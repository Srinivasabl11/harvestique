"""Saved planning scenarios (farmer-only; each farmer sees only their own plans)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CropPlanServiceDep, FarmerDep, PageDep
from app.api.responses import ERR, WRITE_ERR
from app.schemas.common import Page
from app.schemas.intelligence import PlanItemFromPrediction
from app.schemas.planning import (
    CropPlanCreate,
    CropPlanDuplicate,
    CropPlanRead,
    CropPlanSummary,
    CropPlanUpdate,
    PlanItemCreate,
    PlanItemRead,
    PlanItemUpdate,
)
from app.schemas.planning_results import CompareResponse, PlanResultOut

router = APIRouter()


@router.post("/crop-plans", response_model=CropPlanRead, status_code=status.HTTP_201_CREATED, responses=WRITE_ERR)
def create_plan(payload: CropPlanCreate, farmer: FarmerDep, plans: CropPlanServiceDep) -> CropPlanRead:
    return plans.create(farmer.user_id, payload)


@router.get("/crop-plans", response_model=Page[CropPlanSummary], summary="List my plans", responses=ERR)
def list_plans(
    farmer: FarmerDep, plans: CropPlanServiceDep, page: PageDep, farm_id: uuid.UUID | None = None
) -> Page[CropPlanSummary]:
    return plans.list_owned(farmer.user_id, farm_id=farm_id, limit=page.limit, offset=page.offset)


# Declared before /{plan_id} so "compare" is not parsed as a plan id.
@router.get(
    "/crop-plans/compare",
    response_model=CompareResponse,
    summary="Compare 2-5 of my plans side by side",
    responses=WRITE_ERR,
)
def compare_plans(
    farmer: FarmerDep,
    plans: CropPlanServiceDep,
    plan_id: Annotated[list[uuid.UUID], Query(min_length=2, max_length=5)],
) -> CompareResponse:
    return plans.compare(farmer.user_id, plan_id)


@router.get("/crop-plans/{plan_id}", response_model=CropPlanRead, responses=ERR)
def get_plan(plan_id: uuid.UUID, farmer: FarmerDep, plans: CropPlanServiceDep) -> CropPlanRead:
    return plans.get(farmer.user_id, plan_id)


@router.patch("/crop-plans/{plan_id}", response_model=CropPlanRead, responses=WRITE_ERR)
def update_plan(
    plan_id: uuid.UUID, payload: CropPlanUpdate, farmer: FarmerDep, plans: CropPlanServiceDep
) -> CropPlanRead:
    return plans.update(farmer.user_id, plan_id, payload)


@router.delete("/crop-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, responses=ERR)
def delete_plan(plan_id: uuid.UUID, farmer: FarmerDep, plans: CropPlanServiceDep) -> Response:
    plans.delete(farmer.user_id, plan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/crop-plans/{plan_id}/duplicate",
    response_model=CropPlanRead,
    status_code=status.HTTP_201_CREATED,
    summary="Copy a plan (with its crops) to try a variation",
    responses=WRITE_ERR,
)
def duplicate_plan(
    plan_id: uuid.UUID, payload: CropPlanDuplicate, farmer: FarmerDep, plans: CropPlanServiceDep
) -> CropPlanRead:
    return plans.duplicate(farmer.user_id, plan_id, payload)


@router.get(
    "/crop-plans/{plan_id}/evaluation",
    response_model=PlanResultOut,
    summary="Evaluate a saved plan (computed fresh from its inputs)",
    responses=WRITE_ERR,
)
def evaluate_plan(plan_id: uuid.UUID, farmer: FarmerDep, plans: CropPlanServiceDep) -> PlanResultOut:
    return plans.evaluate(farmer.user_id, plan_id)


# ----------------------------------------------------------------- plan items


@router.post(
    "/crop-plans/{plan_id}/items/from-prediction",
    response_model=PlanItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a crop to a plan using a saved prediction's p10/p50/p90 as its yield range",
    responses=WRITE_ERR,
)
def add_item_from_prediction(
    plan_id: uuid.UUID, payload: PlanItemFromPrediction, farmer: FarmerDep, plans: CropPlanServiceDep
) -> PlanItemRead:
    return plans.add_item_from_prediction(farmer.user_id, plan_id, payload)


@router.post(
    "/crop-plans/{plan_id}/items",
    response_model=PlanItemRead,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERR,
)
def add_item(plan_id: uuid.UUID, payload: PlanItemCreate, farmer: FarmerDep, plans: CropPlanServiceDep) -> PlanItemRead:
    return plans.add_item(farmer.user_id, plan_id, payload)


@router.get("/crop-plan-items/{item_id}", response_model=PlanItemRead, responses=ERR)
def get_item(item_id: uuid.UUID, farmer: FarmerDep, plans: CropPlanServiceDep) -> PlanItemRead:
    return plans.get_item(farmer.user_id, item_id)


@router.patch("/crop-plan-items/{item_id}", response_model=PlanItemRead, responses=WRITE_ERR)
def update_item(
    item_id: uuid.UUID, payload: PlanItemUpdate, farmer: FarmerDep, plans: CropPlanServiceDep
) -> PlanItemRead:
    return plans.update_item(farmer.user_id, item_id, payload)


@router.delete(
    "/crop-plan-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, responses=ERR
)
def delete_item(item_id: uuid.UUID, farmer: FarmerDep, plans: CropPlanServiceDep) -> Response:
    plans.delete_item(farmer.user_id, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
