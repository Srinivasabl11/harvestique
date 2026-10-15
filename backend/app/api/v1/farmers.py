"""Farmer-only endpoints (Phase 1: own profile; farms/plots arrive in Phase 2)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import FarmerDep, UserServiceDep
from app.schemas.auth import FarmerProfileRead
from app.schemas.common import ErrorResponse

router = APIRouter()


@router.get(
    "/me",
    response_model=FarmerProfileRead,
    summary="The authenticated farmer's profile",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def my_farmer_profile(current: FarmerDep, users: UserServiceDep) -> FarmerProfileRead:
    return users.get_farmer_profile(current.user_id)
