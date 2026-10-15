"""Stateless planning tools (nothing is saved): the income calculator and the land allocator."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import FarmerDep, PlanningServiceDep
from app.api.responses import WRITE_ERR
from app.schemas.planning import AllocationRequestIn, CalcRequest
from app.schemas.planning_results import AllocationResponse, PlanResultOut

router = APIRouter()


@router.post(
    "/calculate",
    response_model=PlanResultOut,
    summary="Farm cost & income calculator",
    description=(
        "Evaluate a crop plan from the inputs alone. Returns estimated cost, yield and revenue ranges, "
        "margin, break-even, land utilization, income continuity, risk and confidence, with explanations. "
        "All figures are estimates over the ranges supplied, never guarantees."
    ),
    responses=WRITE_ERR,
)
def calculate(payload: CalcRequest, _farmer: FarmerDep, planning: PlanningServiceDep) -> PlanResultOut:
    return planning.calculate(payload)


@router.post(
    "/suggest-allocation",
    response_model=AllocationResponse,
    summary="Land utilization planner: suggest how to split land between crops",
    description=(
        "Deterministic greedy allocation that respects land (including crops that do not overlap in time), "
        "budget, water, labour, demand and a per-crop share cap. Every decision names the limit that bound it."
    ),
    responses=WRITE_ERR,
)
def suggest_allocation(
    payload: AllocationRequestIn, _farmer: FarmerDep, planning: PlanningServiceDep
) -> AllocationResponse:
    return planning.suggest_allocation(payload)
