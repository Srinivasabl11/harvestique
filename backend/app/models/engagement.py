"""Reminders, in-app notifications and crop-health analyses."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import CropHealthClass, NotificationCategory, Recurrence, ReminderStatus, ReminderType
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.intelligence import JSONType


class Reminder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reminders"
    __table_args__ = (Index("ix_reminders_owner_id_status_due_at", "owner_id", "status", "due_at"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    reminder_type: Mapped[ReminderType] = mapped_column(enum_column(ReminderType, name="reminder_type", length=24))
    title: Mapped[str] = mapped_column(String(160))
    notes: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime]
    recurrence: Mapped[Recurrence] = mapped_column(enum_column(Recurrence, name="recurrence", length=8))
    status: Mapped[ReminderStatus] = mapped_column(enum_column(ReminderStatus, name="reminder_status", length=16))
    farm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"))
    crop_cycle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crop_cycles.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(24))  # user / suggestion / assistant
    notified_for: Mapped[datetime | None]  # the due_at already turned into a notification


class Notification(UUIDPrimaryKeyMixin, Base):
    """In-app notification feed; the Android app fetches it and shows local notifications."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedup_key", name="uq_notifications_user_id_dedup_key"),
        Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category: Mapped[NotificationCategory] = mapped_column(
        enum_column(NotificationCategory, name="notification_category", length=32)
    )
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))  # info / warning / critical
    data: Mapped[dict[str, Any]] = mapped_column(JSONType)
    dedup_key: Mapped[str] = mapped_column(String(160))  # the same event never notifies twice
    read_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CropHealthAnalysis(UUIDPrimaryKeyMixin, Base):
    """Advisory result of a crop photo analysis. The image itself is NOT stored (only its hash)."""

    __tablename__ = "crop_health_analyses"
    __table_args__ = (CheckConstraint("width > 0 AND height > 0", name="dimensions_positive"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    crop_cycle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crop_cycles.id", ondelete="CASCADE"))
    image_sha256: Mapped[str] = mapped_column(String(64))
    width: Mapped[int]
    height: Mapped[int]
    label: Mapped[CropHealthClass] = mapped_column(enum_column(CropHealthClass, name="crop_health_class", length=24))
    probabilities: Mapped[dict[str, Any]] = mapped_column(JSONType)
    features: Mapped[dict[str, Any]] = mapped_column(JSONType)
    model_name: Mapped[str] = mapped_column(String(40))
    model_version: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
