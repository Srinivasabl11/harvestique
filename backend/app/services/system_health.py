"""Readiness evaluation (infrastructure service, not a business module)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from app.providers.llm.base import LLMProvider
from app.schemas.common import ComponentHealth, ReadinessResponse


class SystemHealthService:
    def __init__(self, db_check: Callable[[], bool], llm: LLMProvider) -> None:
        self._db_check = db_check
        self._llm = llm

    def readiness(self) -> ReadinessResponse:
        db_ok = self._db_check()
        llm_status: Literal["ok", "unavailable", "disabled"] = "disabled"
        if self._llm.name != "disabled":
            llm_status = "ok" if self._llm.is_available() else "unavailable"

        components = [
            ComponentHealth(name="database", status="ok" if db_ok else "unavailable", critical=True),
            ComponentHealth(name=f"llm:{self._llm.name}", status=llm_status, critical=False),
        ]
        if not db_ok:
            overall = "not_ready"
        elif llm_status == "unavailable":
            overall = "degraded"
        else:
            overall = "ready"
        return ReadinessResponse(status=overall, components=components)
