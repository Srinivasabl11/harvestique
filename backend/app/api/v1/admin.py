"""Admin-only endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminDep, UserServiceDep
from app.core.enums import UserRole
from app.schemas.auth import UserRead
from app.schemas.common import ErrorResponse, Page

router = APIRouter()


@router.get(
    "/users",
    response_model=Page[UserRead],
    summary="List users (admin only)",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def list_users(
    _admin: AdminDep,
    users: UserServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    role: UserRole | None = None,
) -> Page[UserRead]:
    return users.list_users(limit=limit, offset=offset, role=role)
