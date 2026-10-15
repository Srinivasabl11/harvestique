"""Application error hierarchy and the single JSON error envelope.

Services raise `AppError` subclasses; routes never build error responses by hand.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code: int = 400
    code: str = "app_error"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.headers = headers or {}
        if code is not None:
            self.code = code  # per-instance machine code, e.g. "token_expired"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            message,
            details=details,
            code=code,
            headers=headers or {"WWW-Authenticate": "Bearer"},
        )


class TooManyRequestsError(AppError):
    status_code = 429
    code = "too_many_requests"


class DomainValidationError(AppError):
    status_code = 422
    code = "domain_validation_error"


class ProviderUnavailableError(AppError):
    """An external provider (weather, LLM, ...) failed or is not configured."""

    status_code = 503
    code = "provider_unavailable"


def _envelope(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


_SOURCES = {"body", "query", "path", "header", "cookie"}
# Tags of discriminated request unions (register: farmer|buyer). Pydantic inserts the tag into the
# error path; clients want stable field names ("password", not "farmer.password").
_UNION_TAGS = frozenset({"farmer", "buyer"})
_TAG_ERRORS = {"union_tag_invalid", "union_tag_not_found"}


def _clean_validation_errors(errors: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Reduce pydantic errors to field/message/type.

    Deliberately drops `input` and `ctx`: echoing the offending input would leak
    submitted passwords back in error responses (and into logs/proxies).
    """
    cleaned: list[dict[str, str]] = []
    for err in errors:
        loc = [str(part) for part in err.get("loc", ())]
        if loc and loc[0] in _SOURCES:
            loc = loc[1:]
        if loc and loc[0] in _UNION_TAGS:
            loc = loc[1:]
        if err.get("type") in _TAG_ERRORS:  # e.g. unsupported/missing "role"
            loc = [str((err.get("ctx") or {}).get("discriminator", "")).strip("'")]
        message = str(err.get("msg", "Invalid value")).removeprefix("Value error, ")
        cleaned.append({"field": ".".join(loc), "message": message, "type": str(err.get("type", ""))})
    return cleaned


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details),
            headers=exc.headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope(
                "request_validation_error",
                "Invalid request",
                {"errors": _clean_validation_errors(exc.errors())},
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        # no internals in the body; the request id finds the full error in the server log
        from app.core.logging import request_id_var

        rid = request_id_var.get()
        return JSONResponse(
            status_code=500,
            content=_envelope("internal_error", f"Internal server error (reference {rid})", {"request_id": rid}),
        )
