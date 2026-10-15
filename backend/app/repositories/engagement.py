"""Reminders, notifications and crop-health analysis persistence."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.enums import CycleStatus, ReminderStatus
from app.models.crop import CropCycle
from app.models.engagement import CropHealthAnalysis, Notification, Reminder
from app.models.farm import Farm, FarmPlot
from app.models.farm_records import CropObservation, FarmExpense
from app.models.intelligence import YieldPrediction
from app.repositories.base import paginate


class EngagementRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, obj: object) -> None:
        self.session.add(obj)
        self.session.flush()

    # -------------------------------------------------------------- reminders
    def reminder(self, reminder_id: uuid.UUID, owner_id: uuid.UUID) -> Reminder | None:
        return self.session.scalar(select(Reminder).where(Reminder.id == reminder_id, Reminder.owner_id == owner_id))

    def reminders(
        self, owner_id: uuid.UUID, status: ReminderStatus | None, *, limit: int, offset: int
    ) -> tuple[list[Reminder], int]:
        stmt = select(Reminder).where(Reminder.owner_id == owner_id).order_by(Reminder.due_at, Reminder.id)
        if status is not None:
            stmt = stmt.where(Reminder.status == status)
        return paginate(self.session, stmt, limit=limit, offset=offset)

    def due_reminders(self, now: datetime, owner_id: uuid.UUID | None = None) -> list[Reminder]:
        """Pending reminders whose current occurrence has not been notified yet (row-locked, skip contended)."""
        stmt = select(Reminder).where(
            Reminder.status == ReminderStatus.PENDING,
            Reminder.due_at <= now,
            (Reminder.notified_for.is_(None)) | (Reminder.notified_for != Reminder.due_at),
        )
        if owner_id is not None:
            stmt = stmt.where(Reminder.owner_id == owner_id)
        return list(self.session.scalars(stmt.order_by(Reminder.due_at).with_for_update(skip_locked=True)))

    def reminders_between(self, owner_id: uuid.UUID, start: datetime, end: datetime) -> list[Reminder]:
        stmt = (
            select(Reminder)
            .where(Reminder.owner_id == owner_id, Reminder.due_at >= start, Reminder.due_at < end)
            .order_by(Reminder.due_at)
        )
        return list(self.session.scalars(stmt))

    # ---------------------------------------------------------- notifications
    def notify(self, row: dict[str, object]) -> bool:
        """Insert unless (user, dedup_key) exists. Returns True when a new notification was created."""
        stmt = (
            insert(Notification).values(**row).on_conflict_do_nothing(constraint="uq_notifications_user_id_dedup_key")
        )
        result = self.session.execute(stmt.returning(Notification.id))
        return result.scalar_one_or_none() is not None

    def notifications(
        self, user_id: uuid.UUID, unread_only: bool, *, limit: int, offset: int
    ) -> tuple[list[Notification], int]:
        stmt = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        return paginate(
            self.session, stmt.order_by(Notification.created_at.desc(), Notification.id), limit=limit, offset=offset
        )

    def unread_count(self, user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
        return int(self.session.scalar(stmt) or 0)

    def notification(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification | None:
        return self.session.scalar(
            select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
        )

    def mark_all_read(self, user_id: uuid.UUID, now: datetime) -> int:
        stmt = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=now)
        )
        return len(self.session.execute(stmt.returning(Notification.id)).all())

    # ------------------------------------------------------------ suggestions
    def active_cycles(self, owner_id: uuid.UUID) -> list[tuple[CropCycle, Farm]]:
        stmt = (
            select(CropCycle, Farm)
            .join(FarmPlot, FarmPlot.id == CropCycle.plot_id)
            .join(Farm, Farm.id == FarmPlot.farm_id)
            .where(Farm.owner_id == owner_id, CropCycle.status.in_([CycleStatus.PLANNED, CycleStatus.GROWING]))
            .order_by(CropCycle.sowing_date, CropCycle.id)
        )
        return [(c, f) for c, f in self.session.execute(stmt).all()]

    def last_observation(self, cycle_id: uuid.UUID) -> date | None:
        stmt = select(func.max(CropObservation.observed_on)).where(CropObservation.crop_cycle_id == cycle_id)
        return self.session.scalar(stmt)

    def last_expense(self, cycle_id: uuid.UUID) -> date | None:
        stmt = select(func.max(FarmExpense.expense_date)).where(FarmExpense.crop_cycle_id == cycle_id)
        return self.session.scalar(stmt)

    def latest_prediction(self, cycle_id: uuid.UUID) -> YieldPrediction | None:
        stmt = (
            select(YieldPrediction)
            .where(YieldPrediction.crop_cycle_id == cycle_id)
            .order_by(YieldPrediction.version.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def open_reminder_exists(self, owner_id: uuid.UUID, cycle_id: uuid.UUID, kind: str) -> bool:
        stmt = (
            select(func.count())
            .select_from(Reminder)
            .where(
                Reminder.owner_id == owner_id,
                Reminder.crop_cycle_id == cycle_id,
                Reminder.reminder_type == kind,
                Reminder.status == ReminderStatus.PENDING,
            )
        )
        return bool(self.session.scalar(stmt))

    # ------------------------------------------------------------ crop health
    def analyses(self, owner_id: uuid.UUID, cycle_id: uuid.UUID | None, *, limit: int) -> list[CropHealthAnalysis]:
        stmt = select(CropHealthAnalysis).where(CropHealthAnalysis.owner_id == owner_id)
        if cycle_id is not None:
            stmt = stmt.where(CropHealthAnalysis.crop_cycle_id == cycle_id)
        return list(self.session.scalars(stmt.order_by(CropHealthAnalysis.created_at.desc()).limit(limit)))
