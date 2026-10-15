"""In-memory notification channel for tests and development."""

from __future__ import annotations

from app.providers.notifications.base import NotificationMessage


class FakeNotificationChannel:
    name = "fake"

    def __init__(self) -> None:
        self.sent: list[NotificationMessage] = []

    def send(self, message: NotificationMessage) -> None:
        self.sent.append(message)


class InAppNotificationChannel:
    """Default channel: notifications are stored in the in-app feed by NotificationService (the Android app polls
    it and shows local notifications). No external push service is contacted."""

    name = "in_app"

    def send(self, message: NotificationMessage) -> None:
        return None
