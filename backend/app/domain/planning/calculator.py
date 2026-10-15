"""Cost and income arithmetic for one plan item. Deterministic, full precision, no rounding.

Worked definitions (all shown to the user in the item's `explanations`):

  cost per acre   = seed + fertilizer + pesticide + irrigation + machinery + other
                    + labour person-days x daily wage
  expected cost   = cost per acre x area + fixed cost
  high cost       = expected cost x (1 + overrun %)         (cost is never assumed to be *lower*)
  production      = yield per acre x area                    (low / expected / high)
  sold quantity   = min(production, demand quantity)         (unsold surplus earns nothing)
  revenue         = sold quantity x price                    (low x low, expected x expected, high x high)
  margin          = revenue - cost, pairing the WORST revenue with the HIGH cost
  break-even      = the price / yield at which margin would be zero
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.core.enums import RiskLevel
from app.domain.planning.models import (
    AREA_QUANT,
    ZERO,
    BatchSchedule,
    CostInputs,
    D,
    ItemInput,
    PlanningInputError,
    Triple,
)

MONEY = D("0.01")
QTY = D("0.001")
PCT = D("0.01")
SCORE = D("0.1")
HUNDRED = D(100)

# Cost-overrun allowance when the farmer gives none, by how risky they declared the crop to be.
DEFAULT_OVERRUN_PCT: dict[RiskLevel, Decimal] = {
    RiskLevel.LOW: D(5),
    RiskLevel.MEDIUM: D(10),
    RiskLevel.HIGH: D(20),
}


def q(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def qt(triple: Triple, quantum: Decimal) -> Triple:
    return Triple(q(triple.low, quantum), q(triple.expected, quantum), q(triple.high, quantum))


def inr(value: Decimal) -> str:
    return f"₹{value:,.2f}"


def num(value: Decimal, places: int = 2) -> str:
    return f"{value:,.{places}f}"


# --------------------------------------------------------------- batches


def split_area(total: Decimal, batches: int) -> list[Decimal]:
    """Equal thousandth-acre shares; the (tiny) remainder goes to the last batch so the sum is exact."""
    share = (total / batches).quantize(AREA_QUANT, rounding=ROUND_FLOOR)
    if share <= 0:
        raise PlanningInputError("batch_area_too_small", "Each batch must be at least 0.001 acre", "batches")
    areas = [share] * (batches - 1)
    areas.append(total - share * (batches - 1))
    return areas


def batch_schedules(item: ItemInput) -> tuple[BatchSchedule, ...]:
    """Sowing, harvest window and land occupancy of every batch (staggered planting)."""
    interval = item.batch_interval_days or 0
    out: list[BatchSchedule] = []
    for index, area in enumerate(split_area(item.area_acres, item.batches)):
        sowing = item.sowing_date + timedelta(days=index * interval)
        harvest_start = sowing + timedelta(days=item.duration_days)
        harvest_end = harvest_start + timedelta(days=item.harvest_window_days - 1)
        out.append(BatchSchedule(index, area, sowing, harvest_start, harvest_end))
    return tuple(out)


# ------------------------------------------------------------- economics


@dataclass(frozen=True, slots=True)
class Economics:
    """Full-precision results for one item (rounded only when the ItemResult is assembled)."""

    area: Decimal
    cost_per_acre: Decimal
    labour_cost_per_acre: Decimal
    input_cost_per_acre: Decimal
    breakdown: dict[str, Decimal]
    overrun_pct: Decimal
    cost_expected: Decimal
    cost_high: Decimal
    production: Triple
    sold: Triple
    demand_limited: bool
    revenue: Triple
    margin: Triple
    roi_pct: Decimal | None
    be_price_expected: Decimal
    be_price_conservative: Decimal | None
    be_yield_per_acre: Decimal
    margin_of_safety_pct: Decimal


def cost_per_acre(cost: CostInputs) -> tuple[Decimal, Decimal, Decimal]:
    """(total, inputs-only, labour) per acre."""
    inputs = cost.seed + cost.fertilizer + cost.pesticide + cost.irrigation + cost.machinery + cost.other
    labour = cost.labour_person_days_per_acre * cost.labour_wage_per_day
    return inputs + labour, inputs, labour


def resolve_overrun(item: ItemInput) -> Decimal:
    given = item.cost.overrun_pct
    return given if given is not None else DEFAULT_OVERRUN_PCT[item.declared_risk]


def compute_economics(item: ItemInput) -> Economics:
    area, c = item.area_acres, item.cost
    per_acre, inputs_per_acre, labour_per_acre = cost_per_acre(c)

    breakdown = {
        "seed": c.seed * area,
        "fertilizer": c.fertilizer * area,
        "pesticide": c.pesticide * area,
        "irrigation": c.irrigation * area,
        "machinery": c.machinery * area,
        "other": c.other * area,
        "labour": labour_per_acre * area,
        "fixed": c.fixed_cost,
    }
    expected_cost = per_acre * area + c.fixed_cost
    overrun = resolve_overrun(item)
    high_cost = expected_cost * (1 + overrun / HUNDRED)

    y, p = item.yield_per_acre_kg, item.price_per_kg
    production = Triple(y.low * area, y.expected * area, y.high * area)
    cap = item.demand_quantity_kg
    sold = Triple(*(min(v, cap) for v in (production.low, production.expected, production.high))) if cap else production
    demand_limited = cap is not None and production.expected > cap

    revenue = Triple(sold.low * p.low, sold.expected * p.expected, sold.high * p.high)
    # Worst case pairs the lowest revenue with the highest cost; best case keeps the expected cost.
    margin = Triple(revenue.low - high_cost, revenue.expected - expected_cost, revenue.high - expected_cost)

    be_price = expected_cost / sold.expected  # sold.expected > 0: yield and demand cap are both positive
    be_price_conservative = high_cost / sold.low if sold.low > 0 else None
    be_yield = expected_cost / (p.expected * area)
    safety = (y.expected - be_yield) / y.expected * HUNDRED
    roi = margin.expected / expected_cost * HUNDRED if expected_cost > 0 else None

    return Economics(
        area=area,
        cost_per_acre=per_acre,
        labour_cost_per_acre=labour_per_acre,
        input_cost_per_acre=inputs_per_acre,
        breakdown=breakdown,
        overrun_pct=overrun,
        cost_expected=expected_cost,
        cost_high=high_cost,
        production=production,
        sold=sold,
        demand_limited=demand_limited,
        revenue=revenue,
        margin=margin,
        roi_pct=roi,
        be_price_expected=be_price,
        be_price_conservative=be_price_conservative,
        be_yield_per_acre=be_yield,
        margin_of_safety_pct=safety,
    )


def per_acre_variable_margin(item: ItemInput) -> tuple[Decimal, Decimal, Decimal | None]:
    """(cost per acre, expected margin per acre, return on cost %) ignoring fixed cost and demand caps.

    Used to rank crops when allocating land; fixed costs and demand caps are handled by the allocator.
    """
    per_acre, _, _ = cost_per_acre(item.cost)
    revenue = item.yield_per_acre_kg.expected * item.price_per_kg.expected
    margin = revenue - per_acre
    roi = margin / per_acre * HUNDRED if per_acre > 0 else None
    return per_acre, margin, roi


__all__ = [
    "DEFAULT_OVERRUN_PCT",
    "MONEY",
    "PCT",
    "QTY",
    "SCORE",
    "ZERO",
    "Economics",
    "batch_schedules",
    "compute_economics",
    "cost_per_acre",
    "inr",
    "num",
    "per_acre_variable_margin",
    "q",
    "qt",
    "resolve_overrun",
    "split_area",
]
