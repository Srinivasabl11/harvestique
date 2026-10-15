"""Admin-only endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.deps import AdminDep, AuthServiceDep, UserServiceDep
from app.core.enums import AccessStatus, UserRole
from app.schemas.auth import AccessUpdate, TemporaryPasswordOut, UserRead
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
    access: Annotated[AccessStatus | None, Query(description="Only accounts with this tester access")] = None,
) -> Page[UserRead]:
    return users.list_users(limit=limit, offset=offset, role=role, access=access)


@router.post(
    "/users/{user_id}/access",
    response_model=UserRead,
    summary="Approve, suspend or revoke a tester's access (admin only)",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def set_user_access(admin: AdminDep, auth: AuthServiceDep, user_id: uuid.UUID, payload: AccessUpdate) -> UserRead:
    return auth.set_access(admin, user_id, payload)


@router.post(
    "/users/{user_id}/password-reset",
    response_model=TemporaryPasswordOut,
    summary="Give a farmer or buyer a one-time temporary password; they must change it at sign-in (admin only)",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def reset_user_password(
    admin: AdminDep, auth: AuthServiceDep, user_id: uuid.UUID, response: Response
) -> TemporaryPasswordOut:
    response.headers["Cache-Control"] = "no-store"  # carries a password
    return auth.admin_reset_password(admin, user_id)
