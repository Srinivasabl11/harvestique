"""Typed OpenAPI `responses=` blocks shared by route modules (documentation only)."""

from __future__ import annotations

from typing import Any

from app.schemas.common import ErrorResponse

type Responses = dict[int | str, dict[str, Any]]


def _r(*codes: int) -> Responses:
    return {code: {"model": ErrorResponse} for code in codes}


AUTH_ONLY: Responses = _r(401)
AUTH_NOT_FOUND: Responses = _r(401, 404)
ERR: Responses = _r(401, 403, 404)  # farmer endpoints: unauthenticated / wrong role / not yours
WRITE_ERR: Responses = _r(401, 403, 404, 409, 422)  # + conflicts and rule violations
