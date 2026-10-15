"""Shared API schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str


class ComponentHealth(BaseModel):
    name: str
    status: Literal["ok", "unavailable", "disabled"]
    critical: bool


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded", "not_ready"]
    components: list[ComponentHealth]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class PageParams(BaseModel):
    """Resolved ?limit=&offset= query parameters (see api.deps.page_params)."""

    limit: int = 50
    offset: int = 0
