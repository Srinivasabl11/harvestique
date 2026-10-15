"""Value objects of the planning engine: validated inputs and immutable results.

Pure Python: no I/O, no framework imports. All money is INR, area is acres, quantity is kg, water is
kilolitres (kL). Amounts are `Decimal`; results are rounded (half-up) only when they are *built*, never
in the middle of a calculation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.core.enums import (
    ConfidenceLevel,
    ContinuityLevel,
    CropSeason,
    DemandLevel,
    EstimateBasis,
    FindingSeverity,
    RiskLevel,
)

D = Decimal
ZERO = D(0)
AREA_QUANT = D("0.001")  # areas are whole thousandths of an acre
MAX_BATCHES = 12
MAX_ITEMS = 30


class PlanningInputError(ValueError):
    """An input the engine cannot work with. Carries a stable machine code."""

    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


# ================================================================== inputs


@dataclass(frozen=True, slots=True)
class Range:
    """A low / expected / high estimate. Never a promise: the engine carries all three through."""

    low: Decimal
    expected: Decimal
    high: Decimal

    def __post_init__(self) -> None:
        if self.low < 0:
            raise PlanningInputError("range_negative", "A range cannot contain negative values")
        if not self.low <= self.expected <= self.high:
            raise PlanningInputError("range_not_ordered", "A range must satisfy low <= expected <= high")
        if self.expected <= 0:
            raise PlanningInputError("range_expected_not_positive", "The expected value must be greater than zero")

    @property
    def spread(self) -> Decimal:
        """Relative width of the range, (high - low) / expected. 0 = a single number; 1 = +/-50%."""
        return (self.high - self.low) / self.expected


@dataclass(frozen=True, slots=True)
class CostInputs:
    """Per-acre cost estimates (INR), labour as person-days x wage, plus a fixed total."""

    seed: Decimal = ZERO
    fertilizer: Decimal = ZERO
    pesticide: Decimal = ZERO
    irrigation: Decimal = ZERO
    machinery: Decimal = ZERO
    other: Decimal = ZERO
    labour_person_days_per_acre: Decimal = ZERO
    labour_wage_per_day: Decimal = ZERO
    fixed_cost: Decimal = ZERO  # whole-item costs that do not scale with area (e.g. equipment hire)
    overrun_pct: Decimal | None = None  # None = default from the item's declared risk

    def __post_init__(self) -> None:
        for name in (
            "seed",
            "fertilizer",
            "pesticide",
            "irrigation",
            "machinery",
            "other",
            "labour_person_days_per_acre",
            "labour_wage_per_day",
            "fixed_cost",
        ):
            if getattr(self, name) < 0:
                raise PlanningInputError("cost_negative", f"{name} cannot be negative", name)
        if self.overrun_pct is not None and self.overrun_pct < 0:
            raise PlanningInputError("overrun_negative", "overrun_pct cannot be negative", "overrun_pct")


@dataclass(frozen=True, slots=True)
class ItemInput:
    """One crop in a plan: how much, when, and what the farmer expects of it."""

    crop_name: str
    area_acres: Decimal
    sowing_date: date
    duration_days: int  # sowing -> start of harvest
    harvest_window_days: int  # days over which the crop is harvested and sold
    yield_per_acre_kg: Range
    price_per_kg: Range  # INR/kg, entered net of transport and commission
    cost: CostInputs = field(default_factory=CostInputs)
    water_kl_per_acre: Decimal | None = None
    demand_level: DemandLevel = DemandLevel.MEDIUM
    demand_quantity_kg: Decimal | None = None  # the most the market can absorb; None = unconstrained
    declared_risk: RiskLevel = RiskLevel.MEDIUM
    estimate_basis: EstimateBasis = EstimateBasis.LOCAL_KNOWLEDGE
    batches: int = 1  # staggered planting: the area is split equally into this many sowings
    batch_interval_days: int | None = None
    crop_season: CropSeason | None = None  # from the catalog, when linked
    has_catalog_crop: bool = False

    def __post_init__(self) -> None:
        if not self.crop_name.strip():
            raise PlanningInputError("crop_name_blank", "crop_name cannot be blank", "crop_name")
        if self.area_acres <= 0:
            raise PlanningInputError("area_not_positive", "area_acres must be greater than zero", "area_acres")
        if self.area_acres != self.area_acres.quantize(AREA_QUANT):
            raise PlanningInputError("area_precision", "area_acres allows at most 3 decimal places", "area_acres")
        if self.duration_days <= 0:
            raise PlanningInputError("duration_not_positive", "duration_days must be positive", "duration_days")
        if not 1 <= self.harvest_window_days <= 365:
            raise PlanningInputError(
                "harvest_window_invalid", "harvest_window_days must be between 1 and 365", "harvest_window_days"
            )
        if not 1 <= self.batches <= MAX_BATCHES:
            raise PlanningInputError("batches_invalid", f"batches must be between 1 and {MAX_BATCHES}", "batches")
        if self.batches > 1 and (self.batch_interval_days is None or self.batch_interval_days < 1):
            raise PlanningInputError(
                "batch_interval_required",
                "batch_interval_days (>= 1) is required when batches > 1",
                "batch_interval_days",
            )
        if self.demand_quantity_kg is not None and self.demand_quantity_kg <= 0:
            raise PlanningInputError(
                "demand_quantity_not_positive", "demand_quantity_kg must be positive", "demand_quantity_kg"
            )
        if self.water_kl_per_acre is not None and self.water_kl_per_acre < 0:
            raise PlanningInputError("water_negative", "water_kl_per_acre cannot be negative", "water_kl_per_acre")
        if self.area_acres / self.batches < AREA_QUANT:
            raise PlanningInputError("batch_area_too_small", "Each batch must be at least 0.001 acre", "batches")


@dataclass(frozen=True, slots=True)
class PlanInput:
    available_land_acres: Decimal
    season: CropSeason
    items: tuple[ItemInput, ...]
    budget_inr: Decimal | None = None  # None = no budget limit
    available_water_kl: Decimal | None = None
    available_labour_person_days: Decimal | None = None

    def __post_init__(self) -> None:
        if self.available_land_acres <= 0:
            raise PlanningInputError(
                "land_not_positive", "available_land_acres must be positive", "available_land_acres"
            )
        for name in ("budget_inr", "available_water_kl", "available_labour_person_days"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise PlanningInputError(f"{name}_not_positive", f"{name} must be positive when given", name)
        if not self.items:
            raise PlanningInputError("plan_has_no_items", "A plan needs at least one crop")
        if len(self.items) > MAX_ITEMS:
            raise PlanningInputError("too_many_items", f"A plan can hold at most {MAX_ITEMS} crops")


# ================================================================= results


@dataclass(frozen=True, slots=True)
class Triple:
    """The three scenario values of a quantity: pessimistic (low), expected, optimistic (high)."""

    low: Decimal
    expected: Decimal
    high: Decimal


@dataclass(frozen=True, slots=True)
class Component:
    """One explainable ingredient of a score: 0-100 points, its weight, and why."""

    name: str
    score: Decimal
    weight: Decimal
    detail: str


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    score: Decimal  # 0 (safe) - 100 (very risky)
    level: RiskLevel
    components: tuple[Component, ...]


@dataclass(frozen=True, slots=True)
class ConfidenceAssessment:
    score: Decimal  # 0 - 100: how well-founded the *inputs* are (not a probability of success)
    level: ConfidenceLevel
    components: tuple[Component, ...]


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    severity: FindingSeverity
    message: str
    item_index: int | None = None
    details: dict[str, str | float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BatchSchedule:
    index: int
    area_acres: Decimal
    sowing_date: date
    harvest_start: date
    harvest_end: date  # the land stays occupied through this day


@dataclass(frozen=True, slots=True)
class BreakEven:
    price_per_kg_expected: Decimal  # price that covers expected cost at expected sales
    price_per_kg_conservative: Decimal | None  # covers the high cost at the low yield (None if low yield is 0)
    yield_kg_per_acre: Decimal  # yield that covers expected cost at the expected price
    margin_of_safety_pct: Decimal  # how far the expected yield sits above that break-even yield


@dataclass(frozen=True, slots=True)
class ItemResult:
    index: int
    crop_name: str
    area_acres: Decimal
    batches: tuple[BatchSchedule, ...]
    cost_per_acre: Decimal
    cost: Triple  # low = expected (cost cannot be assumed lower), high = with overrun
    cost_breakdown: dict[str, Decimal]
    overrun_pct: Decimal
    production_kg: Triple
    sold_kg: Triple
    demand_limited: bool
    revenue: Triple
    margin: Triple
    roi_expected_pct: Decimal | None
    break_even: BreakEven
    risk: RiskAssessment
    confidence: ConfidenceAssessment
    explanations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanningPeriod:
    start: date
    end: date
    days: int
    months: int


@dataclass(frozen=True, slots=True)
class PlanTotals:
    area_sown_acres: Decimal  # sum of crop areas (land reused over time counts each time)
    cost: Triple
    revenue: Triple
    margin: Triple
    roi_expected_pct: Decimal | None
    break_even_revenue: Decimal  # revenue needed to cover the expected cost
    break_even_pct_of_expected_revenue: Decimal | None
    cover_ratio_expected: Decimal | None  # expected revenue / expected cost
    cover_ratio_pessimistic: Decimal | None  # low revenue / high cost


@dataclass(frozen=True, slots=True)
class LandMonth:
    month: str  # YYYY-MM
    peak_area_acres: Decimal
    average_area_acres: Decimal
    utilization_pct: Decimal  # peak / available


@dataclass(frozen=True, slots=True)
class LandUtilization:
    available_acres: Decimal
    peak_in_use_acres: Decimal
    peak_utilization_pct: Decimal
    average_utilization_pct: Decimal  # area-days used / area-days available over the planning period
    unused_at_peak_acres: Decimal  # negative if over the limit
    first_over_limit_on: date | None
    monthly: tuple[LandMonth, ...]


@dataclass(frozen=True, slots=True)
class MonthlyFlow:
    month: str
    income: Triple
    cost_expected: Decimal
    net_expected: Decimal
    cumulative_net_expected: Decimal


@dataclass(frozen=True, slots=True)
class IncomeContinuity:
    level: ContinuityLevel
    monthly: tuple[MonthlyFlow, ...]
    income_months: int
    span_months: int  # first income month .. last income month, inclusive
    lead_months: int  # months between the first sowing and the first income
    gap_months: int
    gap_month_list: tuple[str, ...]
    longest_gap_months: int
    largest_month_share_pct: Decimal
    peak_funding_required: Decimal  # the deepest cumulative shortfall if income is reinvested as it arrives
    advice: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BudgetSummary:
    budget: Decimal | None
    expected_cost: Decimal
    high_cost: Decimal
    headroom_expected: Decimal | None
    headroom_high: Decimal | None
    utilization_pct: Decimal | None  # expected cost / budget


@dataclass(frozen=True, slots=True)
class ResourceUse:
    required: Decimal
    available: Decimal | None
    headroom: Decimal | None
    utilization_pct: Decimal | None
    items_without_estimate: int


@dataclass(frozen=True, slots=True)
class PlanResult:
    period: PlanningPeriod
    totals: PlanTotals
    land: LandUtilization
    budget: BudgetSummary
    water: ResourceUse
    labour: ResourceUse
    continuity: IncomeContinuity
    items: tuple[ItemResult, ...]
    risk: RiskAssessment
    confidence: ConfidenceAssessment
    findings: tuple[Finding, ...]
    feasible: bool  # False when any HARD finding exists (land or budget exceeded)
    explanations: tuple[str, ...]
    assumptions: tuple[str, ...]
    disclaimer: str
