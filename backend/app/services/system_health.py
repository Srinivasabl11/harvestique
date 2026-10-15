"""Readiness evaluation (infrastructure service, not a business module)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from app.providers.llm.base import LLMProvider
from app.schemas.common import ComponentHealth, ReadinessResponse


class SystemHealthService:
    def __init__(self, db_check: Callable[[], bool], llm: LLMProvider, vision: Any = None) -> None:
        self._db_check = db_check
        self._llm = llm
        self._vision = vision  # the crop-photo classifier; only an AI one (with is_available) is probed

    def readiness(self) -> ReadinessResponse:
        db_ok = self._db_check()
        llm_status: Literal["ok", "unavailable", "disabled"] = "disabled"
        if self._llm.name != "disabled":
            llm_status = "ok" if self._llm.is_available() else "unavailable"

        probe = getattr(self._vision, "is_available", None)
        vision_status: Literal["ok", "unavailable", "disabled"] = "disabled"
        if callable(probe):
            vision_status = "ok" if probe() else "unavailable"

        components = [
            ComponentHealth(name="database", status="ok" if db_ok else "unavailable", critical=True),
            ComponentHealth(name=f"llm:{self._llm.name}", status=llm_status, critical=False),
            # crop-health check and produce-grading photo proposals; without it both say the AI is unavailable
            ComponentHealth(
                name=f"vision:{getattr(self._vision, 'name', 'none')}", status=vision_status, critical=False
            ),
        ]
        if not db_ok:
            overall = "not_ready"
        elif "unavailable" in (llm_status, vision_status):
            overall = "degraded"
        else:
            overall = "ready"
        return ReadinessResponse(status=overall, components=components)
