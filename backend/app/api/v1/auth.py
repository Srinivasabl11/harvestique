"""Authentication endpoints.

Sign-in is phone + password. Sign-up creates the account; on a server with NEW_ACCOUNT_ACCESS=pending (production) it
then waits for an admin's approval and no tokens are issued until then. A forgotten password is reset by an admin
(temporary password); `/password/change` sets a new one and signs in.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from app.api.deps import AuthServiceDep, CurrentUserDep, UserServiceDep
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    PasswordChangeRequest,
    RefreshRequest,
    RegisterRequest,
    RegistrationOut,
    TokenPair,
    TourUpdate,
    UserRead,
)
from app.schemas.common import ErrorResponse

router = APIRouter()
NO_STORE = "no-store"  # responses carrying tokens must not be cached by any proxy or client (RFC 6749 section 5.1)
CREDENTIALS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
}


@router.post(
    "/register",
    response_model=RegistrationOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Register a farmer or buyer (201 + tokens when usable at once; 202 when it waits for admin approval)",
    responses={
        201: {"model": RegistrationOut, "description": "Account created and signed in"},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
)
def register(payload: RegisterRequest, response: Response, auth: AuthServiceDep) -> RegistrationOut:
    out = auth.register(payload)
    response.headers["Cache-Control"] = NO_STORE
    if out.tokens is not None:
        response.status_code = status.HTTP_201_CREATED
    return out


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Sign in with phone and password (403 password_change_required after an admin password reset)",
    responses=CREDENTIALS,
)
def login(payload: LoginRequest, response: Response, auth: AuthServiceDep) -> AuthResponse:
    response.headers["Cache-Control"] = NO_STORE
    return auth.login(payload)


@router.post(
    "/password/change",
    response_model=AuthResponse,
    summary="Set a new password using the current or temporary one; signs out other devices and signs in",
    responses=CREDENTIALS,
)
def change_password(payload: PasswordChangeRequest, response: Response, auth: AuthServiceDep) -> AuthResponse:
    response.headers["Cache-Control"] = NO_STORE
    return auth.change_password(payload)


@router.post(
    "/me/tour",
    response_model=UserRead,
    summary="Record that the first-login tour (this version) was finished or skipped",
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def tour_seen(payload: TourUpdate, current: CurrentUserDep, auth: AuthServiceDep) -> UserRead:
    return auth.mark_tour_seen(current, payload.version)


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Exchange a refresh token for a new token pair (rotation)",
    responses={401: {"model": ErrorResponse}},
)
def refresh(payload: RefreshRequest, response: Response, auth: AuthServiceDep) -> TokenPair:
    response.headers["Cache-Control"] = NO_STORE
    return auth.refresh(payload.refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="End the current session",
    responses={401: {"model": ErrorResponse}},
)
def logout(current: CurrentUserDep, auth: AuthServiceDep) -> Response:
    auth.logout(current)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=UserRead,
    summary="The authenticated user (with role profile)",
    responses={401: {"model": ErrorResponse}},
)
def me(current: CurrentUserDep, users: UserServiceDep) -> UserRead:
    return users.get_user(current.user_id)
