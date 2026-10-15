"""Marketplace use cases: orders on harvest pools, farmer participation, collection, quality, fulfilment,
traceability and market search.

Every quantity flows through the existing invariants: pool allocations reserve Phase 4 inventory (p10-based, no
negatives, no double booking), reallocation is the Phase 5 path, and fulfilment uses the inventory's own rule (only
after a MEASURED harvest). Lock order everywhere: order row -> pool row -> lots (by id). No price is ever stored,
shown or computed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.enums import (
    AllocationStatus,
    BatchStatus,
    BuyerType,
    DataKind,
    FarmerProgress,
    NotificationCategory,
    OrderItemStatus,
    OrderStatus,
    ParticipationStatus,
    QualityGrade,
    UserRole,
)
from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.domain.marketplace import (
    OPEN_ITEMS,
    MarketplaceRuleError,
    batch_code,
    check_cancel,
    check_respond,
    fulfil_quantity,
    order_quantities,
    order_status,
    quality_result,
)
from app.domain.pooling.models import DemandSpec
from app.models.crop import Crop
from app.models.marketplace import (
    BuyerOrder,
    BuyerOrderItem,
    CollectionHub,
    FarmerParticipation,
    ProduceBatch,
    QualityCheck,
)
from app.models.pooling import BuyerDemand, HarvestAllocation, HarvestPool
from app.models.profiles import BuyerProfile
from app.repositories.marketplace import MarketplaceRepository
from app.repositories.pooling import PoolingRepository
from app.schemas.auth import CurrentUser
from app.schemas.common import Page
from app.schemas.marketplace import (
    BatchCreate,
    BatchOut,
    BatchTrace,
    FulfilmentOut,
    HubCreate,
    HubOut,
    HubUpdate,
    Opportunity,
    OrderCreate,
    OrderItemOut,
    OrderOut,
    OrderTrace,
    ParticipationOut,
    QualityIn,
    QualityOut,
    SupplySummary,
    TraceItem,
    TraceStep,
)
from app.schemas.pooling import EventOut, MatchesOut
from app.services.engagement import NotificationService
from app.services.pooling import PoolService

logger = logging.getLogger(__name__)
ZERO = Decimal(0)
TERMINAL_ORDER = (OrderStatus.CANCELLED, OrderStatus.FULFILLED, OrderStatus.PARTIALLY_FULFILLED)


def _rule(exc: MarketplaceRuleError) -> Exception:
    if exc.code in ("quantities_mismatch", "negative_quantity", "grade_required", "grade_below_order_minimum"):
        return DomainValidationError(exc.message, code=exc.code)
    return ConflictError(exc.message, code=exc.code)


def _ref(farm_id: uuid.UUID) -> str:
    return str(farm_id)[:8]  # same pseudonymous reference as pool matching


def _order_ref(order_id: uuid.UUID) -> str:
    """The order ID as people see it in the app: #1A2B3C4D (first 8 characters)."""
    return f"#{str(order_id)[:8].upper()}"


def _kg(q: Decimal) -> str:
    return f"{q.normalize():f}"


