"""Dynamic shortage detection and pool state rules (pure)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.core.enums import DemandStatus, OrderStatus, PoolStatus
from app.domain.pooling.models import ZERO


@dataclass(frozen=True, slots=True)
class Commitment:
    reservation_id: str
    quantity_kg: Decimal
    order: int  # creation order; higher = newer
    pool_owned: bool  # False = the farmer's own reservation, never cut by the system


@dataclass(frozen=True, slots=True)
class ShortfallAssignment:
    cuts: dict[str, Decimal]  # reservation id -> kg to remove
    uncovered_kg: Decimal  # shortfall left on reservations the system may not cut


def lot_shortfall(committable_kg: Decimal, commitments: Sequence[Commitment]) -> Decimal:
    """Exact shortage of one lot: committed beyond what it can now safely promise."""
    return max(ZERO, sum((c.quantity_kg for c in commitments), ZERO) - committable_kg)


def assign_shortfall(shortfall_kg: Decimal, commitments: Sequence[Commitment]) -> ShortfallAssignment:
    """Cut pool reservations NEWEST FIRST (older confirmed quantities are preserved where possible)."""
    remaining, cuts = shortfall_kg, {}
    for c in sorted((c for c in commitments if c.pool_owned), key=lambda c: (-c.order, c.reservation_id)):
        if remaining <= 0:
            break
        cut = min(c.quantity_kg, remaining)
        cuts[c.reservation_id] = cut
        remaining -= cut
    return ShortfallAssignment(cuts, max(ZERO, remaining))


def demand_stage(
    demand_status: DemandStatus,
    pool_status: PoolStatus | None,
    order_status: OrderStatus | None,
    open_fulfilment: str | None = None,
) -> str:
    """One buyer-facing state for a demand, from its demand, pool and order states (most actionable first).
    `open_fulfilment` (full / partial / none) is live matching for a demand with no pool yet: nothing is reserved,
    it only says whether current eligible predicted supply could cover it."""
    if demand_status is DemandStatus.CANCELLED or order_status is OrderStatus.CANCELLED:
        return "cancelled"
    if order_status is OrderStatus.FULFILLED:
        return "fulfilled"
    if order_status is OrderStatus.PARTIALLY_FULFILLED:
        return "partially_fulfilled"
    if pool_status is None:  # demand saved, nothing reserved yet
        return {
            "full": "matching_supply_available",
            "partial": "partially_matched",
            "none": "no_matching_supply",
        }.get(open_fulfilment or "", "open")
    if pool_status is PoolStatus.AT_RISK:
        return "reallocation_required"  # supply changed and the shortage is not (yet) covered
    if order_status is OrderStatus.IN_FULFILMENT:
        return "in_fulfilment"
    if order_status is OrderStatus.CONFIRMED:
        return "confirmed"
    if order_status is OrderStatus.PLACED:
        return "awaiting_farmer_confirmation"
    return {
        PoolStatus.FILLED: "supply_reserved",
        PoolStatus.PARTIAL: "partially_matched",
        PoolStatus.UNFILLED: "no_matching_supply",
    }[pool_status]


def pool_status(
    demand_kg: Decimal, allocated_kg: Decimal, unresolved_shortage_kg: Decimal, any_lot_at_risk: bool
) -> PoolStatus:
    if unresolved_shortage_kg > 0 or any_lot_at_risk:
        return PoolStatus.AT_RISK
    if allocated_kg >= demand_kg:
        return PoolStatus.FILLED
    return PoolStatus.PARTIAL if allocated_kg > 0 else PoolStatus.UNFILLED
