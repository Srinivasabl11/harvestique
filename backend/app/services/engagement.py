"""Notifications (in-app feed) and reminders, including data-driven reminder suggestions.

Suggestions are computed only from what the farmer has recorded (observations, expenses, predictions); nothing is
invented. Weather-driven irrigation advice is NOT generated automatically: irrigation reminders are created by the
farmer (or by the assistant on the farmer's confirmed request).
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.enums import (
    CycleStatus,
    DataKind,
    HealthStatus,
    NotificationCategory,
    Recurrence,
    ReminderStatus,
    ReminderType,
)
from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.models.crop import CropCycle
from app.models.engagement import Reminder
from app.models.farm import Farm, FarmPlot
from app.models.farm_records import CropObservation
from app.providers.notifications.base import NotificationChannel, NotificationMessage
from app.repositories.engagement import EngagementRepository
from app.schemas.common import Page
from app.schemas.engagement import (
    NotificationOut,
    ReminderCreate,
    ReminderOut,
    ReminderSuggestion,
    ReminderUpdate,
    UnreadCount,
)

OBSERVATION_GAP_DAYS = 14
EXPENSE_GAP_DAYS = 30
HARVEST_LEAD_DAYS = 14
HEALTH_FOLLOW_UP_DAYS = 3
STEP = {Recurrence.DAILY: timedelta(days=1), Recurrence.WEEKLY: timedelta(days=7)}


PAST_TOLERANCE = timedelta(minutes=5)  # clock differences between phone and server


class NotificationService:
    def __init__(
        self, *, session: Session, repo: EngagementRepository, clock: Clock, channel: NotificationChannel
    ) -> None:
        self._session = session
        self._repo = repo
        self._clock = clock
        self._channel = channel

    def notify(
        self,
        user_id: uuid.UUID,
        category: NotificationCategory,
        title: str,
        body: str,
        *,
        dedup_key: str,
        severity: str = "info",
        data: dict[str, Any] | None = None,
    ) -> bool:
        """Record a notification once per (user, dedup_key). Caller commits."""
        payload = {str(k): str(v) for k, v in (data or {}).items()}
        created = self._repo.notify(
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "category": category,
                "title": title[:160],
                "body": body,
                "severity": severity,
                "data": payload,
                "dedup_key": dedup_key[:160],
            }
        )
        if created:
            self._channel.send(NotificationMessage(user_id, category.value, title, body, severity, payload))  # type: ignore[arg-type]
        return created

    def list_notifications(
        self, user_id: uuid.UUID, unread_only: bool, *, limit: int, offset: int
    ) -> Page[NotificationOut]:
        rows, total = self._repo.notifications(user_id, unread_only, limit=limit, offset=offset)
        return Page[NotificationOut](
            items=[NotificationOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
        )

    def unread(self, user_id: uuid.UUID) -> UnreadCount:
        return UnreadCount(unread=self._repo.unread_count(user_id))

    def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> NotificationOut:
        row = self._repo.notification(notification_id, user_id)
        if row is None:
            raise NotFoundError("Notification not found")
        if row.read_at is None:
            row.read_at = self._clock.now()
        self._session.commit()
        return NotificationOut.model_validate(row)

    def mark_all_read(self, user_id: uuid.UUID) -> UnreadCount:
        self._repo.mark_all_read(user_id, self._clock.now())
        self._session.commit()
        return UnreadCount(unread=0)


class ReminderService:
    def __init__(
        self, *, session: Session, repo: EngagementRepository, clock: Clock, notifications: NotificationService
    ) -> None:
        self._session = session
        self._repo = repo
        self._clock = clock
        self._notifications = notifications

    # ------------------------------------------------------------------ CRUD
    def create(self, owner_id: uuid.UUID, payload: ReminderCreate, source: str = "user") -> ReminderOut:
        self._check_not_past(payload.due_at)
        self._check_links(owner_id, payload.farm_id, payload.crop_cycle_id)
        row = Reminder(owner_id=owner_id, status=ReminderStatus.PENDING, source=source, **payload.model_dump())
        self._repo.add(row)
        self._session.commit()
        return ReminderOut.model_validate(row)

    def list_reminders(
        self, owner_id: uuid.UUID, status: ReminderStatus | None, *, limit: int, offset: int
    ) -> Page[ReminderOut]:
        rows, total = self._repo.reminders(owner_id, status, limit=limit, offset=offset)
        return Page[ReminderOut](
            items=[ReminderOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
        )

    def get(self, owner_id: uuid.UUID, reminder_id: uuid.UUID) -> ReminderOut:
        return ReminderOut.model_validate(self._require(owner_id, reminder_id))

    def update(self, owner_id: uuid.UUID, reminder_id: uuid.UUID, payload: ReminderUpdate) -> ReminderOut:
        row = self._require(owner_id, reminder_id)
        if row.status is not ReminderStatus.PENDING:
            raise ConflictError("Only a pending reminder can be changed", code="reminder_closed")
        changes = payload.model_dump(exclude_unset=True)
        if "due_at" in changes:
            self._check_not_past(changes["due_at"])  # rescheduling: the new occurrence is notified at its new time
        for k, v in changes.items():
            setattr(row, k, v)
        self._session.commit()
        return ReminderOut.model_validate(row)

    def delete(self, owner_id: uuid.UUID, reminder_id: uuid.UUID) -> None:
        """Remove the reminder (any status). Notifications already shown for it stay in the feed as history."""
        row = self._require(owner_id, reminder_id)
        self._session.delete(row)
        self._session.commit()

    def _check_not_past(self, due_at: datetime) -> None:
        if due_at < self._clock.now() - PAST_TOLERANCE:
            raise DomainValidationError(
                "The reminder time is in the past. Choose a future date and time.",
                code="due_in_past",
                details={"field": "due_at"},
            )

    def complete(self, owner_id: uuid.UUID, reminder_id: uuid.UUID) -> ReminderOut:
        """Done. A recurring reminder rolls forward to its next occurrence after now instead."""
        row = self._require(owner_id, reminder_id)
        if row.status is not ReminderStatus.PENDING:
            raise ConflictError("This reminder is already closed", code="reminder_closed")
        if row.recurrence is Recurrence.NONE:
            row.status = ReminderStatus.DONE
        else:
            now, step = self._clock.now(), STEP[row.recurrence]
            nxt = row.due_at + step
            while nxt <= now:
                nxt += step
            row.due_at = nxt
        self._session.commit()
        return ReminderOut.model_validate(row)

    def dismiss(self, owner_id: uuid.UUID, reminder_id: uuid.UUID) -> ReminderOut:
        row = self._require(owner_id, reminder_id)
        if row.status is not ReminderStatus.PENDING:
            raise ConflictError("This reminder is already closed", code="reminder_closed")
        row.status = ReminderStatus.DISMISSED
        self._session.commit()
        return ReminderOut.model_validate(row)

    # ----------------------------------------------------------- due → notify
    def process_due(self, owner_id: uuid.UUID | None = None) -> int:
        """Turn every due reminder occurrence into ONE notification (idempotent; safe to run concurrently)."""
        count = 0
        for row in self._repo.due_reminders(self._clock.now(), owner_id):
            created = self._notifications.notify(
                row.owner_id,
                NotificationCategory.REMINDER,
                row.title,
                row.notes or f"Reminder ({row.reminder_type.value.replace('_', ' ')}) is due.",
                dedup_key=f"reminder:{row.id}:{row.due_at.isoformat()}",
                data={"reminder_id": row.id, "reminder_type": row.reminder_type.value},
            )
            row.notified_for = row.due_at
            count += int(created)
        self._session.commit()
        return count

    # ------------------------------------------------------------ suggestions
    def suggestions(self, owner_id: uuid.UUID) -> list[ReminderSuggestion]:
        now = self._clock.now()
        today = now.date()
        morning = datetime.combine(today, time(3, 30), tzinfo=now.tzinfo)  # 09:00 IST expressed in UTC
        if morning < now:
            morning += timedelta(days=1)
        out: list[ReminderSuggestion] = []
        for cycle, farm in self._repo.active_cycles(owner_id):
            name = cycle.crop.name

            def add(
                kind: ReminderType,
                title: str,
                reason: str,
                due: datetime,
                basis: DataKind,
                c: CropCycle = cycle,
                f: Farm = farm,
            ) -> None:
                if not self._repo.open_reminder_exists(owner_id, c.id, kind.value):
                    out.append(
                        ReminderSuggestion(
                            reminder_type=kind,
                            title=title,
                            reason=reason,
                            due_at=due,
                            farm_id=f.id,
                            crop_cycle_id=c.id,
                            basis=basis,
                        )
                    )

            if cycle.status is CycleStatus.GROWING:
                last = self._repo.last_observation(cycle.id)
                if last is None or (today - last).days >= OBSERVATION_GAP_DAYS:
                    why = "No field observation recorded yet." if last is None else f"Last observation was on {last}."
                    add(ReminderType.CROP_OBSERVATION, f"Check {name} in {farm.name}", why, morning, DataKind.MEASURED)
                obs = self._latest_observation(cycle.id)
                if (
                    obs is not None
                    and obs.health_status is not HealthStatus.HEALTHY
                    and (today - obs.observed_on).days <= OBSERVATION_GAP_DAYS
                ):
                    add(
                        ReminderType.CROP_HEALTH,
                        f"Follow up {name} health ({obs.health_status.value.replace('_', ' ')})",
                        f"Observation on {obs.observed_on} recorded {obs.health_status.value.replace('_', ' ')}.",
                        morning + timedelta(days=HEALTH_FOLLOW_UP_DAYS - 1),
                        DataKind.MEASURED,
                    )
                spent = self._repo.last_expense(cycle.id)
                if (spent is None and (today - cycle.sowing_date).days >= EXPENSE_GAP_DAYS) or (
                    spent is not None and (today - spent).days >= EXPENSE_GAP_DAYS
                ):
                    add(
                        ReminderType.EXPENSE,
                        f"Record recent expenses for {name}",
                        "No expense recorded for this crop in the last 30 days.",
                        morning,
                        DataKind.MEASURED,
                    )
            pred = self._repo.latest_prediction(cycle.id)
            # the predicted window starts within the lead time (or has already opened) and has not ended yet
            if (
                pred is not None
                and (pred.harvest_start_p10 - today).days <= HARVEST_LEAD_DAYS
                and pred.harvest_end_p90 >= today
            ):
                due = datetime.combine(pred.harvest_start_p10 - timedelta(days=2), time(3, 30), tzinfo=now.tzinfo)
                add(
                    ReminderType.HARVEST,
                    f"Prepare to harvest {name}",
                    f"Predicted harvest window {pred.harvest_start_p10} to {pred.harvest_end_p90} "
                    f"(prediction v{pred.version}, an estimate).",
                    max(due, morning),
                    DataKind.ESTIMATE,
                )
        return out

    # --------------------------------------------------------------- helpers
    def _require(self, owner_id: uuid.UUID, reminder_id: uuid.UUID) -> Reminder:
        row = self._repo.reminder(reminder_id, owner_id)
        if row is None:
            raise NotFoundError("Reminder not found")
        return row

    def _latest_observation(self, cycle_id: uuid.UUID) -> CropObservation | None:
        stmt = (
            select(CropObservation)
            .where(CropObservation.crop_cycle_id == cycle_id)
            .order_by(CropObservation.observed_on.desc(), CropObservation.created_at.desc())
            .limit(1)
        )
        return self._session.scalar(stmt)

    def _check_links(self, owner_id: uuid.UUID, farm_id: uuid.UUID | None, cycle_id: uuid.UUID | None) -> None:
        if farm_id is not None:
            farm = self._session.get(Farm, farm_id)
            if farm is None or farm.owner_id != owner_id:
                raise NotFoundError("Farm not found")
        if cycle_id is not None:
            cycle = self._session.get(CropCycle, cycle_id)
            plot = self._session.get(FarmPlot, cycle.plot_id) if cycle else None
            farm = self._session.get(Farm, plot.farm_id) if plot else None
            if farm is None or farm.owner_id != owner_id:
                raise NotFoundError("Crop cycle not found")
