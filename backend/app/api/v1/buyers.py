"""Buyer-only endpoints (Phase 1: own profile; demands arrive in a later phase)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import BuyerDep, UserServiceDep
from app.schemas.auth import BuyerProfileRead
from app.schemas.common import ErrorResponse

router = APIRouter()


@router.get(
    "/me",
    response_model=BuyerProfileRead,
    summary="The authenticated buyer's profile",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def my_buyer_profile(current: BuyerDep, users: UserServiceDep) -> BuyerProfileRead:
    return users.get_buyer_profile(current.user_id)
