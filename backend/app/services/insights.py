"""Farm calendar and admin dashboard: read-only views assembled from recorded data (nothing estimated here except
values already labelled as estimates by the prediction engine)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.enums import CycleStatus, DataKind, LotStatus, OrderItemStatus, UserRole
from app.core.errors import DomainValidationError
from app.models.crop import Crop, CropCycle
from app.models.engagement import Reminder
from app.models.farm import Farm, FarmPlot
from app.models.farm_records import FarmActivity
from app.models.intelligence import InventoryLot, PredictionFeedback, YieldPrediction
from app.models.marketplace import BuyerOrder, BuyerOrderItem, CollectionHub, ProduceBatch, QualityCheck
from app.models.pooling import BuyerDemand, HarvestPool, ReallocationEvent
from app.models.user import User
from app.schemas.auth import CurrentUser
from app.schemas.engagement import CalendarEvent, CalendarOut, DashboardOut

MAX_CALENDAR_DAYS = 180


class InsightService:
    def __init__(self, *, session: Session, clock: Clock) -> None:
        self._session = session
        self._clock = clock

    # =============================================================== calendar
    def calendar(self, user: CurrentUser, start: date, end: date) -> CalendarOut:
        if end < start:
            raise DomainValidationError("end must not be before start", code="range_order")
        if (end - start).days > MAX_CALENDAR_DAYS:
            raise DomainValidationError(f"The range may cover at most {MAX_CALENDAR_DAYS} days", code="range_too_long")
        events = self._farmer_events(user.user_id, start, end) if user.role is UserRole.FARMER else []
        if user.role is UserRole.BUYER:
            events = self._buyer_events(user.user_id, start, end)
        events.extend(self._reminders(user.user_id, start, end))
        events.sort(key=lambda e: (e.start, e.kind, e.title))
        return CalendarOut(start=start, end=end, events=events)

    def _farmer_events(self, owner: uuid.UUID, start: date, end: date) -> list[CalendarEvent]:
        s = self._session
        out: list[CalendarEvent] = []
        cycles = s.execute(
            select(CropCycle, Farm, Crop.name)
            .join(FarmPlot, FarmPlot.id == CropCycle.plot_id)
            .join(Farm, Farm.id == FarmPlot.farm_id)
            .join(Crop, Crop.id == CropCycle.crop_id)
            .where(Farm.owner_id == owner, CropCycle.status != CycleStatus.ABANDONED)
        ).all()
        for cycle, farm, crop in cycles:
            common = {"farm_id": farm.id, "crop_cycle_id": cycle.id, "ref_id": cycle.id}
            if start <= cycle.sowing_date <= end:
                out.append(
                    CalendarEvent(
                        kind="sowing",
                        title=f"Sowing: {crop} ({farm.name})",
                        start=cycle.sowing_date,
                        end=None,
                        data_kind="user_entered",
                        **common,
                    )
                )
            if cycle.expected_harvest_date and start <= cycle.expected_harvest_date <= end:
                out.append(
                    CalendarEvent(
                        kind="expected_harvest",
                        title=f"Your expected harvest: {crop}",
                        start=cycle.expected_harvest_date,
                        end=None,
                        data_kind="user_entered",
                        **common,
                    )
                )
            pred = s.scalar(
                select(YieldPrediction)
                .where(YieldPrediction.crop_cycle_id == cycle.id)
                .order_by(YieldPrediction.version.desc())
                .limit(1)
            )
            if (
                pred is not None
                and pred.harvest_start_p10 <= end
                and pred.harvest_end_p90 >= start
                and cycle.status is not CycleStatus.HARVESTED
            ):
                out.append(
                    CalendarEvent(
                        kind="predicted_harvest_window",
                        title=f"Predicted harvest window: {crop} (v{pred.version})",
                        start=pred.harvest_start_p10,
                        end=pred.harvest_end_p90,
                        data_kind=DataKind.ESTIMATE,
                        **common,
                    )
                )
        acts = s.execute(
            select(FarmActivity, Farm.name)
            .join(Farm, Farm.id == FarmActivity.farm_id)
            .where(Farm.owner_id == owner, FarmActivity.activity_date >= start, FarmActivity.activity_date <= end)
        ).all()
        for act, farm_name in acts:
            out.append(
                CalendarEvent(
                    kind="activity",
                    title=f"{act.activity_type.value.replace('_', ' ').capitalize()} ({farm_name})",
                    start=act.activity_date,
                    end=None,
                    data_kind="user_entered",
                    farm_id=act.farm_id,
                    crop_cycle_id=act.crop_cycle_id,
                    ref_id=act.id,
                )
            )
        out.extend(self._batches(BuyerOrderItem.farmer_id == owner, start, end))
        items = s.execute(
            select(BuyerOrderItem, BuyerDemand)
            .join(BuyerOrder, BuyerOrder.id == BuyerOrderItem.order_id)
            .join(HarvestPool, HarvestPool.id == BuyerOrder.pool_id)
            .join(BuyerDemand, BuyerDemand.id == HarvestPool.demand_id)
            .where(
                BuyerOrderItem.farmer_id == owner,
                BuyerOrderItem.status == OrderItemStatus.ACCEPTED,
                BuyerDemand.window_start <= end,
                BuyerDemand.window_end >= start,
            )
        ).all()
        for item, demand in items:
            out.append(
                CalendarEvent(
                    kind="delivery_window",
                    title=f"Deliver {item.quantity_kg} kg (accepted order)",
                    start=demand.window_start,
                    end=demand.window_end,
                    data_kind="scheduled",
                    ref_id=item.id,
                )
            )
        return out

    def _buyer_events(self, buyer: uuid.UUID, start: date, end: date) -> list[CalendarEvent]:
        rows = self._session.execute(
            select(BuyerOrder, BuyerDemand, Crop.name)
            .join(HarvestPool, HarvestPool.id == BuyerOrder.pool_id)
            .join(BuyerDemand, BuyerDemand.id == HarvestPool.demand_id)
            .join(Crop, Crop.id == BuyerDemand.crop_id)
            .where(BuyerOrder.buyer_id == buyer, BuyerDemand.window_start <= end, BuyerDemand.window_end >= start)
        ).all()
        out = [
            CalendarEvent(
                kind="delivery_window",
                title=f"Delivery window: {order.ordered_kg} kg {crop} ({order.status.value})",
                start=d.window_start,
                end=d.window_end,
                data_kind="scheduled",
                ref_id=order.id,
            )
            for order, d, crop in rows
        ]
        out.extend(self._batches(BuyerOrder.buyer_id == buyer, start, end))
        return out

    def _batches(self, condition: object, start: date, end: date) -> list[CalendarEvent]:
        lo = datetime.combine(start, time.min, tzinfo=UTC)
        hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
        rows = self._session.execute(
            select(ProduceBatch, CollectionHub.name)
            .join(CollectionHub, CollectionHub.id == ProduceBatch.hub_id)
            .join(BuyerOrderItem, BuyerOrderItem.id == ProduceBatch.order_item_id)
            .join(BuyerOrder, BuyerOrder.id == BuyerOrderItem.order_id)
            .where(condition, ProduceBatch.received_at >= lo, ProduceBatch.received_at < hi)  # type: ignore[arg-type]
        ).all()
        return [
            CalendarEvent(
                kind="collection",
                title=f"Batch {b.code}: {b.received_kg} kg at {hub}",
                start=b.received_at.date(),
                end=None,
                data_kind=DataKind.MEASURED,
                ref_id=b.id,
            )
            for b, hub in rows
        ]

    def _reminders(self, owner: uuid.UUID, start: date, end: date) -> list[CalendarEvent]:
        lo = datetime.combine(start, time.min, tzinfo=UTC)
        hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
        rows = self._session.scalars(
            select(Reminder)
            .where(Reminder.owner_id == owner, Reminder.due_at >= lo, Reminder.due_at < hi)
            .order_by(Reminder.due_at)
        )
        return [
            CalendarEvent(
                kind="reminder",
                title=f"{r.title} ({r.status.value})",
                start=r.due_at.date(),
                end=None,
                data_kind="scheduled",
                farm_id=r.farm_id,
                crop_cycle_id=r.crop_cycle_id,
                ref_id=r.id,
            )
            for r in rows
        ]

    # ============================================================== dashboard
    def dashboard(self) -> DashboardOut:
        s = self._session
        now = self._clock.now()

        def grouped(col: object, model: type) -> dict[str, int]:
            rows = s.execute(select(col, func.count()).select_from(model).group_by(col)).all()  # type: ignore[call-overload]
            return {str(getattr(k, "value", k)): int(n) for k, n in rows}

        quality = s.execute(
            select(
                func.coalesce(func.sum(QualityCheck.accepted_kg), 0),
                func.coalesce(func.sum(QualityCheck.rejected_kg), 0),
            )
        ).one()
        received = s.scalar(select(func.coalesce(func.sum(ProduceBatch.received_kg), 0)))
        awaiting = s.scalar(
            select(func.count())
            .select_from(ProduceBatch)
            .where(~select(QualityCheck.id).where(QualityCheck.batch_id == ProduceBatch.id).exists())
        )
        events = s.execute(
            select(ReallocationEvent.outcome, func.count())
            .where(ReallocationEvent.created_at >= now - timedelta(days=30))
            .group_by(ReallocationEvent.outcome)
        ).all()
        scored = int(s.scalar(select(func.count()).select_from(PredictionFeedback)) or 0)
        available = s.scalar(
            select(func.coalesce(func.sum(InventoryLot.available_kg), 0)).where(
                InventoryLot.pool_eligible.is_(True), InventoryLot.status == LotStatus.OPEN
            )
        )
        return DashboardOut(
            generated_at=now,
            users=grouped(User.role, User),
            farms=int(s.scalar(select(func.count()).select_from(Farm)) or 0),
            active_cycles=int(
                s.scalar(
                    select(func.count())
                    .select_from(CropCycle)
                    .where(CropCycle.status.in_([CycleStatus.PLANNED, CycleStatus.GROWING]))
                )
                or 0
            ),
            lots=grouped(InventoryLot.status, InventoryLot),
            available_kg=available or 0,
            demands=grouped(BuyerDemand.status, BuyerDemand),
            pools=grouped(HarvestPool.status, HarvestPool),
            orders=grouped(BuyerOrder.status, BuyerOrder),
            reallocation_events_30d={str(o.value): int(n) for o, n in events},
            batches_awaiting_quality=int(awaiting or 0),
            quality={"received_kg": received or 0, "accepted_kg": quality[0], "rejected_kg": quality[1]},
            predictions_scored=scored,
            calibration_note=(
                "Prediction accuracy is measured only from recorded harvests; "
                + (
                    f"{scored} prediction versions scored so far."
                    if scored
                    else "none recorded yet, so no accuracy is claimed."
                )
            ),
        )
