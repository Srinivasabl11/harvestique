"""Pure marketplace rules: order state, participation transitions, quality verification, fulfilment quantity."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from decimal import Decimal

from app.core.enums import OrderItemStatus, OrderStatus, ParticipationStatus, QualityGrade, QualityResult

ZERO = Decimal(0)
GRADE_RANK = {QualityGrade.A: 3, QualityGrade.B: 2, QualityGrade.C: 1}
OPEN_ITEMS = frozenset({OrderItemStatus.AWAITING_FARMER, OrderItemStatus.ACCEPTED})
DELIVERED_ITEMS = frozenset({OrderItemStatus.FULFILLED, OrderItemStatus.SHORT})


class MarketplaceRuleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def order_status(
    current: OrderStatus,
    items: Collection[OrderItemStatus],
    fulfilled_kg: Decimal,
    ordered_kg: Decimal,
    any_batch: bool,
    *,
    accepted_kg: Decimal,
) -> OrderStatus:
    """Derive the order state from its items (a cancelled order stays cancelled).

    CONFIRMED means the farmers have accepted the WHOLE ordered quantity (`accepted_kg`: accepted items plus anything
    already delivered). An order whose farmers accepted everything asked of them but whose pool is short (e.g. 250 of
    300 kg) stays PLACED, so a shortage is never reported as secured."""
    if current is OrderStatus.CANCELLED:
        return current
    open_items = [s for s in items if s in OPEN_ITEMS]
    if not open_items and any(s in DELIVERED_ITEMS for s in items):
        return OrderStatus.FULFILLED if fulfilled_kg >= ordered_kg else OrderStatus.PARTIALLY_FULFILLED
    if any_batch:
        return OrderStatus.IN_FULFILMENT
    if open_items and all(s is OrderItemStatus.ACCEPTED for s in open_items) and accepted_kg >= ordered_kg:
        return OrderStatus.CONFIRMED
    return OrderStatus.PLACED


@dataclass(frozen=True)
class OrderQuantities:
    """Where the ordered quantity stands. `confirmed` = accepted by farmers (+ already delivered); `awaiting` = asked
    of farmers who have not answered; `uncovered` = no supply found yet (ordered - confirmed - awaiting, >= 0)."""

    confirmed_kg: Decimal
    awaiting_kg: Decimal
    uncovered_kg: Decimal


def order_quantities(
    items: Iterable[tuple[OrderItemStatus, Decimal]], fulfilled_kg: Decimal, ordered_kg: Decimal
) -> OrderQuantities:
    rows = list(items)
    confirmed = sum((q for s, q in rows if s is OrderItemStatus.ACCEPTED), ZERO) + fulfilled_kg
    awaiting = sum((q for s, q in rows if s is OrderItemStatus.AWAITING_FARMER), ZERO)
    return OrderQuantities(confirmed, awaiting, max(ZERO, ordered_kg - confirmed - awaiting))


def check_respond(participation: ParticipationStatus, item: OrderItemStatus, *, decline: bool, has_batch: bool) -> None:
    """A farmer may accept a pending request, and decline a pending or accepted one until produce is received."""
    if item not in OPEN_ITEMS:
        raise MarketplaceRuleError("item_closed", "This order item is no longer open")
    if has_batch:
        raise MarketplaceRuleError("already_collected", "Produce has already been received for this item")
    allowed = {ParticipationStatus.PENDING, ParticipationStatus.ACCEPTED} if decline else {ParticipationStatus.PENDING}
    if participation not in allowed:
        raise MarketplaceRuleError(
            "invalid_transition", f"Cannot {'decline' if decline else 'accept'} a {participation.value} request"
        )


def check_cancel(status: OrderStatus, any_batch: bool) -> None:
    if status in (OrderStatus.CANCELLED, OrderStatus.FULFILLED, OrderStatus.PARTIALLY_FULFILLED):
        raise MarketplaceRuleError("order_closed", f"A {status.value} order cannot be cancelled")
    if any_batch:
        raise MarketplaceRuleError("already_collected", "Produce has already been received for this order")


def quality_result(
    received_kg: Decimal,
    accepted_kg: Decimal,
    rejected_kg: Decimal,
    grade: QualityGrade | None,
    min_grade: QualityGrade,
) -> QualityResult:
    """Validate a MEASURED quality check against the batch and the buyer's minimum grade."""
    if accepted_kg < 0 or rejected_kg < 0:
        raise MarketplaceRuleError("negative_quantity", "Quantities cannot be negative")
    if accepted_kg + rejected_kg != received_kg:
        raise MarketplaceRuleError(
            "quantities_mismatch",
            f"Accepted ({accepted_kg}) + rejected ({rejected_kg}) must equal the received weight ({received_kg})",
        )
    if accepted_kg > 0 and grade is None:
        raise MarketplaceRuleError("grade_required", "A grade is required when any quantity is accepted")
    if accepted_kg > 0 and grade is not None and GRADE_RANK[grade] < GRADE_RANK[min_grade]:
        raise MarketplaceRuleError(
            "grade_below_order_minimum",
            f"Grade {grade.value} is below the buyer's minimum {min_grade.value}; the batch can only be rejected",
        )
    if accepted_kg == 0:
        return QualityResult.REJECTED
    return QualityResult.ACCEPTED if rejected_kg == 0 else QualityResult.PARTIALLY_ACCEPTED


def fulfil_quantity(accepted_total_kg: Decimal, committed_kg: Decimal) -> Decimal:
    """Only quality-accepted (measured) produce counts, and never more than the farm's committed share."""
    return max(ZERO, min(accepted_total_kg, committed_kg))


def batch_code(seq_hex: str, day: str) -> str:
    """Printable batch code, e.g. HQ-261008-3F9A2C (date + 6 random hex digits)."""
    return f"HQ-{day}-{seq_hex[:6].upper()}"
