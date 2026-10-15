"""Planning DTOs: outputs. Each class mirrors a domain result dataclass and is read from it directly."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import (
    ConfidenceLevel,
    ContinuityLevel,
    FindingSeverity,
    RankBy,
    RiskLevel,
)
from app.schemas.base import JsonNumber
from app.schemas.planning import CalcItem


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TripleOut(_Out):
    """Pessimistic (low), expected and optimistic (high) values. Never a guarantee."""

    low: JsonNumber
    expected: JsonNumber
    high: JsonNumber


class ComponentOut(_Out):
    name: str
    score: JsonNumber
    weight: JsonNumber
    detail: str


class RiskOut(_Out):
    score: JsonNumber = Field(description="0 (safe) to 100 (very risky)")
    level: RiskLevel
    components: list[ComponentOut]


class ConfidenceOut(_Out):
    score: JsonNumber = Field(description="0-100: how well-founded the inputs are. Not a probability of success.")
    level: ConfidenceLevel
    components: list[ComponentOut]


class FindingOut(_Out):
    code: str
    severity: FindingSeverity
    message: str
    item_index: int | None
    details: dict[str, str | float]


class BatchOut(_Out):
    index: int
    area_acres: JsonNumber
    sowing_date: date
    harvest_start: date
    harvest_end: date


class BreakEvenOut(_Out):
    price_per_kg_expected: JsonNumber
    price_per_kg_conservative: JsonNumber | None
    yield_kg_per_acre: JsonNumber
    margin_of_safety_pct: JsonNumber


class ItemResultOut(_Out):
    index: int
    crop_name: str
    area_acres: JsonNumber
    batches: list[BatchOut]
    cost_per_acre: JsonNumber
    cost: TripleOut
    cost_breakdown: dict[str, JsonNumber]
    overrun_pct: JsonNumber
    production_kg: TripleOut
    sold_kg: TripleOut
    demand_limited: bool
    revenue: TripleOut
    margin: TripleOut
    roi_expected_pct: JsonNumber | None
    break_even: BreakEvenOut
    risk: RiskOut
    confidence: ConfidenceOut
    explanations: list[str]


class PeriodOut(_Out):
    start: date
    end: date
    days: int
    months: int


class TotalsOut(_Out):
    area_sown_acres: JsonNumber
    cost: TripleOut
    revenue: TripleOut
    margin: TripleOut
    roi_expected_pct: JsonNumber | None
    break_even_revenue: JsonNumber
    break_even_pct_of_expected_revenue: JsonNumber | None
    cover_ratio_expected: JsonNumber | None
    cover_ratio_pessimistic: JsonNumber | None


class LandMonthOut(_Out):
    month: str
    peak_area_acres: JsonNumber
    average_area_acres: JsonNumber
    utilization_pct: JsonNumber


class LandUtilizationOut(_Out):
    available_acres: JsonNumber
    peak_in_use_acres: JsonNumber
    peak_utilization_pct: JsonNumber
    average_utilization_pct: JsonNumber
    unused_at_peak_acres: JsonNumber
    first_over_limit_on: date | None
    monthly: list[LandMonthOut]


class MonthlyFlowOut(_Out):
    month: str
    income: TripleOut
    cost_expected: JsonNumber
    net_expected: JsonNumber
    cumulative_net_expected: JsonNumber


class IncomeContinuityOut(_Out):
    level: ContinuityLevel
    monthly: list[MonthlyFlowOut]
    income_months: int
    span_months: int
    lead_months: int
    gap_months: int
    gap_month_list: list[str]
    longest_gap_months: int
    largest_month_share_pct: JsonNumber
    peak_funding_required: JsonNumber
    advice: list[str]


class BudgetOut(_Out):
    budget: JsonNumber | None
    expected_cost: JsonNumber
    high_cost: JsonNumber
    headroom_expected: JsonNumber | None
    headroom_high: JsonNumber | None
    utilization_pct: JsonNumber | None


class ResourceOut(_Out):
    required: JsonNumber
    available: JsonNumber | None
    headroom: JsonNumber | None
    utilization_pct: JsonNumber | None
    items_without_estimate: int


class PlanResultOut(_Out):
    """The full, explainable evaluation of a plan. All figures are estimates over ranges."""

    period: PeriodOut
    totals: TotalsOut
    land: LandUtilizationOut
    budget: BudgetOut
    water: ResourceOut
    labour: ResourceOut
    continuity: IncomeContinuityOut
    items: list[ItemResultOut]
    risk: RiskOut
    confidence: ConfidenceOut
    findings: list[FindingOut]
    feasible: bool = Field(description="False when land or budget is exceeded (a HARD finding)")
    explanations: list[str]
    assumptions: list[str]
    disclaimer: str


# --------------------------------------------------------------- allocation


class AllocationOut(_Out):
    candidate_index: int
    crop_name: str
    area_acres: JsonNumber
    limited_by: str
    cost_per_acre: JsonNumber
    margin_per_acre: JsonNumber
    expected_margin: JsonNumber
    reason: str


class ExcludedOut(_Out):
    candidate_index: int
    crop_name: str
    code: str
    reason: str


class AllocationResponse(BaseModel):
    """A suggested split of land. `suggested_items` can be sent to POST /planning/calculate or saved in a plan."""

    rank_by: RankBy
    ranking: list[int]
    allocations: list[AllocationOut]
    excluded: list[ExcludedOut]
    notes: list[str]
    suggested_items: list[CalcItem]
    plan: PlanResultOut | None = Field(
        description="Evaluation of the suggested split; null if nothing could be allocated"
    )


# ------------------------------------------------------------------ compare


class CompareRow(BaseModel):
    plan_id: uuid.UUID
    name: str
    feasible: bool
    hard_findings: int
    warnings: int
    cost: TripleOut
    revenue: TripleOut
    margin: TripleOut
    roi_expected_pct: JsonNumber | None
    peak_land_utilization_pct: JsonNumber
    planning_period: PeriodOut
    continuity: ContinuityLevel
    risk: RiskOut
    confidence: ConfidenceOut


class CompareResponse(BaseModel):
    rows: list[CompareRow]
    best_expected_margin_plan_id: uuid.UUID | None = Field(
        description="The feasible plan with the highest expected margin (null if none is feasible)"
    )
    note: str
