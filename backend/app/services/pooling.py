"""Dynamic Predictive Harvest Pooling and Dynamic Reallocation (use cases).

Concurrency: every operation locks rows in a fixed order (pool or demand row first, then all lots of the crop
in id order), so two operations on overlapping supply serialise instead of over-committing or deadlocking.
Supply is reserved only through the Phase 4 inventory (p10-based, no negatives, unique booking keys).
Atomicity: each pool creation or rebalance commits once; any failure rolls the whole operation back.
Idempotency: pool creation by (buyer, Idempotency-Key); rebalances by their event key.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.enums import (
    AllocationStatus,
    DemandStatus,
    LotStatus,
    PoolStatus,
    QualityGrade,
    ReallocationOutcome,
    ReservationStatus,
    UserRole,
)
from app.core.errors import ConflictError, DomainValidationError, NotFoundError, PermissionDeniedError
from app.domain.inventory import InventoryError
from app.domain.pooling.matching import evaluate, rank, summarize
from app.domain.pooling.models import DemandSpec, Match, MatchSummary, Plan, Supply, Weights
from app.domain.pooling.optimizer import allocate
from app.domain.pooling.shortage import Commitment, assign_shortfall, demand_stage, lot_shortfall, pool_status
from app.models.crop import Crop, CropCycle
from app.models.farm import Farm
from app.models.intelligence import InventoryLot, InventoryReservation
from app.models.pooling import (
    AllocationLedger,
    BuyerDemand,
    HarvestAllocation,
    HarvestPool,
    HarvestPoolMember,
    ReallocationEvent,
)
from app.repositories.pooling import PoolingRepository
from app.schemas.auth import CurrentUser
from app.schemas.common import Page
from app.schemas.intelligence import LotOut
from app.schemas.pooling import (
    AllocationOut,
    DemandCreate,
    DemandOut,
    EventOut,
    LedgerOut,
    LotUpdate,
    MatchesOut,
    MatchOut,
    PoolCreate,
    PoolOut,
)
from app.services._common import to_jsonable
from app.services.inventory import InventoryService

logger = logging.getLogger(__name__)
ZERO = Decimal(0)
POOL_KEY_PREFIX = "pool:"


class PoolService:
    def __init__(
        self,
        *,
        session: Session,
        repo: PoolingRepository,
        inventory: InventoryService,
        clock: Clock,
        after_change: Callable[[uuid.UUID, EventOut], object] | None = None,
        on_demand_created: Callable[[BuyerDemand], object] | None = None,
    ) -> None:
        self._after_change = after_change
        self._on_demand_created = on_demand_created
        self._session = session
        self._repo = repo
        self._inventory = inventory
        self._clock = clock

    # ================================================================ demands

    def set_hooks(
        self,
        *,
        after_change: Callable[[uuid.UUID, EventOut], object] | None,
        on_demand_created: Callable[[BuyerDemand], object] | None,
    ) -> None:
        self._after_change = after_change
        self._on_demand_created = on_demand_created

    def create_demand(self, buyer_id: uuid.UUID, payload: DemandCreate) -> DemandOut:
        crop = self._session.get(Crop, payload.crop_id)
        if crop is None or not crop.is_active:
            raise DomainValidationError(
                "Crop not found in the catalog", code="crop_not_found", details={"field": "crop_id"}
            )
        demand = BuyerDemand(buyer_id=buyer_id, **payload.model_dump())
        self._repo.add(demand)
        if self._on_demand_created is not None:
            self._on_demand_created(demand)  # buyer-opportunity notifications, same transaction
        self._session.flush()
        out = self._demand_out(demand)  # includes the live matching result (nothing is reserved)
        self._session.commit()
        return out

    def search(self, spec: DemandSpec) -> MatchesOut:
        """Future-harvest search without creating a demand: eligible, ranked, p10-based supply (default weights)."""
        ranked = rank(
            [s for _, s in self._supplies(uuid.UUID(spec.crop_id), lock=False)], spec, spec.quantity_kg, Weights()
        )
        eligible = [m for m in ranked if m.eligible]
        summary = summarize(spec.quantity_kg, ranked, crop=self._crop_name(uuid.UUID(spec.crop_id)))
        self._session.commit()  # lot re-syncs only
        return MatchesOut(
            demand_id=None,
            need_kg=spec.quantity_kg,
            eligible_supply_kg=summary.eligible_kg,
            shortfall_kg=summary.shortage_kg,
            matches=[self._match_out(m) for m in eligible],
            note=(
                "Only lots their farmers opted into pooling are shown, under pseudonymous references. Quantities are "
                "p10 (pessimistic) predictions net of existing commitments: estimates, not guarantees."
            ),
            **self._summary_fields(summary),
        )

    def list_demands(self, buyer_id: uuid.UUID, *, limit: int, offset: int) -> Page[DemandOut]:
        rows, total = self._repo.demands(buyer_id, limit=limit, offset=offset)
        items = [self._demand_out(r) for r in rows]
        self._session.commit()  # lot re-syncs only
        return Page[DemandOut](items=items, total=total, limit=limit, offset=offset)

    def get_demand(self, buyer_id: uuid.UUID, demand_id: uuid.UUID) -> DemandOut:
        out = self._demand_out(self._demand(buyer_id, demand_id))
        self._session.commit()  # lot re-syncs only
        return out

    def cancel_demand(self, buyer_id: uuid.UUID, demand_id: uuid.UUID) -> DemandOut:
        """Withdraw a demand that has no pool yet (repeating it is harmless). A pooled demand ends by cancelling its
        order, which releases the farms' reserved supply properly."""
        demand = self._demand(buyer_id, demand_id, lock=True)
        if demand.status is DemandStatus.POOLED:
            raise ConflictError(
                "This demand already has a harvest pool. Cancel its order instead (Orders > open the order > Cancel).",
                code="demand_pooled",
            )
        demand.status = DemandStatus.CANCELLED
        self._session.commit()
        return self._demand_out(demand)

    def matches(self, buyer_id: uuid.UUID, demand_id: uuid.UUID) -> MatchesOut:
        demand = self._demand(buyer_id, demand_id)
        pool = self._repo.pool_for_demand(demand.id)
        need = demand.quantity_kg - (pool.allocated_kg if pool else ZERO)
        ranked = rank(
            [s for _, s in self._supplies(demand.crop_id, lock=False)],
            self._spec(demand),
            max(need, Decimal("0.001")),
            Weights(),
        )
        summary = summarize(max(need, ZERO), ranked, crop=self._crop_name(demand.crop_id))
        self._session.commit()  # lot re-syncs only
        return MatchesOut(
            demand_id=demand.id,
            need_kg=need,
            eligible_supply_kg=summary.eligible_kg,
            shortfall_kg=summary.shortage_kg,
            matches=[self._match_out(m) for m in ranked],
            note=(
                "Ranked by the allocation score; ineligible lots are listed with the reasons. "
                "Quantities are p10-based (pessimistic)."
                + (" Need is the quantity the pool has not covered yet." if pool else "")
            ),
            **self._summary_fields(summary),
        )

    # ================================================================== pools

    def create_pool(
        self, buyer_id: uuid.UUID, demand_id: uuid.UUID, payload: PoolCreate, idempotency_key: str | None
    ) -> PoolOut:
        demand = self._demand(buyer_id, demand_id, lock=True)
        existing = self._repo.pool_for_demand(demand.id)
        if existing is not None:
            if idempotency_key and existing.idempotency_key == idempotency_key:
                return self._pool_out(existing)  # safe retry
            raise ConflictError(
                "This demand already has a pool", code="pool_exists", details={"pool_id": str(existing.id)}
            )
        if demand.status is DemandStatus.CANCELLED:
            raise ConflictError("This demand is cancelled", code="demand_cancelled")
        weights = Weights(**payload.weights.model_dump())
        try:
            lots = {str(lot.id): lot for lot, _ in self._supplies(demand.crop_id, lock=True)}
            pool = HarvestPool(
                demand_id=demand.id,
                buyer_id=buyer_id,
                status=PoolStatus.UNFILLED,
                algorithm=payload.algorithm,
                demand_kg=demand.quantity_kg,
                allocated_kg=ZERO,
                shortage_kg=ZERO,
                max_pool_risk=payload.max_pool_risk,
                max_share=payload.max_share,
                weights=to_jsonable(weights),
                idempotency_key=idempotency_key,
            )
            self._repo.add(pool)
            plan, matches = self._plan(pool, demand, demand.quantity_kg)
            self._apply(
                pool, plan, matches, lots, "allocated", "Initial allocation by the pool's algorithm.", None, buyer_id
            )
            self._finish(pool)
            demand.status = DemandStatus.POOLED
            self._session.commit()
        except BaseException:
            self._session.rollback()
            raise
        return self._pool_out(pool, plan.notes)

    def list_pools(self, user: CurrentUser, *, limit: int, offset: int) -> Page[PoolOut]:
        buyer = None if user.role is UserRole.ADMIN else user.user_id
        rows, total = self._repo.pools(buyer, limit=limit, offset=offset)
        return Page[PoolOut](items=[self._pool_out(p) for p in rows], total=total, limit=limit, offset=offset)

    def get_pool(self, user: CurrentUser, pool_id: uuid.UUID) -> PoolOut:
        return self._pool_out(self._visible_pool(user, pool_id))

    def events(self, user: CurrentUser, pool_id: uuid.UUID) -> list[EventOut]:
        return [EventOut.model_validate(e) for e in self._repo.events(self._visible_pool(user, pool_id).id)]

    def ledger(self, user: CurrentUser, pool_id: uuid.UUID) -> list[LedgerOut]:
        return [LedgerOut.model_validate(r) for r in self._repo.ledger(self._visible_pool(user, pool_id).id)]

    # ============================================================ reallocation

    def rebalance(self, user: CurrentUser, pool_id: uuid.UUID, idempotency_key: str) -> EventOut:
        self._visible_pool(user, pool_id)
        return self._rebalance(pool_id, "manual", None, f"manual:{pool_id}:{idempotency_key}", user.user_id)

    def on_lot_changed(self, lot_id: uuid.UUID, trigger_ref: str) -> list[EventOut]:
        """Called after a prediction or harvest changes a lot. Each pool is rebalanced in its own savepoint:
        a failure leaves that pool exactly as it was (logged) without undoing the prediction."""
        out: list[EventOut] = []
        using = self._repo.pools_using_lot(lot_id)
        for pool_id in using:
            try:
                out.append(self._rebalance(pool_id, "prediction_change", trigger_ref, f"{trigger_ref}:{pool_id}", None))
            except Exception:
                self._session.rollback()
                logger.exception("automatic reallocation failed for pool %s (left unchanged)", pool_id)
        return out + self.offer_new_supply(lot_id, trigger_ref, skip=set(using))

    def offer_new_supply(self, lot_id: uuid.UUID, trigger_ref: str, *, skip: set[uuid.UUID]) -> list[EventOut]:
        """Buyer-first matching: supply that appears (new or higher prediction, opt-in) after a demand was pooled
        short is offered to the open short pools of the same crop that it is eligible for, oldest pool first.
        Each top-up is an ordinary rebalance (own transaction, idempotent key, audited); the farmer still accepts or
        declines the resulting order item, so nothing is confirmed on their behalf."""
        out: list[EventOut] = []
        lot = self._session.get(InventoryLot, lot_id)
        if lot is None or not lot.pool_eligible:
            return out
        cycle = self._session.get(CropCycle, lot.crop_cycle_id)
        assert cycle is not None
        for pool_id in self._repo.short_pools_for_crop(cycle.crop_id, lot_id):
            if pool_id in skip:
                continue
            self._session.refresh(lot)
            if lot.available_kg <= 0:
                break
            pool = self._repo.pool(pool_id)
            demand = self._session.get(BuyerDemand, pool.demand_id) if pool else None
            if pool is None or demand is None:
                continue
            supply = next((s for _, s in self._supplies(cycle.crop_id, lock=False) if s.lot_id == str(lot_id)), None)
            need = pool.demand_kg - pool.allocated_kg
            self._session.commit()  # lot re-syncs only
            if supply is None or not evaluate(supply, self._spec(demand), need, Weights()).eligible:
                continue  # this pool cannot use the lot (dates, grade, distance, ...): no event
            try:
                out.append(self._rebalance(pool_id, "supply_added", str(lot_id), f"{trigger_ref}:{pool_id}", None))
            except Exception:
                self._session.rollback()
                logger.exception("automatic top-up failed for pool %s (left unchanged)", pool_id)
        return out

    # ===================================================== order integration

    def close_pool(self, pool_id: uuid.UUID, reason: str, actor: uuid.UUID | None, *, release: bool) -> None:
        """Close a pool so it is never rebalanced again; with `release`, every open allocation is released and its
        supply returned to the farmers' lots (ledger action "released"). Does NOT commit (caller's transaction)."""
        pool = self._repo.pool(pool_id, lock=True)
        assert pool is not None
        demand = self._session.get(BuyerDemand, pool.demand_id)
        assert demand is not None
        lots = {str(lot.id): lot for lot, _ in self._supplies(demand.crop_id, lock=True)}
        if release:
            for alloc in self._repo.allocations(pool.id):
                if alloc.quantity_kg > 0 and alloc.status is not AllocationStatus.FULFILLED:
                    lot = lots[str(alloc.lot_id)]
                    self._set_quantity(pool, alloc, lot, ZERO, "released", f"Pool closed: {reason}", None, actor)
            if demand.status is not DemandStatus.CANCELLED:
                demand.status = DemandStatus.CANCELLED
        pool.closed_at = self._clock.now()
        pool.close_reason = reason[:80]
        pool.shortage_kg = ZERO if release else pool.shortage_kg
        self._finish(pool)

    def fulfil_allocation(
        self, pool_id: uuid.UUID, allocation_id: uuid.UUID, fulfil_kg: Decimal, actor: uuid.UUID | None
    ) -> None:
        """Turn an allocation's reservation into a FULFILLED one of `fulfil_kg` (<= the allocation; measured, quality
        accepted). 0 releases it. Uses the inventory's fulfil rule (only after a measured harvest). No commit."""
        pool = self._repo.pool(pool_id, lock=True)
        assert pool is not None
        demand = self._session.get(BuyerDemand, pool.demand_id)
        assert demand is not None
        lots = {str(lot.id): lot for lot, _ in self._supplies(demand.crop_id, lock=True)}
        alloc = next((a for a in self._repo.allocations(pool.id) if a.id == allocation_id), None)
        if alloc is None:
            raise NotFoundError("Allocation not found")
        if alloc.status is AllocationStatus.FULFILLED:
            raise ConflictError("This allocation is already fulfilled", code="already_fulfilled")
        if fulfil_kg < 0 or fulfil_kg > alloc.quantity_kg:
            raise DomainValidationError("Fulfilled quantity must be between 0 and the allocated quantity")
        lot = lots[str(alloc.lot_id)]
        old_qty = alloc.quantity_kg
        if fulfil_kg < old_qty:  # deliver less than committed: shrink (or release) first, audited
            self._set_quantity(
                pool, alloc, lot, fulfil_kg, "reduced", "Quality-accepted quantity below the allocation.", None, actor
            )
        if fulfil_kg > 0:
            row = self._session.get(InventoryReservation, alloc.reservation_id) if alloc.reservation_id else None
            if row is None:
                raise ConflictError("The allocation has no active reservation", code="reservation_not_active")
            try:
                self._inventory.fulfil_locked(row, lot)
            except InventoryError as exc:
                raise ConflictError(exc.message, code=exc.code) from exc
            alloc.status = AllocationStatus.FULFILLED
            self._repo.add(
                AllocationLedger(
                    pool_id=pool.id,
                    allocation_id=alloc.id,
                    lot_id=lot.id,
                    action="fulfilled",
                    quantity_before=fulfil_kg,
                    quantity_after=fulfil_kg,
                    reason="Delivered and accepted at quality check (measured).",
                    reallocation_event_id=None,
                    actor_id=actor,
                )
            )
        self._finish(pool)

    def withdraw_lot(self, pool_id: uuid.UUID, lot_id: uuid.UUID, reason: str, actor: uuid.UUID, key: str) -> EventOut:
        """A farmer declined to supply this pool: release the lot's allocation, exclude the lot from this pool and
        reallocate the lost quantity, all in ONE transaction (the Phase 5 reallocation steps)."""
        return self._rebalance(pool_id, "farmer_declined", str(lot_id), key, actor, withdraw=(lot_id, reason))

    def _rebalance(
        self,
        pool_id: uuid.UUID,
        trigger: str,
        trigger_ref: str | None,
        key: str,
        actor: uuid.UUID | None,
        withdraw: tuple[uuid.UUID, str] | None = None,
    ) -> EventOut:
        done = self._repo.event_by_key(key)
        if done is not None:
            return EventOut.model_validate(done)  # idempotent replay: nothing changes
        current = self._repo.pool(pool_id)
        if current is not None and current.closed_at is not None:
            raise ConflictError("This pool is closed (its order was cancelled or completed)", code="pool_closed")
        out = self._rebalance_once(pool_id, trigger, trigger_ref, key, actor, withdraw)
        if self._after_change is not None:
            self._after_change(pool_id, out)  # runs after commit: orders, notifications
        return out

    def _rebalance_once(
        self,
        pool_id: uuid.UUID,
        trigger: str,
        trigger_ref: str | None,
        key: str,
        actor: uuid.UUID | None,
        withdraw: tuple[uuid.UUID, str] | None,
    ) -> EventOut:
        try:
            started = time.perf_counter()
            pool = self._repo.pool(pool_id, lock=True)
            assert pool is not None
            demand = self._session.get(BuyerDemand, pool.demand_id)
            assert demand is not None
            lots = {str(lot.id): lot for lot, _ in self._supplies(demand.crop_id, lock=True)}
            before = self._snapshot(pool)
            event = ReallocationEvent(
                pool_id=pool.id,
                trigger=trigger,
                trigger_ref=trigger_ref,
                idempotency_key=key,
                outcome=ReallocationOutcome.NO_CHANGE,
                algorithm=pool.algorithm.value,
                shortage_kg=ZERO,
                replaced_kg=ZERO,
                unresolved_kg=ZERO,
                topped_up_kg=ZERO,
                steps=0,
                duration_ms=0,
                reason="",
                before=before,
                after={},
            )
            self._repo.add(event)

            # 1-3. detect affected lots, the exact shortage, and the affected reservations (newest first)
            shortage, steps, causes = ZERO, 0, []
            if withdraw is not None:  # a farmer declined: their whole allocation becomes the shortage
                lot_id, why = withdraw
                member = self._repo.member(pool.id, lot_id)
                alloc = next((a for a in self._repo.allocations(pool.id) if a.lot_id == lot_id), None)
                if member is None or alloc is None:
                    raise NotFoundError("This farm lot does not supply the pool")
                member.excluded = True
                if alloc.quantity_kg > 0:
                    lost = alloc.quantity_kg
                    lot = lots[str(lot_id)]
                    self._set_quantity(pool, alloc, lot, ZERO, "released", f"Farmer declined: {why}", event.id, actor)
                    causes.append(f"lot {str(lot_id)[:8]}: farmer declined to supply {lost} kg")
                    shortage += lost
                    steps += 1
            for alloc in self._repo.allocations(pool.id):
                if alloc.quantity_kg <= 0 or alloc.reservation_id is None:
                    continue
                lot = lots[str(alloc.lot_id)]
                commitments = self._commitments(lot)
                deficit = lot_shortfall(lot.committable_kg, commitments)
                if deficit <= 0:
                    continue
                cut = assign_shortfall(deficit, commitments).cuts.get(str(alloc.reservation_id), ZERO)
                if cut <= 0:
                    continue
                causes.append(
                    f"lot {str(lot.id)[:8]}: can now promise {lot.committable_kg} kg but "
                    f"{lot.committable_kg + deficit} kg was committed; this pool loses {cut} kg"
                )
                self._set_quantity(
                    pool,
                    alloc,
                    lot,
                    alloc.quantity_kg - cut,
                    "reduced",
                    f"Supply prediction fell ({lot.basis}).",
                    event.id,
                    actor,
                )
                shortage += cut
                steps += 1

            # 4-6. find, rank and allocate eligible replacement supply for everything still missing
            allocated = self._repo.allocated_total(self._repo.allocations(pool.id))
            need = pool.demand_kg - allocated
            added = ZERO
            notes: tuple[str, ...] = ()
            if need > 0:
                plan, matches = self._plan(pool, demand, need)
                notes = plan.notes
                action = "replacement_added" if shortage > 0 else "topped_up"
                added = self._apply(
                    pool,
                    plan,
                    matches,
                    lots,
                    action,
                    "Replacement for a supply shortage." if shortage > 0 else "Unfilled demand topped up.",
                    event.id,
                    actor,
                )
                steps += len(plan.lines)

            # 7. update pool, risk and status
            replaced = min(added, shortage)
            topped = added - replaced
            pool.shortage_kg = min(
                pool.demand_kg - self._repo.allocated_total(self._repo.allocations(pool.id)),
                max(ZERO, pool.shortage_kg + shortage - added),
            )
            self._finish(pool)

            # 8-9. event + audit with reason and before/after
            event.shortage_kg, event.replaced_kg, event.topped_up_kg = shortage, replaced, topped
            event.unresolved_kg = shortage - replaced
            if shortage == 0:
                event.outcome = ReallocationOutcome.TOP_UP if added > 0 else ReallocationOutcome.NO_CHANGE
            elif replaced >= shortage:
                event.outcome = ReallocationOutcome.FULL
            else:
                event.outcome = ReallocationOutcome.PARTIAL if replaced > 0 else ReallocationOutcome.NONE
            event.steps = steps
            event.reason = (
                ("; ".join(causes) + ". " if causes else "No supply shortage detected. ")
                + f"Shortage {shortage} kg; replaced {replaced} kg; "
                + f"unresolved {event.unresolved_kg} kg; topped up {topped} kg. "
                + " ".join(notes)
            ).strip()
            event.after = self._snapshot(pool)
            event.duration_ms = int((time.perf_counter() - started) * 1000)
            self._session.flush()
            self._session.commit()
            return EventOut.model_validate(event)
        except BaseException:
            self._session.rollback()
            raise

    # ============================================================= farmer side

    def update_lot(self, owner_id: uuid.UUID, lot_id: uuid.UUID, payload: LotUpdate) -> LotOut:
        lot = self._session.get(InventoryLot, lot_id)
        if lot is None or lot.owner_id != owner_id:
            raise NotFoundError("Inventory lot not found")
        before = (lot.pool_eligible, lot.expected_grade)
        changes = payload.model_dump(exclude_unset=True)
        graded = self._graded(lot)
        if graded is not None and changes.get("expected_grade") not in (None, graded):
            raise ConflictError(
                f"This harvest was graded {graded.value} from its quality checks. Change the grade on the crop's "
                "'Produce quality grade' screen instead.",
                code="grade_set_by_grading",
            )
        for k, v in changes.items():
            if v is None:
                raise DomainValidationError(f"{k} cannot be null", code="null_not_allowed", details={"field": k})
            setattr(lot, k, v)
        self._session.commit()
        if lot.pool_eligible and (lot.pool_eligible, lot.expected_grade) != before:
            # newly offered (or regraded): short pools of this crop may now use it; a repeated PATCH changes nothing
            self.offer_new_supply(lot.id, f"lot:{lot.id}:{uuid.uuid4().hex[:12]}", skip=set())
            self._session.refresh(lot)
        return self._inventory.lot_out(lot)

    # =============================================================== internals

    def _graded(self, lot: InventoryLot) -> QualityGrade | None:
        """The confirmed quality grade of the lot's recorded harvest, if the farmer graded it."""
        from app.models.intelligence import HarvestActual, ProduceGrading

        stmt = (
            select(ProduceGrading.grade)
            .join(HarvestActual, HarvestActual.id == ProduceGrading.harvest_actual_id)
            .where(HarvestActual.crop_cycle_id == lot.crop_cycle_id, ProduceGrading.grade.is_not(None))
        )
        return self._session.scalar(stmt)

    def _demand_out(self, demand: BuyerDemand) -> DemandOut:
        """The demand with one buyer-facing stage and its quantities. Pooled: reserved and still uncovered kg.
        Open: live matching against current eligible supply (nothing reserved). Caller commits (lot re-syncs)."""
        update: dict[str, Any] = {"crop_name": self._crop_name(demand.crop_id)}
        pool = self._repo.pool_for_demand(demand.id)
        order = self._repo.order_for_pool(pool.id) if pool else None
        live: MatchSummary | None = None
        if pool is not None:
            update.update(
                pool_id=pool.id,
                allocated_kg=pool.allocated_kg,
                remaining_kg=max(ZERO, pool.demand_kg - pool.allocated_kg),
            )
        elif demand.status is DemandStatus.OPEN:
            supplies = [s for _, s in self._supplies(demand.crop_id, lock=False)]
            live = summarize(demand.quantity_kg, rank(supplies, self._spec(demand), demand.quantity_kg, Weights()))
            update.update(matched_kg=min(live.eligible_kg, demand.quantity_kg), shortage_kg=live.shortage_kg)
        if order is not None:
            update["order_id"] = order[0]
        update["stage"] = demand_stage(
            demand.status,
            pool.status if pool else None,
            order[1] if order else None,
            live.fulfilment if live else None,
        )
        return DemandOut.model_validate(demand).model_copy(update=update)

    def _crop_name(self, crop_id: uuid.UUID) -> str:
        crop = self._session.get(Crop, crop_id)
        return crop.name if crop else "this crop"

    @staticmethod
    def _summary_fields(s: MatchSummary) -> dict[str, Any]:
        return {
            "eligible_count": s.eligible_count,
            "fulfilment": s.fulfilment,
            "shortage_kg": s.shortage_kg,
            "excluded_reasons": dict(s.excluded),
            "explanation": list(s.explanation),
            "next_steps": list(s.next_steps),
        }

    def _demand(self, buyer_id: uuid.UUID, demand_id: uuid.UUID, *, lock: bool = False) -> BuyerDemand:
        demand = self._repo.demand_owned(demand_id, buyer_id, lock=lock)
        if demand is None:
            raise NotFoundError("Demand not found")
        return demand

    def _visible_pool(self, user: CurrentUser, pool_id: uuid.UUID) -> HarvestPool:
        pool = self._repo.pool(pool_id)
        if pool is None or (user.role is not UserRole.ADMIN and pool.buyer_id != user.user_id):
            raise NotFoundError("Pool not found")
        if user.role not in (UserRole.ADMIN, UserRole.BUYER):
            raise PermissionDeniedError("You do not have permission to perform this action")
        return pool

    @staticmethod
    def _spec(d: BuyerDemand) -> DemandSpec:
        return DemandSpec(
            str(d.crop_id),
            d.quantity_kg,
            d.window_start,
            d.window_end,
            d.min_grade,
            d.min_confidence,
            d.max_risk,
            d.latitude,
            d.longitude,
            d.max_distance_km,
        )

    def _supplies(self, crop_id: uuid.UUID, *, lock: bool) -> list[tuple[InventoryLot, Supply]]:
        out: list[tuple[InventoryLot, Supply]] = []
        reliability: dict[uuid.UUID, Decimal] = {}
        confirmed = self._repo.graded_cycle_ids(crop_id)
        for lot, cycle, farm in self._repo.lots_for_crop(crop_id, lock=lock):
            self._inventory.sync_lot(cycle, lot.owner_id)
            pred = self._repo.latest_prediction(cycle.id)
            if lot.owner_id not in reliability:
                hits, n = self._repo.reliability(lot.owner_id)
                reliability[lot.owner_id] = Decimal(hits + 1) / Decimal(n + 2)  # Laplace: no history -> 0.5
            graded = cycle.id in confirmed
            out.append((lot, self._supply(lot, cycle, farm, pred, reliability[lot.owner_id], graded)))
        self._session.flush()
        return out

    @staticmethod
    def _supply(
        lot: InventoryLot, cycle: CropCycle, farm: Farm, pred: Any, reliability: Decimal, graded: bool = False
    ) -> Supply:
        start = pred.harvest_start_p10 if pred else cycle.sowing_date
        end = pred.harvest_end_p90 if pred else cycle.sowing_date
        return Supply(
            lot_id=str(lot.id),
            farm_ref=str(farm.id)[:8],
            crop_id=str(cycle.crop_id),
            grade=lot.expected_grade,
            available_kg=lot.available_kg,
            p50_kg=lot.p50_kg,
            window_start=start,
            window_end=end,
            confidence=pred.confidence_score if pred else ZERO,
            risk=pred.risk_score if pred else None,
            reliability=reliability,
            latitude=farm.latitude,
            longitude=farm.longitude,
            opted_in=lot.pool_eligible,
            lot_open=pred is not None and lot.status in (LotStatus.OPEN, LotStatus.HARVESTED),
            grade_confirmed=graded,
        )

    def _plan(self, pool: HarvestPool, demand: BuyerDemand, need: Decimal) -> tuple[Plan, list[Match]]:
        excluded = self._repo.excluded_lots(pool.id)  # lots whose farmer declined, or already delivered
        supplies = [s for _, s in self._supplies(demand.crop_id, lock=False) if s.lot_id not in excluded]
        matches = rank(
            supplies, self._spec(demand), need, Weights(**{k: Decimal(str(v)) for k, v in pool.weights.items()})
        )
        plan = allocate(pool.algorithm.value, matches, need, max_pool_risk=pool.max_pool_risk, max_share=pool.max_share)
        return plan, matches

    def _apply(
        self,
        pool: HarvestPool,
        plan: Plan,
        matches: Sequence[Match],
        lots: dict[str, InventoryLot],
        action: str,
        reason: str,
        event_id: uuid.UUID | None,
        actor: uuid.UUID | None,
    ) -> Decimal:
        by_lot = {m.supply.lot_id: m for m in matches}
        existing = {str(a.lot_id): a for a in self._repo.allocations(pool.id)}
        added = ZERO
        for line in plan.lines:
            lot, match = lots[line.lot_id], by_lot[line.lot_id]
            member = self._repo.member(pool.id, lot.id)
            if member is None:
                member = HarvestPoolMember(
                    pool_id=pool.id, lot_id=lot.id, score=match.score, components=to_jsonable(match.components)
                )
                self._repo.add(member)
            else:
                member.score, member.components = match.score, to_jsonable(match.components)
            alloc = existing.get(line.lot_id)
            if alloc is None:
                alloc = HarvestAllocation(
                    pool_id=pool.id,
                    lot_id=lot.id,
                    member_id=member.id,
                    quantity_kg=ZERO,
                    status=AllocationStatus.ACTIVE,
                    risk_level="unknown",
                    reservation_seq=0,
                )
                self._repo.add(alloc)
            self._set_quantity(
                pool,
                alloc,
                lot,
                alloc.quantity_kg + line.quantity_kg,
                action,
                f"{reason} Score {match.score}.",
                event_id,
                actor,
            )
            added += line.quantity_kg
        return added

    def _set_quantity(
        self,
        pool: HarvestPool,
        alloc: HarvestAllocation,
        lot: InventoryLot,
        new_qty: Decimal,
        action: str,
        reason: str,
        event_id: uuid.UUID | None,
        actor: uuid.UUID | None,
    ) -> None:
        """Replace the allocation's reservation (release old, reserve new total) under the lot lock and log it."""
        old_qty = alloc.quantity_kg
        old = self._session.get(InventoryReservation, alloc.reservation_id) if alloc.reservation_id else None
        if old is not None and old.status is not ReservationStatus.ACTIVE:
            old = None
        try:
            if old is not None and 0 < new_qty < old_qty:
                # a pure reduction: shrink in place of re-reserving (cannot over-allocate; order-independent)
                alloc.reservation_seq += 1
                key = f"{POOL_KEY_PREFIX}{pool.id}:v{alloc.reservation_seq}"
                alloc.reservation_id = self._inventory.shrink_locked(
                    old, lot, new_qty, key, f"Harvest pool {pool.id}"
                ).id
            else:
                if old is not None:
                    self._inventory.release_locked(old, lot)
                alloc.reservation_id = None
                if new_qty > 0:
                    alloc.reservation_seq += 1
                    # booking key is unique per lot: "pool:<pool id>:v<n>" (~46 chars, column limit 80)
                    key = f"{POOL_KEY_PREFIX}{pool.id}:v{alloc.reservation_seq}"
                    alloc.reservation_id = self._inventory.reserve_locked(
                        lot, new_qty, key, f"Harvest pool {pool.id}"
                    ).id
        except InventoryError as exc:  # never expected: plans only use available supply
            raise ConflictError(exc.message, code=exc.code) from exc
        alloc.quantity_kg = new_qty
        alloc.status = (
            AllocationStatus.ACTIVE
            if new_qty >= old_qty and new_qty > 0
            else AllocationStatus.REDUCED
            if new_qty > 0
            else AllocationStatus.RELEASED
        )
        self._session.flush()
        self._repo.add(
            AllocationLedger(
                pool_id=pool.id,
                allocation_id=alloc.id,
                lot_id=lot.id,
                action=action if new_qty > 0 or action != "reduced" else "released",
                quantity_before=old_qty,
                quantity_after=new_qty,
                reason=reason,
                reallocation_event_id=event_id,
                actor_id=actor,
            )
        )

    def _commitments(self, lot: InventoryLot) -> list[Commitment]:
        """Active reservations ordered by when the commitment was ORIGINALLY made. A pool reservation is
        re-created when resized, so its own timestamp would wrongly make it look newest; the allocation's
        creation time is used instead (newest-first cutting then preserves older commitments)."""
        rows = self._repo.active_reservations(lot.id)
        first_made = self._repo.allocation_times([r.id for r in rows])
        ordered = sorted(rows, key=lambda r: (first_made.get(r.id, r.created_at), str(r.id)))
        return [
            Commitment(str(r.id), r.quantity_kg, i, r.booking_key.startswith(POOL_KEY_PREFIX))
            for i, r in enumerate(ordered)
        ]

    def _finish(self, pool: HarvestPool) -> None:
        allocs = self._repo.allocations(pool.id)
        pool.allocated_kg = self._repo.allocated_total(allocs)
        lots_at_risk = False
        for a in allocs:
            lot = self._session.get(InventoryLot, a.lot_id)
            pred = self._repo.latest_prediction(lot.crop_cycle_id) if lot else None
            a.risk_level = pred.risk_level if pred else "unknown"
            lots_at_risk = lots_at_risk or (a.quantity_kg > 0 and lot is not None and lot.status is LotStatus.AT_RISK)
        pool.status = pool_status(pool.demand_kg, pool.allocated_kg, pool.shortage_kg, lots_at_risk)
        self._session.flush()

    def _snapshot(self, pool: HarvestPool) -> dict[str, Any]:
        result: dict[str, Any] = to_jsonable(
            {
                "status": pool.status,
                "allocated_kg": pool.allocated_kg,
                "shortage_kg": pool.shortage_kg,
                "allocations": {str(a.lot_id): a.quantity_kg for a in self._repo.allocations(pool.id)},
            }
        )
        return result

    def _pool_out(self, pool: HarvestPool, notes: Sequence[str] = ()) -> PoolOut:
        scores = {}
        allocs = self._repo.allocations(pool.id)
        for a in allocs:
            m = self._repo.member(pool.id, a.lot_id)
            scores[a.id] = m.score if m else None
        return PoolOut(
            id=pool.id,
            demand_id=pool.demand_id,
            status=pool.status,
            algorithm=pool.algorithm,
            demand_kg=pool.demand_kg,
            allocated_kg=pool.allocated_kg,
            shortage_kg=pool.shortage_kg,
            unfilled_kg=max(ZERO, pool.demand_kg - pool.allocated_kg),
            closed=pool.closed_at is not None,
            fill_rate=(pool.allocated_kg / pool.demand_kg).quantize(Decimal("0.0001")),
            version=pool.version,
            allocations=[
                AllocationOut(**AllocationOut.model_validate(a).model_dump(exclude={"score"}), score=scores[a.id])
                for a in allocs
            ],
            notes=list(notes),
            created_at=pool.created_at,
            updated_at=pool.updated_at,
        )

    @staticmethod
    def _match_out(m: Match) -> MatchOut:
        s = m.supply
        return MatchOut(
            lot_id=uuid.UUID(s.lot_id),
            farm_ref=s.farm_ref,
            eligible=m.eligible,
            reasons=list(m.reasons),
            score=m.score,
            components=m.components,
            available_kg=s.available_kg,
            p50_kg=s.p50_kg,
            window_start=s.window_start,
            window_end=s.window_end,
            confidence=s.confidence,
            risk=s.risk,
            reliability=s.reliability.quantize(Decimal("0.001")),
            distance_km=m.distance_km,
            grade=s.grade,
            grade_basis="farmer_graded" if s.grade_confirmed else "farmer_expected",
        )