class MarketplaceService:
    def __init__(
        self,
        *,
        session: Session,
        repo: MarketplaceRepository,
        pool_repo: PoolingRepository,
        pools: PoolService,
        notifications: NotificationService,
        clock: Clock,
    ) -> None:
        self._session = session
        self._repo = repo
        self._pool_repo = pool_repo
        self._pools = pools
        self._notifications = notifications
        self._clock = clock

    # ================================================================= orders

    def place_order(self, buyer_id: uuid.UUID, payload: OrderCreate, key: str | None) -> OrderOut:
        existing = self._repo.order_for_pool(payload.pool_id)
        if existing is not None and existing.buyer_id == buyer_id:
            if key and existing.idempotency_key == key:
                return self._order_out(existing)  # safe retry
            raise ConflictError(
                "This pool already has an order", code="order_exists", details={"order_id": str(existing.id)}
            )
        pool = self._pool_repo.pool(payload.pool_id, lock=True)
        if pool is None or pool.buyer_id != buyer_id:
            raise NotFoundError("Pool not found")
        if pool.closed_at is not None:
            raise ConflictError("This pool is closed", code="pool_closed")
        if pool.allocated_kg <= 0:
            raise ConflictError("The pool has no allocated supply to order", code="pool_empty")
        if payload.delivery_hub_id is not None:
            self._active_hub(payload.delivery_hub_id)
        order = BuyerOrder(
            buyer_id=buyer_id,
            pool_id=pool.id,
            status=OrderStatus.PLACED,
            ordered_kg=pool.demand_kg,
            fulfilled_kg=ZERO,
            delivery_hub_id=payload.delivery_hub_id,
            notes=payload.notes,
            idempotency_key=key,
        )
        try:
            self._repo.add(order)
            for alloc in self._pool_repo.allocations(pool.id):
                if alloc.quantity_kg > 0:
                    self._new_item(order, alloc)
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("This pool already has an order", code="order_exists") from exc
        return self._order_out(order)

    def list_orders(self, user: CurrentUser, status: OrderStatus | None, *, limit: int, offset: int) -> Page[OrderOut]:
        buyer = None if user.role is UserRole.ADMIN else user.user_id
        rows, total = self._repo.orders(buyer, status, limit=limit, offset=offset)
        return Page[OrderOut](items=[self._order_out(o) for o in rows], total=total, limit=limit, offset=offset)

    def get_order(self, user: CurrentUser, order_id: uuid.UUID) -> OrderOut:
        return self._order_out(self._visible_order(user, order_id))

    def cancel_order(self, buyer_id: uuid.UUID, order_id: uuid.UUID) -> OrderOut:
        order = self._repo.order(order_id, lock=True)
        if order is None or order.buyer_id != buyer_id:
            raise NotFoundError("Order not found")
        try:
            check_cancel(order.status, self._repo.any_batch(order.id))
        except MarketplaceRuleError as exc:
            raise _rule(exc) from exc
        try:
            for item in self._repo.items(order.id):
                if item.status in OPEN_ITEMS:
                    item.status = OrderItemStatus.CANCELLED
                    part = self._repo.participation(item.participation_id)
                    assert part is not None
                    part.status = ParticipationStatus.WITHDRAWN
                    self._notify_farmer(
                        item,
                        "Order cancelled",
                        f"The buyer cancelled the order; your {item.quantity_kg} kg is free again.",
                        f"cancel:{item.id}",
                    )
            order.status = OrderStatus.CANCELLED
            self._pools.close_pool(order.pool_id, "order cancelled by buyer", buyer_id, release=True)
            self._session.commit()
        except BaseException:
            self._session.rollback()
            raise
        return self._order_out(order)

    # ========================================================== participation

    def participations(
        self, farmer_id: uuid.UUID, status: ParticipationStatus | None, *, limit: int, offset: int
    ) -> Page[ParticipationOut]:
        rows, total = self._repo.participations(farmer_id, status, limit=limit, offset=offset)
        return Page[ParticipationOut](
            items=[self._participation_out(p) for p in rows], total=total, limit=limit, offset=offset
        )

    def accept(self, farmer_id: uuid.UUID, participation_id: uuid.UUID) -> ParticipationOut:
        part, item, order = self._own_participation(farmer_id, participation_id)
        try:
            check_respond(part.status, item.status, decline=False, has_batch=bool(self._repo.batches_for_item(item.id)))
        except MarketplaceRuleError as exc:
            raise _rule(exc) from exc
        part.status = ParticipationStatus.ACCEPTED
        part.responded_at = self._clock.now()
        item.status = OrderItemStatus.ACCEPTED
        self._refresh(order)
        crop = self._item_crop(item)
        self._notifications.notify(
            order.buyer_id,
            NotificationCategory.PARTICIPATION_RESPONSE,
            f"Order {_order_ref(order.id)}: a farm confirmed",
            f"Farm {self._farm_ref(item)} confirmed {_kg(item.quantity_kg)} kg of {crop} for order "
            f"{_order_ref(order.id)}. Order status: {order.status.value.replace('_', ' ')}.",
            dedup_key=f"accept:{part.id}",
            data={"order_id": order.id, "participation_id": part.id},
        )
        self._session.commit()
        return self._participation_out(part)

    def decline(self, farmer_id: uuid.UUID, participation_id: uuid.UUID, reason: str) -> ParticipationOut:
        """Declining releases the farm's supply and immediately runs dynamic reallocation for the pool; the decline
        and the reallocation commit together (or not at all)."""
        part, item, order = self._own_participation(farmer_id, participation_id)
        try:
            check_respond(part.status, item.status, decline=True, has_batch=bool(self._repo.batches_for_item(item.id)))
        except MarketplaceRuleError as exc:
            raise _rule(exc) from exc
        part.status = ParticipationStatus.DECLINED
        part.responded_at = self._clock.now()
        part.reason = reason
        item.status = OrderItemStatus.DECLINED
        self._session.flush()
        alloc = self._session.get(HarvestAllocation, item.allocation_id)
        assert alloc is not None
        self._notifications.notify(
            order.buyer_id,
            NotificationCategory.PARTICIPATION_RESPONSE,
            f"Order {_order_ref(order.id)}: a farm declined",
            f"Farm {self._farm_ref(item)} declined {_kg(item.quantity_kg)} kg of {self._item_crop(item)} for order "
            f"{_order_ref(order.id)}. Harvestique is looking for replacement supply from other farms.",
            severity="warning",
            dedup_key=f"decline:{part.id}",
            data={"order_id": order.id, "participation_id": part.id},
        )
        # commits the decline together with the reallocation; then calls sync_pool (new items, notifications)
        self._pools.withdraw_lot(order.pool_id, alloc.lot_id, reason, farmer_id, f"decline:{part.id}")
        self._session.refresh(part)
        return self._participation_out(part)

    def progress(self, farmer_id: uuid.UUID, participation_id: uuid.UUID, stage: FarmerProgress) -> ParticipationOut:
        """The farmer marks an ACCEPTED request as preparing, then ready. Forward only; repeating a step changes
        nothing (and sends no second notification)."""
        part, item, order = self._own_participation(farmer_id, participation_id)
        if part.status is not ParticipationStatus.ACCEPTED or item.status is not OrderItemStatus.ACCEPTED:
            raise ConflictError(
                "Accept the request first; a declined or closed request cannot be updated", code="not_accepted"
            )
        if order.status in TERMINAL_ORDER:
            raise ConflictError("This order is already closed", code="order_closed")
        order_rank = [None, FarmerProgress.PREPARING, FarmerProgress.READY]
        if order_rank.index(stage) < order_rank.index(part.progress):
            raise ConflictError("This order is already marked ready", code="progress_backwards")
        if part.progress is stage:
            return self._participation_out(part)
        part.progress, part.progress_at = stage, self._clock.now()
        crop = self._item_crop(item)
        word = "is preparing" if stage is FarmerProgress.PREPARING else "has made ready"
        self._notifications.notify(
            order.buyer_id,
            NotificationCategory.ORDER_UPDATE,
            f"Order {_order_ref(order.id)}: {crop} {stage.value}",
            f"Farm {self._farm_ref(item)} {word} {_kg(item.quantity_kg)} kg of {crop} for order "
            f"{_order_ref(order.id)}. Order status: {order.status.value.replace('_', ' ')}.",
            dedup_key=f"progress:{part.id}:{stage.value}",
            data={"order_id": order.id, "participation_id": part.id, "stage": stage.value},
        )
        self._session.commit()
        return self._participation_out(part)

    # ================================================ hooks from pool service

    def sync_pool(self, pool_id: uuid.UUID, event: EventOut) -> None:
        """After every committed reallocation: align the order's items with the pool's allocations and tell the
        people affected. Idempotent (derived from allocations); failures are logged and retried by the next sync."""
        try:
            self._sync(pool_id, event)
            self._session.commit()
        except Exception:
            self._session.rollback()
            logger.exception("order sync failed for pool %s", pool_id)

    def _sync(self, pool_id: uuid.UUID, event: EventOut) -> None:
        pool = self._pool_repo.pool(pool_id)
        assert pool is not None
        if event.outcome.value == "top_up":
            self._notifications.notify(
                pool.buyer_id,
                NotificationCategory.REALLOCATION,
                "New supply found for your demand",
                f"{event.topped_up_kg} kg of newly predicted supply was added to your pool "
                f"(still {max(Decimal(0), pool.demand_kg - pool.allocated_kg)} kg uncovered). "
                "It is an estimate; the farmer must still accept it.",
                dedup_key=f"event:{event.id}",
                data={"pool_id": pool.id, "event_id": event.id},
            )
        elif event.outcome.value != "no_change":
            unresolved = Decimal(str(event.unresolved_kg))
            self._notifications.notify(
                pool.buyer_id,
                NotificationCategory.SHORTAGE if unresolved > 0 else NotificationCategory.REALLOCATION,
                "Supply shortage not fully covered" if unresolved > 0 else "Supply rebalanced",
                f"Shortage {event.shortage_kg} kg, replaced {event.replaced_kg} kg, "
                f"unresolved {event.unresolved_kg} kg.",
                severity="warning" if unresolved > 0 else "info",
                dedup_key=f"event:{event.id}",
                data={"pool_id": pool.id, "event_id": event.id},
            )
        order = self._repo.order_for_pool(pool_id, lock=True)
        if order is None or order.status in TERMINAL_ORDER:
            return
        by_alloc = {i.allocation_id: i for i in self._repo.items(order.id)}
        for alloc in self._pool_repo.allocations(pool.id):
            item = by_alloc.get(alloc.id)
            if item is None:
                if alloc.quantity_kg > 0 and alloc.status is not AllocationStatus.FULFILLED:
                    self._new_item(order, alloc)
                continue
            if item.status not in OPEN_ITEMS or item.quantity_kg == alloc.quantity_kg:
                continue
            part = self._repo.participation(item.participation_id)
            assert part is not None
            old = item.quantity_kg
            if alloc.quantity_kg == 0:
                item.status, part.status = OrderItemStatus.REMOVED, ParticipationStatus.WITHDRAWN
                self._notify_farmer(
                    item,
                    "Your supply is no longer needed",
                    f"Your predicted supply fell, so the {old} kg request was withdrawn.",
                    f"removed:{item.id}:{event.id}",
                )
            elif alloc.quantity_kg < old:
                self._notify_farmer(
                    item,
                    "Requested quantity reduced",
                    f"Your committed quantity changed from {old} kg to {alloc.quantity_kg} kg "
                    "after your prediction changed.",
                    f"reduced:{item.id}:{event.id}",
                )
            else:  # more than the farmer agreed to: ask again
                part.status, item.status = ParticipationStatus.PENDING, OrderItemStatus.AWAITING_FARMER
                self._notify_farmer(
                    item,
                    "Please confirm a larger quantity",
                    f"The pool now asks {alloc.quantity_kg} kg (was {old} kg). Please accept or decline.",
                    f"increased:{item.id}:{event.id}",
                )
            item.quantity_kg = alloc.quantity_kg
        self._refresh(order)

    def notify_demand(self, demand: BuyerDemand) -> None:
        """Buyer opportunity: farmers growing the crop are told (no buyer identity, no price)."""
        crop = self._session.get(Crop, demand.crop_id)
        name = crop.name if crop else "a crop you grow"
        for farmer_id in self._repo.farmers_growing(demand.crop_id):
            self._notifications.notify(
                farmer_id,
                NotificationCategory.BUYER_OPPORTUNITY,
                f"Buyer looking for {name}",
                f"A buyer wants {demand.quantity_kg} kg of {name} (grade {demand.min_grade.value} or better) between "
                f"{demand.window_start} and {demand.window_end}. Opt your lot into pooling to be considered.",
                dedup_key=f"demand:{demand.id}",
                data={"demand_id": demand.id},
            )

    # ================================================================== hubs

    def create_hub(self, payload: HubCreate) -> HubOut:
        hub = CollectionHub(**payload.model_dump())
        try:
            self._repo.add(hub)
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("A hub with this name already exists", code="hub_exists") from exc
        return HubOut.model_validate(hub)

    def list_hubs(self, include_inactive: bool) -> list[HubOut]:
        return [HubOut.model_validate(h) for h in self._repo.hubs(active_only=not include_inactive)]

    def update_hub(self, hub_id: uuid.UUID, payload: HubUpdate) -> HubOut:
        hub = self._repo.hub(hub_id)
        if hub is None:
            raise NotFoundError("Hub not found")
        for k, v in payload.model_dump(exclude_unset=True).items():
            if v is None:
                raise DomainValidationError(f"{k} cannot be null", code="null_not_allowed")
            setattr(hub, k, v)
        self._session.commit()
        return HubOut.model_validate(hub)

    # ============================================ collection, quality, fulfilment

    def receive_batch(self, operator_id: uuid.UUID, payload: BatchCreate) -> BatchOut:
        item = self._repo.item(payload.order_item_id)
        if item is None:
            raise NotFoundError("Order item not found")
        order = self._repo.order(item.order_id, lock=True)
        assert order is not None
        self._session.refresh(item)
        if item.status is not OrderItemStatus.ACCEPTED:
            raise ConflictError(
                "Produce can only be received for an item the farmer has accepted", code="item_not_accepted"
            )
        hub = self._active_hub(payload.hub_id)
        lot, cycle, _farm = self._repo.lot_context(item.lot_id)
        harvest = self._repo.harvest_for_cycle(cycle.id)
        if harvest is None:
            raise ConflictError(
                "The farmer must record the harvest (measured quantity) first", code="harvest_not_recorded"
            )
        now = self._clock.now()
        for _attempt in range(3):
            batch = ProduceBatch(
                code=batch_code(uuid.uuid4().hex, now.strftime("%y%m%d")),
                order_item_id=item.id,
                lot_id=lot.id,
                harvest_actual_id=harvest.id,
                hub_id=hub.id,
                received_kg=payload.received_kg,
                received_at=now,
                received_by=operator_id,
                status=BatchStatus.RECEIVED,
                notes=payload.notes,
            )
            try:
                with self._session.begin_nested():
                    self._repo.add(batch)
                break
            except IntegrityError:  # code collision (1 in 16.7M per day): try another code
                continue
        else:  # pragma: no cover - three collisions in a row
            raise ConflictError("Could not allocate a batch code; retry", code="batch_code_conflict")
        self._refresh(order)
        msg = f"Batch {batch.code}: {batch.received_kg} kg received at {hub.name}."
        self._notify_farmer(item, "Produce received", msg, f"batch:{batch.id}")
        self._notifications.notify(
            order.buyer_id,
            NotificationCategory.COLLECTION,
            "Produce received",
            msg,
            dedup_key=f"batch:{batch.id}",
            data={"order_id": order.id},
        )
        self._session.commit()
        return self._batch_out(batch)

    def remove_batch(self, batch_id: uuid.UUID) -> None:
        """Remove a batch entered by mistake. Only before its quality check: after that it is part of the order's
        fulfilment and traceability record and must stay."""
        batch = self._repo.batch(batch_id, lock=True)
        if batch is None:
            raise NotFoundError("Batch not found")
        if self._repo.quality(batch.id) is not None or batch.status is not BatchStatus.RECEIVED:
            raise ConflictError(
                "This batch was already quality-checked and is part of the order's record; it cannot be removed",
                code="batch_in_use",
            )
        self._session.delete(batch)
        self._session.commit()

    def record_quality(self, inspector_id: uuid.UUID, batch_id: uuid.UUID, payload: QualityIn) -> BatchOut:
        batch = self._repo.batch(batch_id, lock=True)
        if batch is None:
            raise NotFoundError("Batch not found")
        if self._repo.quality(batch.id) is not None:
            raise ConflictError("Quality has already been recorded for this batch", code="quality_already_recorded")
        item = self._repo.item(batch.order_item_id)
        assert item is not None
        demand = self._demand_for_order(item.order_id)
        try:
            result = quality_result(
                batch.received_kg, payload.accepted_kg, payload.rejected_kg, payload.grade, demand.min_grade
            )
        except MarketplaceRuleError as exc:
            raise _rule(exc) from exc
        check = QualityCheck(
            batch_id=batch.id,
            inspector_id=inspector_id,
            grade=payload.grade,
            result=result,
            accepted_kg=payload.accepted_kg,
            rejected_kg=payload.rejected_kg,
            moisture_percent=payload.moisture_percent,
            defects=payload.defects,
            checked_at=self._clock.now(),
        )
        self._repo.add(check)
        batch.status = BatchStatus.QUALITY_CHECKED
        order = self._repo.order(item.order_id)
        assert order is not None
        grade = payload.grade.value if payload.grade else "-"
        msg = (
            f"Batch {batch.code}: {result.value.replace('_', ' ')} (grade {grade}); "
            f"accepted {payload.accepted_kg} kg, rejected {payload.rejected_kg} kg."
        )
        self._notify_farmer(item, "Quality checked", msg, f"quality:{batch.id}", category=NotificationCategory.QUALITY)
        self._notifications.notify(
            order.buyer_id,
            NotificationCategory.QUALITY,
            "Quality checked",
            msg,
            dedup_key=f"quality:{batch.id}",
            data={"order_id": order.id},
        )
        self._session.commit()
        return self._batch_out(batch)

    def fulfil_item(self, operator_id: uuid.UUID, item_id: uuid.UUID) -> FulfilmentOut:
        item = self._repo.item(item_id)
        if item is None:
            raise NotFoundError("Order item not found")
        order = self._repo.order(item.order_id, lock=True)
        assert order is not None
        self._session.refresh(item)
        if item.status is not OrderItemStatus.ACCEPTED:
            raise ConflictError(f"A {item.status.value} item cannot be fulfilled", code="item_not_fulfillable")
        batches = self._repo.batches_for_item(item.id)
        if not batches:
            raise ConflictError("No produce has been received for this item", code="no_batches")
        checks = [self._repo.quality(b.id) for b in batches]
        if any(c is None for c in checks):
            raise ConflictError("Every batch needs a quality check before fulfilment", code="quality_pending")
        accepted = sum((c.accepted_kg for c in checks if c is not None), ZERO)
        qty = fulfil_quantity(accepted, item.quantity_kg)
        try:
            self._pools.fulfil_allocation(order.pool_id, item.allocation_id, qty, operator_id)
            item.fulfilled_kg = qty
            item.status = OrderItemStatus.FULFILLED if qty > 0 else OrderItemStatus.SHORT
            for b in batches:
                b.status = BatchStatus.CLOSED
            order.fulfilled_kg = sum((i.fulfilled_kg for i in self._repo.items(order.id)), ZERO)
            self._refresh(order)
            if order.status in (OrderStatus.FULFILLED, OrderStatus.PARTIALLY_FULFILLED):
                self._pools.close_pool(order.pool_id, f"order {order.status.value}", operator_id, release=False)
            msg = f"{qty} kg delivered and counted for the order (quality-accepted {accepted} kg)."
            self._notify_farmer(
                item, "Delivery completed", msg, f"fulfil:{item.id}", category=NotificationCategory.FULFILMENT
            )
            self._notifications.notify(
                order.buyer_id,
                NotificationCategory.FULFILMENT,
                "Delivery completed",
                msg,
                dedup_key=f"fulfil:{item.id}",
                data={"order_id": order.id},
            )
            self._session.commit()
        except BaseException:
            self._session.rollback()
            raise
        return FulfilmentOut(
            order_item_id=item.id,
            item_status=item.status,
            accepted_kg=accepted,
            fulfilled_kg=qty,
            order_status=order.status,
            order_fulfilled_kg=order.fulfilled_kg,
            note="Fulfilled quantity = quality-accepted (measured) produce, capped at the farm's committed share.",
        )

    def list_batches(
        self, hub_id: uuid.UUID | None, awaiting_quality: bool, *, limit: int, offset: int
    ) -> Page[BatchOut]:
        rows, total = self._repo.batches(hub_id, awaiting_quality, limit=limit, offset=offset)
        return Page[BatchOut](items=[self._batch_out(b) for b in rows], total=total, limit=limit, offset=offset)

    def batches_for_order(self, user: CurrentUser, order_id: uuid.UUID) -> list[BatchOut]:
        order = self._visible_order(user, order_id)
        return [self._batch_out(b) for i in self._repo.items(order.id) for b in self._repo.batches_for_item(i.id)]

    # ============================================================ traceability

    def order_trace(self, user: CurrentUser, order_id: uuid.UUID) -> OrderTrace:
        order = self._visible_order(user, order_id)
        pool = self._pool_repo.pool(order.pool_id)
        assert pool is not None
        demand = self._session.get(BuyerDemand, pool.demand_id)
        assert demand is not None
        crop = self._session.get(Crop, demand.crop_id)
        ledger = self._pool_repo.ledger(pool.id)
        items: list[TraceItem] = []
        for item in self._repo.items(order.id):
            lot, cycle, farm = self._repo.lot_context(item.lot_id)
            part = self._repo.participation(item.participation_id)
            assert part is not None
            steps = [
                TraceStep(
                    step="allocation",
                    at=None,
                    data_kind=DataKind.ESTIMATE,
                    detail={
                        "quantity_kg": float(item.quantity_kg),
                        "basis": "p10 (pessimistic) predicted supply",
                        "ledger": [
                            {
                                "action": r.action,
                                "before_kg": float(r.quantity_before),
                                "after_kg": float(r.quantity_after),
                                "reason": r.reason,
                                "at": r.created_at.isoformat(),
                            }
                            for r in ledger
                            if r.lot_id == lot.id
                        ],
                    },
                ),
                TraceStep(
                    step="farmer_participation",
                    at=part.responded_at,
                    data_kind="user_entered",
                    detail={"status": part.status.value, "reason": part.reason},
                ),
                TraceStep(
                    step="predictions",
                    at=None,
                    data_kind=DataKind.ESTIMATE,
                    detail={
                        "versions": [
                            {
                                "version": p.version,
                                "p10_kg": _f(p.p10_kg),
                                "p50_kg": _f(p.p50_kg),
                                "p90_kg": _f(p.p90_kg),
                                "model": f"{p.model_name} {p.model_version}",
                                "created_at": p.created_at.isoformat(),
                            }
                            for p in self._repo.predictions(cycle.id)
                        ]
                    },
                ),
            ]
            harvest = self._repo.harvest_for_cycle(cycle.id)
            steps.append(
                TraceStep(
                    step="harvest",
                    at=harvest.harvest_start_date if harvest else None,
                    data_kind=DataKind.MEASURED if harvest else "pending",
                    detail={"quantity_kg": _f(harvest.quantity_kg) if harvest else None},
                )
            )
            for b in self._repo.batches_for_item(item.id):
                hub = self._repo.hub(b.hub_id)
                steps.append(
                    TraceStep(
                        step="collection_batch",
                        at=b.received_at,
                        data_kind=DataKind.MEASURED,
                        detail={"code": b.code, "hub": hub.name if hub else None, "received_kg": float(b.received_kg)},
                    )
                )
                q = self._repo.quality(b.id)
                steps.append(
                    TraceStep(
                        step="quality",
                        at=q.checked_at if q else None,
                        data_kind=DataKind.MEASURED if q else "pending",
                        detail={
                            "batch": b.code,
                            "grade": q.grade.value if q and q.grade else None,
                            "result": q.result.value if q else None,
                            "accepted_kg": _f(q.accepted_kg) if q else None,
                            "rejected_kg": _f(q.rejected_kg) if q else None,
                        },
                    )
                )
            steps.append(
                TraceStep(
                    step="fulfilment",
                    at=None,
                    data_kind=DataKind.MEASURED if item.status is OrderItemStatus.FULFILLED else "pending",
                    detail={"fulfilled_kg": float(item.fulfilled_kg), "item_status": item.status.value},
                )
            )
            feedback = self._repo.feedback_for_cycle(cycle.id)
            if feedback:
                steps.append(
                    TraceStep(
                        step="prediction_feedback",
                        at=None,
                        data_kind=DataKind.MEASURED,
                        detail={
                            "versions": [
                                {
                                    "version": v,
                                    "abs_pct_error": _f(f.abs_pct_error),
                                    "within_p10_p90": f.within_interval,
                                }
                                for v, f in feedback
                            ]
                        },
                    )
                )
            items.append(TraceItem(order_item_id=item.id, farm_ref=_ref(farm.id), status=item.status, steps=steps))
        return OrderTrace(
            order_id=order.id,
            order_status=order.status,
            crop_name=crop.name if crop else "",
            ordered_kg=order.ordered_kg,
            fulfilled_kg=order.fulfilled_kg,
            pool={
                "id": str(pool.id),
                "status": pool.status.value,
                "algorithm": pool.algorithm.value,
                "demand_kg": float(pool.demand_kg),
                "allocated_kg": float(pool.allocated_kg),
                "shortage_kg": float(pool.shortage_kg),
                "closed": pool.closed_at is not None,
            },
            reallocations=[
                {
                    "trigger": e.trigger,
                    "outcome": e.outcome.value,
                    "shortage_kg": float(e.shortage_kg),
                    "replaced_kg": float(e.replaced_kg),
                    "unresolved_kg": float(e.unresolved_kg),
                    "reason": e.reason,
                    "at": e.created_at.isoformat(),
                }
                for e in self._pool_repo.events(pool.id)
            ],
            items=items,
        )

    def batch_trace(self, user: CurrentUser, code: str) -> BatchTrace:
        batch = self._repo.batch_by_code(code)
        if batch is None:
            raise NotFoundError("Batch not found")
        item = self._repo.item(batch.order_item_id)
        assert item is not None
        order = self._repo.order(item.order_id)
        assert order is not None
        lot, cycle, farm = self._repo.lot_context(item.lot_id)
        allowed = user.role is UserRole.ADMIN or user.user_id in (order.buyer_id, lot.owner_id)
        if not allowed:
            raise NotFoundError("Batch not found")
        harvest = self._repo.harvest_for_cycle(cycle.id)
        preds = self._repo.predictions(cycle.id)
        last = preds[-1] if preds else None
        crop = self._session.get(Crop, cycle.crop_id)
        return BatchTrace(
            batch=self._batch_out(batch),
            order_id=order.id,
            order_status=order.status,
            pool_id=order.pool_id,
            crop_name=crop.name if crop else "",
            farm_ref=_ref(farm.id),
            allocation_kg=item.quantity_kg,
            harvest={
                "quantity_kg": _f(harvest.quantity_kg) if harvest else None,
                "start_date": harvest.harvest_start_date.isoformat() if harvest else None,
                "data_kind": "measured",
            },
            prediction={
                "version": last.version,
                "p10_kg": _f(last.p10_kg),
                "p50_kg": _f(last.p50_kg),
                "p90_kg": _f(last.p90_kg),
                "data_kind": "estimate",
            }
            if last
            else None,
        )

    # ================================================================= market

    def supply_summary(self) -> list[SupplySummary]:
        rows = self._repo.supply_summary()
        return [
            SupplySummary(
                crop_id=a, crop_name=b, lots=c, available_kg=d, earliest_harvest_start=e, latest_harvest_end=f
            )
            for a, b, c, d, e, f in rows
        ]

    def search(
        self,
        crop_id: uuid.UUID,
        quantity_kg: Decimal,
        window_start: date,
        window_end: date,
        min_grade: QualityGrade,
        latitude: Decimal | None,
        longitude: Decimal | None,
        max_distance_km: Decimal | None,
    ) -> MatchesOut:
        if window_end < window_start:
            raise DomainValidationError("window_end must not be before window_start", code="window_order")
        if (latitude is None) != (longitude is None):
            raise DomainValidationError("latitude and longitude must be provided together", code="coordinates_paired")
        spec = DemandSpec(
            str(crop_id),
            quantity_kg,
            window_start,
            window_end,
            min_grade,
            ZERO,
            Decimal(100),
            latitude,
            longitude,
            max_distance_km,
        )
        return self._pools.search(spec)

    def opportunities(self, farmer_id: uuid.UUID) -> list[Opportunity]:
        out = []
        for demand, crop_name, n in self._repo.open_demands_for_farmer(farmer_id):
            profile = self._session.query(BuyerProfile).filter(BuyerProfile.user_id == demand.buyer_id).one_or_none()
            out.append(
                Opportunity(
                    demand_id=demand.id,
                    crop_id=demand.crop_id,
                    crop_name=crop_name,
                    quantity_kg=demand.quantity_kg,
                    window_start=demand.window_start,
                    window_end=demand.window_end,
                    min_grade=demand.min_grade,
                    buyer_type=profile.buyer_type if profile else BuyerType.OTHER,
                    pooled=demand.status.value == "pooled",
                    my_matching_cycles=n,
                )
            )
        return out

    # ================================================================ helpers

    def _new_item(self, order: BuyerOrder, alloc: HarvestAllocation) -> BuyerOrderItem:
        lot, _cycle, _farm = self._repo.lot_context(alloc.lot_id)
        part = FarmerParticipation(allocation_id=alloc.id, farmer_id=lot.owner_id, status=ParticipationStatus.PENDING)
        self._repo.add(part)
        item = BuyerOrderItem(
            order_id=order.id,
            allocation_id=alloc.id,
            lot_id=lot.id,
            farmer_id=lot.owner_id,
            participation_id=part.id,
            quantity_kg=alloc.quantity_kg,
            fulfilled_kg=ZERO,
            status=OrderItemStatus.AWAITING_FARMER,
        )
        self._repo.add(item)
        crop = self._session.get(Crop, self._repo.lot_context(lot.id)[1].crop_id)
        self._notifications.notify(
            lot.owner_id,
            NotificationCategory.PARTICIPATION_REQUEST,
            f"New order {_order_ref(order.id)}: {crop.name if crop else 'produce'}",
            f"Order {_order_ref(order.id)} asks for {_kg(alloc.quantity_kg)} kg of {crop.name if crop else 'produce'} "
            "from your predicted harvest. Open Market to accept or decline.",
            dedup_key=f"participation:{part.id}",
            data={"participation_id": part.id, "order_id": order.id},
        )
        return item

    def _refresh(self, order: BuyerOrder) -> None:
        self._session.flush()
        items = self._repo.items(order.id)
        order.status = order_status(
            order.status,
            [i.status for i in items],
            order.fulfilled_kg,
            order.ordered_kg,
            self._repo.any_batch(order.id),
            accepted_kg=order_quantities(
                ((i.status, i.quantity_kg) for i in items), order.fulfilled_kg, order.ordered_kg
            ).confirmed_kg,
        )
        self._session.flush()

    def _own_participation(
        self, farmer_id: uuid.UUID, participation_id: uuid.UUID
    ) -> tuple[FarmerParticipation, BuyerOrderItem, BuyerOrder]:
        part = self._repo.participation(participation_id)
        if part is None or part.farmer_id != farmer_id:
            raise NotFoundError("Participation request not found")
        item = self._repo.item_for_participation(part.id)
        assert item is not None
        order = self._repo.order(item.order_id, lock=True)  # lock order first (order -> pool -> lots)
        assert order is not None
        self._session.refresh(part)
        self._session.refresh(item)
        if order.status is OrderStatus.CANCELLED:
            raise ConflictError("This order was cancelled", code="order_closed")
        return part, item, order

    def _visible_order(self, user: CurrentUser, order_id: uuid.UUID) -> BuyerOrder:
        order = self._repo.order(order_id)
        if order is None or (user.role is not UserRole.ADMIN and order.buyer_id != user.user_id):
            raise NotFoundError("Order not found")
        return order

    def _active_hub(self, hub_id: uuid.UUID) -> CollectionHub:
        hub = self._repo.hub(hub_id)
        if hub is None or not hub.is_active:
            raise DomainValidationError(
                "Collection hub not found or inactive", code="hub_not_found", details={"field": "hub_id"}
            )
        return hub

    def _demand_for_order(self, order_id: uuid.UUID) -> BuyerDemand:
        order = self._repo.order(order_id)
        assert order is not None
        pool = self._session.get(HarvestPool, order.pool_id)
        assert pool is not None
        demand = self._session.get(BuyerDemand, pool.demand_id)
        assert demand is not None
        return demand

    def _item_crop(self, item: BuyerOrderItem) -> str:
        crop = self._session.get(Crop, self._repo.lot_context(item.lot_id)[1].crop_id)
        return crop.name if crop else "produce"

    def _farm_ref(self, item: BuyerOrderItem) -> str:
        return _ref(self._repo.lot_context(item.lot_id)[2].id)

    def _notify_farmer(
        self,
        item: BuyerOrderItem,
        title: str,
        body: str,
        key: str,
        *,
        category: NotificationCategory = NotificationCategory.ORDER_UPDATE,
    ) -> None:
        cat = NotificationCategory.COLLECTION if key.startswith("batch:") else category
        self._notifications.notify(
            item.farmer_id,
            cat,
            title,
            body,
            dedup_key=key,
            data={"order_item_id": item.id, "participation_id": item.participation_id},
        )

    def _order_out(self, order: BuyerOrder) -> OrderOut:
        pool = self._pool_repo.pool(order.pool_id)
        assert pool is not None
        demand = self._session.get(BuyerDemand, pool.demand_id)
        assert demand is not None
        crop = self._session.get(Crop, demand.crop_id)
        items = self._repo.items(order.id)
        out_items = []
        for i in items:
            part = self._repo.participation(i.participation_id)
            assert part is not None
            out_items.append(
                OrderItemOut(
                    id=i.id,
                    allocation_id=i.allocation_id,
                    lot_id=i.lot_id,
                    farm_ref=self._farm_ref(i),
                    quantity_kg=i.quantity_kg,
                    fulfilled_kg=i.fulfilled_kg,
                    status=i.status,
                    participation_status=part.status,
                    farmer_progress=part.progress,
                )
            )
        committed = sum((i.quantity_kg for i in items if i.status in OPEN_ITEMS), ZERO) + order.fulfilled_kg
        quantities = order_quantities(((i.status, i.quantity_kg) for i in items), order.fulfilled_kg, order.ordered_kg)
        return OrderOut(
            id=order.id,
            pool_id=pool.id,
            status=order.status,
            crop_name=crop.name if crop else "",
            ordered_kg=order.ordered_kg,
            committed_kg=committed,
            confirmed_kg=quantities.confirmed_kg,
            awaiting_kg=quantities.awaiting_kg,
            uncovered_kg=quantities.uncovered_kg,
            fulfilled_kg=order.fulfilled_kg,
            pool_status=pool.status,
            pool_shortage_kg=pool.shortage_kg,
            delivery_hub_id=order.delivery_hub_id,
            window_start=demand.window_start,
            window_end=demand.window_end,
            notes=order.notes,
            items=out_items,
            created_at=order.created_at,
            updated_at=order.updated_at,
        )

    def _participation_out(self, part: FarmerParticipation) -> ParticipationOut:
        item = self._repo.item_for_participation(part.id)
        assert item is not None
        order = self._repo.order(item.order_id)
        assert order is not None
        demand = self._demand_for_order(order.id)
        crop = self._session.get(Crop, demand.crop_id)
        lot, cycle, _farm = self._repo.lot_context(item.lot_id)
        profile = self._session.query(BuyerProfile).filter(BuyerProfile.user_id == order.buyer_id).one_or_none()
        return ParticipationOut(
            id=part.id,
            status=part.status,
            order_id=order.id,
            order_status=order.status,
            order_item_id=item.id,
            item_status=item.status,
            lot_id=lot.id,
            crop_cycle_id=cycle.id,
            crop_name=crop.name if crop else "",
            quantity_kg=item.quantity_kg,
            fulfilled_kg=item.fulfilled_kg,
            window_start=demand.window_start,
            window_end=demand.window_end,
            min_grade=demand.min_grade,
            buyer_business=profile.business_name if profile else "Buyer",
            buyer_type=profile.buyer_type if profile else BuyerType.OTHER,
            delivery_hub_id=order.delivery_hub_id,
            responded_at=part.responded_at,
            reason=part.reason,
            progress=part.progress,
            progress_at=part.progress_at,
            created_at=part.created_at,
        )

    def _batch_out(self, batch: ProduceBatch) -> BatchOut:
        item = self._repo.item(batch.order_item_id)
        assert item is not None
        hub = self._repo.hub(batch.hub_id)
        q = self._repo.quality(batch.id)
        return BatchOut(
            id=batch.id,
            code=batch.code,
            order_item_id=item.id,
            order_id=item.order_id,
            lot_id=batch.lot_id,
            hub_id=batch.hub_id,
            hub_name=hub.name if hub else "",
            received_kg=batch.received_kg,
            received_at=batch.received_at,
            status=batch.status,
            notes=batch.notes,
            quality=QualityOut.model_validate(q) if q else None,
        )


def _f(x: Decimal | None) -> float | None:
    return None if x is None else float(x)
