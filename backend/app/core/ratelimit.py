"""A per-user sliding-window limit for expensive calls (AI photo checks). In memory: the free hosted plan runs one
server process, and a restart only forgets the last hour's count, which errs on the side of the user."""

from __future__ import annotations

import threading
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta

from app.core.clock import Clock
from app.core.errors import TooManyRequestsError

WINDOW = timedelta(hours=1)


class HourlyLimit:
    def __init__(self, *, limit: int, clock: Clock, what: str) -> None:
        self._limit = limit
        self._clock = clock
        self._what = what
        self._calls: dict[uuid.UUID, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, user_id: uuid.UUID) -> None:
        """Count one call, or raise 429 (with Retry-After) when the user already made `limit` in the last hour."""
        now = self._clock.now()
        with self._lock:
            calls = self._calls[user_id]
            while calls and now - calls[0] >= WINDOW:
                calls.popleft()
            if len(calls) >= self._limit:
                wait = int((calls[0] + WINDOW - now).total_seconds()) + 1
                raise TooManyRequestsError(
                    f"You have used {self._limit} {self._what} in the last hour. Please try again in "
                    f"{max(1, wait // 60)} minutes.",
                    code="ai_photo_limit",
                    details={"limit_per_hour": self._limit, "retry_after_seconds": wait},
                    headers={"Retry-After": str(wait)},
                )
            calls.append(now)
