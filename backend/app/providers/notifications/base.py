"""Notification channel contract.

Delivery model: the backend records notifications; the Flutter app fetches them
and shows LOCAL Android notifications (no paid push service). A push channel
(e.g. FCM) could be added later as another implementation of this Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

Severity = Literal["info", "warning", "critical"]


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    recipient_user_id: UUID
    category: str  # e.g. "shortage_detected", "allocation_changed"
    title: str
    body: str
    severity: Severity = "info"
    data: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class NotificationChannel(Protocol):
    name: str

    def send(self, message: NotificationMessage) -> None: ...
