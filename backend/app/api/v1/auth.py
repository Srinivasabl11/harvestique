"""Authentication endpoints.

Registration and login are two steps. Step 1 (`/register`, `/login`) checks the details and sends a one-time code by
SMS; it never returns tokens. Step 2 (`/register/verify`, `/login/verify`) checks the code and only then issues the
session tokens.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status

from app.api.deps import AuthServiceDep, CurrentUserDep, UserServiceDep
from app.core.enums import OtpPurpose
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    OtpChallengeOut,
    OtpResendRequest,
    OtpVerifyRequest,
    PasswordForgotRequest,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    TourUpdate,
    UserRead,
)
from app.schemas.common import ErrorResponse

router = APIRouter()
STEP1: dict[int | str, dict[str, Any]] = {
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}
STEP2: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def _client(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post(
    "/register",
    response_model=OtpChallengeOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Register a farmer or buyer: step 1 of 2 (sends a verification code by SMS)",
    responses=STEP1,
)
def register(payload: RegisterRequest, request: Request, auth: AuthServiceDep) -> OtpChallengeOut:
    return auth.register(payload, client=_client(request))


@router.post(
    "/register/verify",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register: step 2 of 2 (verify the SMS code, activate the account and sign in)",
    responses=STEP2,
)
def register_verify(payload: OtpVerifyRequest, auth: AuthServiceDep) -> AuthResponse:
    return auth.verify(OtpPurpose.REGISTER, payload)


@router.post(
    "/login",
    response_model=OtpChallengeOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sign in: step 1 of 2 (phone and password; sends a one-time code by SMS)",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, **STEP1},
)
def login(payload: LoginRequest, request: Request, auth: AuthServiceDep) -> OtpChallengeOut:
    return auth.login(payload, client=_client(request))


@router.post(
    "/login/verify",
    response_model=AuthResponse,
    summary="Sign in: step 2 of 2 (verify the SMS code; issues the session tokens)",
    responses=STEP2,
)
def login_verify(payload: OtpVerifyRequest, auth: AuthServiceDep) -> AuthResponse:
    return auth.verify(OtpPurpose.LOGIN, payload)


@router.post(
    "/otp/resend",
    response_model=OtpChallengeOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a new code for a registration or sign-in in progress (cooldown and limits apply)",
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def resend(payload: OtpResendRequest, request: Request, auth: AuthServiceDep) -> OtpChallengeOut:
    return auth.resend(payload, client=_client(request))


@router.post(
    "/password/forgot",
    response_model=OtpChallengeOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Forgot password: step 1 of 2 (a code is sent if the number has an account; same answer otherwise)",
    responses=STEP1,
)
def forgot_password(payload: PasswordForgotRequest, request: Request, auth: AuthServiceDep) -> OtpChallengeOut:
    return auth.forgot_password(payload, client=_client(request))


@router.post(
    "/password/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Forgot password: step 2 of 2 (code + new password; signs out every session)",
    responses=STEP2,
)
def reset_password(payload: PasswordResetRequest, auth: AuthServiceDep) -> Response:
    auth.reset_password(payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
def refresh(payload: RefreshRequest, auth: AuthServiceDep) -> TokenPair:
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
