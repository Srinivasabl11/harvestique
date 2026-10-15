"""Injectable clock so time-dependent logic (harvest windows, expiry, simulations) is testable."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Deterministic clock for tests and research simulations."""

    def __init__(self, fixed: datetime) -> None:
        if fixed.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._now = fixed

    def now(self) -> datetime:
        return self._now

    def advance_to(self, moment: datetime) -> None:
        self._now = moment
