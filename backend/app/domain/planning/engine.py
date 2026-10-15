"""Plan evaluation: the single entry point that turns a PlanInput into an explainable PlanResult.

evaluate_plan is a pure, deterministic function: the same input always yields the same result, and the
result carries its own explanation (per-crop cost lines, risk/confidence components, findings).
Results are *estimates over ranges*. Nothing here predicts or guarantees a yield, price or income.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.core.enums import ContinuityLevel, FindingSeverity
from app.domain.planning import scoring
from app.domain.planning.calculator import (
    HUNDRED,
    MONEY,
    PCT,
    QTY,
    Economics,
    batch_schedules,
    compute_economics,
    inr,
    num,
    q,
    qt,
)
from app.domain.planning.models import (
    ZERO,
    BatchSchedule,
    BreakEven,
    BudgetSummary,
    ConfidenceAssessment,
    Finding,
    ItemInput,
    ItemResult,
    PlanInput,
    PlanResult,
    PlanTotals,
    ResourceUse,
    RiskAssessment,
    Triple,
)
from app.domain.planning.timeline import (
    income_continuity,
    land_utilization,
    occupancies_of,
    period_of,
)

DISCLAIMER = (
    "These figures are planning estimates built from the ranges you entered. They are not forecasts and "
    "do not guarantee any yield, price, cost or income."
)
ASSUMPTIONS = (
    "Yield and price are ranges: 'low' is a pessimistic case, 'high' an optimistic one. Reality can fall outside them.",
    "The pessimistic margin combines every crop's lowest yield and lowest price with the highest cost at once; "
    "that is deliberately harsh and unlikely to happen exactly.",
    "Enter prices net of transport and commission; selling costs are not modelled separately.",
    "Costs are spent in the month of sowing. The budget check compares total expected cost with the budget and "
    "assumes no income is reinvested.",
    "Revenue is spread evenly over each crop's harvest window and received in the month of harvest (no payment delay).",
    "Land is occupied from the sowing day through the last day of the harvest window.",
    "Water and labour checks compare season totals; they do not model peak-week demand.",
    "Season fit uses an indicative sowing-month calendar and only produces warnings.",
)


# ============================================================ item assembly


def _item_explanations(item: ItemInput, e: Economics, batches: Sequence[BatchSchedule]) -> tuple[str, ...]:
    c = item.cost
    lines = [
        f"Cost per acre is {inr(e.cost_per_acre)}: {inr(e.input_cost_per_acre)} of inputs plus {inr(e.labour_cost_per_acre)} "
        f"of labour ({num(c.labour_person_days_per_acre)} person-days × {inr(c.labour_wage_per_day)}).",
        f"Expected cost = {inr(e.cost_per_acre)} × {num(e.area, 3)} acres + {inr(c.fixed_cost)} fixed = {inr(e.cost_expected)}; "
        f"up to {inr(e.cost_high)} with a {num(e.overrun_pct)}% overrun allowance.",
        f"Production is expected to be {num(e.production.expected, 0)} kg "
        f"(range {num(e.production.low, 0)}–{num(e.production.high, 0)} kg).",
    ]
    if e.demand_limited:
        lines.append(
            f"Demand is limited to {num(item.demand_quantity_kg or ZERO, 0)} kg, so only that much is counted as sold; "
            f"{num(e.production.expected - e.sold.expected, 0)} kg of the expected crop earns nothing in this estimate."
        )
    lines += [
        f"Revenue = sold kg × price: expected {inr(e.revenue.expected)} (range {inr(e.revenue.low)}–{inr(e.revenue.high)}).",
        f"Margin: expected {inr(e.margin.expected)}; pessimistic {inr(e.margin.low)} "
        f"(lowest revenue minus the high cost); optimistic {inr(e.margin.high)}.",
        f"Break-even: a price of {inr(e.be_price_expected)}/kg covers the expected cost at the expected sales, or a yield of "
        f"{num(e.be_yield_per_acre, 0)} kg/acre at the expected price "
        f"({num(e.margin_of_safety_pct, 0)}% below the expected yield).",
    ]
    first, last = batches[0], batches[-1]
    if len(batches) == 1:
        lines.append(f"Sown {first.sowing_date}; harvest {first.harvest_start} to {first.harvest_end}.")
    else:
        lines.append(
            f"Sown in {len(batches)} batches from {first.sowing_date} to {last.sowing_date}; "
            f"harvests run {first.harvest_start} to {last.harvest_end}."
        )
    return tuple(lines)


def _build_item(
    index: int, item: ItemInput, plan: PlanInput
) -> tuple[ItemResult, Economics, tuple[BatchSchedule, ...]]:
    e = compute_economics(item)
    batches = batch_schedules(item)
    breakdown = {k: q(v, MONEY) for k, v in e.breakdown.items()}
    result = ItemResult(
        index=index,
        crop_name=item.crop_name,
        area_acres=item.area_acres,
        batches=batches,
        cost_per_acre=q(e.cost_per_acre, MONEY),
        cost=Triple(q(e.cost_expected, MONEY), q(e.cost_expected, MONEY), q(e.cost_high, MONEY)),
        cost_breakdown=breakdown,
        overrun_pct=q(e.overrun_pct, PCT),
        production_kg=qt(e.production, QTY),
        sold_kg=qt(e.sold, QTY),
        demand_limited=e.demand_limited,
        revenue=qt(e.revenue, MONEY),
        margin=qt(e.margin, MONEY),
        roi_expected_pct=q(e.roi_pct, PCT) if e.roi_pct is not None else None,
        break_even=BreakEven(
            price_per_kg_expected=q(e.be_price_expected, MONEY),
            price_per_kg_conservative=(
                q(e.be_price_conservative, MONEY) if e.be_price_conservative is not None else None
            ),
            yield_kg_per_acre=q(e.be_yield_per_acre, QTY),
            margin_of_safety_pct=q(e.margin_of_safety_pct, PCT),
        ),
        risk=scoring.item_risk(item, e, plan.season),
        confidence=scoring.item_confidence(item),
        explanations=_item_explanations(item, e, batches),
    )
    return result, e, batches


# ============================================================ plan assembly


def _sum_triples(triples: Sequence[Triple]) -> Triple:
    return Triple(
        sum((t.low for t in triples), ZERO),
        sum((t.expected for t in triples), ZERO),
        sum((t.high for t in triples), ZERO),
    )


def _resource(required: Decimal, available: Decimal | None, missing: int) -> ResourceUse:
    return ResourceUse(
        required=q(required, QTY),
        available=available,
        headroom=q(available - required, QTY) if available is not None else None,
        utilization_pct=q(required / available * HUNDRED, PCT) if available is not None else None,
        items_without_estimate=missing,
    )


def _findings(
    plan: PlanInput,
    items: Sequence[ItemInput],
    results: Sequence[ItemResult],
    peak: Decimal,
    first_over: object,
    expected_cost: Decimal,
    high_cost: Decimal,
    water_required: Decimal,
    labour_required: Decimal,
    gap_months: Sequence[str],
) -> list[Finding]:
    out: list[Finding] = []
    hard, warn = FindingSeverity.HARD, FindingSeverity.WARNING

    if peak > plan.available_land_acres:
        out.append(
            Finding(
                "land_exceeded",
                hard,
                f"The crops need up to {num(peak, 3)} acres at the same time but only "
                f"{num(plan.available_land_acres, 3)} acres are available (first exceeded on {first_over}). "
                "Reduce areas or move sowing dates so crops do not overlap.",
                details={"peak_acres": float(peak), "available_acres": float(plan.available_land_acres)},
            )
        )
    if plan.budget_inr is not None:
        if expected_cost > plan.budget_inr:
            out.append(
                Finding(
                    "budget_exceeded",
                    hard,
                    f"Expected cost {inr(expected_cost)} is more than the budget {inr(plan.budget_inr)}.",
                    details={"expected_cost": float(expected_cost), "budget": float(plan.budget_inr)},
                )
            )
        elif high_cost > plan.budget_inr:
            out.append(
                Finding(
                    "budget_at_risk",
                    warn,
                    f"Expected cost {inr(expected_cost)} fits the budget {inr(plan.budget_inr)}, but a cost overrun "
                    f"(up to {inr(high_cost)}) would not.",
                    details={"high_cost": float(high_cost), "budget": float(plan.budget_inr)},
                )
            )
    if plan.available_water_kl is not None and water_required > plan.available_water_kl:
        out.append(
            Finding(
                "water_exceeded",
                warn,
                f"Estimated water need {num(water_required, 1)} kL is more than the {num(plan.available_water_kl, 1)} kL available.",
                details={"required_kl": float(water_required), "available_kl": float(plan.available_water_kl)},
            )
        )
    if plan.available_labour_person_days is not None and labour_required > plan.available_labour_person_days:
        out.append(
            Finding(
                "labour_exceeded",
                warn,
                f"Estimated labour {num(labour_required, 1)} person-days is more than the "
                f"{num(plan.available_labour_person_days, 1)} available.",
                details={"required": float(labour_required), "available": float(plan.available_labour_person_days)},
            )
        )

    for item, r in zip(items, results, strict=True):
        if r.demand_limited:
            out.append(
                Finding(
                    "demand_exceeded",
                    warn,
                    f"{r.crop_name}: expected production ({num(r.production_kg.expected, 0)} kg) is more than the demand "
                    f"you entered ({num(item.demand_quantity_kg or ZERO, 0)} kg); the surplus is not counted as revenue.",
                    item_index=r.index,
                )
            )
        if r.margin.expected < 0:
            out.append(
                Finding(
                    "expected_loss",
                    warn,
                    f"{r.crop_name}: the expected margin is negative ({inr(r.margin.expected)}).",
                    item_index=r.index,
                )
            )
        elif r.margin.low < 0:
            out.append(
                Finding(
                    "loss_possible",
                    warn,
                    f"{r.crop_name}: the pessimistic case loses money ({inr(r.margin.low)}), although the expected margin is positive.",
                    item_index=r.index,
                )
            )
        outside, mismatch = scoring.season_fit_issues(item, plan.season)
        if outside:
            out.append(
                Finding(
                    "sowing_outside_season",
                    warn,
                    f"{r.crop_name}: a sowing date falls outside the usual {plan.season.value} sowing months.",
                    item_index=r.index,
                )
            )
        if mismatch:
            out.append(
                Finding(
                    "crop_season_mismatch",
                    warn,
                    f"{r.crop_name}: the catalog lists it as a {item.crop_season.value if item.crop_season else ''} crop, "
                    f"but the plan season is {plan.season.value}.",
                    item_index=r.index,
                )
            )

    if gap_months:
        out.append(
            Finding(
                "income_gap",
                warn,
                f"No income is expected in {len(gap_months)} month(s) between harvests: {', '.join(gap_months)}.",
                details={"months": ", ".join(gap_months)},
            )
        )

    order = {FindingSeverity.HARD: 0, FindingSeverity.WARNING: 1}
    return sorted(out, key=lambda f: (order[f.severity], f.code, -1 if f.item_index is None else f.item_index))


def _plan_explanations(
    totals: PlanTotals,
    results: Sequence[ItemResult],
    land_peak_pct: Decimal,
    peak: Decimal,
    plan: PlanInput,
    continuity_level: ContinuityLevel,
    risk_score: RiskAssessment,
    confidence: ConfidenceAssessment,
    feasible: bool,
) -> tuple[str, ...]:
    top = max(risk_score.components, key=lambda c: c.weight * c.score)
    lines = [
        f"{len(results)} crop(s) over {num(totals.area_sown_acres, 3)} acres sown: estimated cost {inr(totals.cost.expected)} "
        f"(up to {inr(totals.cost.high)} if costs overrun).",
        f"Expected revenue {inr(totals.revenue.expected)}, plausible range {inr(totals.revenue.low)} to {inr(totals.revenue.high)}.",
        f"Expected margin {inr(totals.margin.expected)}; pessimistic {inr(totals.margin.low)}; optimistic {inr(totals.margin.high)}.",
    ]
    if totals.break_even_pct_of_expected_revenue is not None:
        lines.append(
            f"Break-even: {inr(totals.break_even_revenue)} of revenue covers the expected cost, which is "
            f"{num(totals.break_even_pct_of_expected_revenue, 0)}% of the expected revenue."
        )
    lines.append(
        f"Land: at most {num(peak, 3)} of {num(plan.available_land_acres, 3)} acres are in use at once ({num(land_peak_pct, 0)}%)."
    )
    lines.append(f"Income pattern: {continuity_level.value.replace('_', ' ')}.")
    lines.append(
        f"Risk is {risk_score.level.value} ({num(risk_score.score, 1)}/100); the biggest contributor is "
        f"'{top.name.replace('_', ' ')}'. Confidence in the inputs is {confidence.level.value} ({num(confidence.score, 1)}/100)."
    )
    lines.append(
        "This plan fits the land and budget you set."
        if feasible
        else "This plan does NOT fit the land or budget you set (see findings)."
    )
    return tuple(lines)


def evaluate_plan(plan: PlanInput) -> PlanResult:
    built = [_build_item(i, item, plan) for i, item in enumerate(plan.items)]
    results = [r for r, _, _ in built]
    econs = [e for _, e, _ in built]
    batches = [b for _, _, b in built]

    period = period_of(batches)
    occupancies = occupancies_of(batches)
    land = land_utilization(occupancies, plan.available_land_acres, period)
    continuity = income_continuity(plan.items, batches, econs, period)

    expected_cost = sum((e.cost_expected for e in econs), ZERO)
    high_cost = sum((e.cost_high for e in econs), ZERO)
    revenue = _sum_triples([e.revenue for e in econs])
    margin = Triple(revenue.low - high_cost, revenue.expected - expected_cost, revenue.high - expected_cost)

    totals = PlanTotals(
        area_sown_acres=sum((i.area_acres for i in plan.items), ZERO),
        cost=Triple(q(expected_cost, MONEY), q(expected_cost, MONEY), q(high_cost, MONEY)),
        revenue=qt(revenue, MONEY),
        margin=qt(margin, MONEY),
        roi_expected_pct=q(margin.expected / expected_cost * HUNDRED, PCT) if expected_cost > 0 else None,
        break_even_revenue=q(expected_cost, MONEY),
        break_even_pct_of_expected_revenue=q(expected_cost / revenue.expected * HUNDRED, PCT)
        if revenue.expected > 0
        else None,
        cover_ratio_expected=q(revenue.expected / expected_cost, PCT) if expected_cost > 0 else None,
        cover_ratio_pessimistic=q(revenue.low / high_cost, PCT) if high_cost > 0 else None,
    )

    budget = plan.budget_inr
    budget_summary = BudgetSummary(
        budget=budget,
        expected_cost=q(expected_cost, MONEY),
        high_cost=q(high_cost, MONEY),
        headroom_expected=q(budget - expected_cost, MONEY) if budget is not None else None,
        headroom_high=q(budget - high_cost, MONEY) if budget is not None else None,
        utilization_pct=q(expected_cost / budget * HUNDRED, PCT) if budget is not None else None,
    )

    water_required = sum(((i.water_kl_per_acre or ZERO) * i.area_acres for i in plan.items), ZERO)
    labour_required = sum((i.cost.labour_person_days_per_acre * i.area_acres for i in plan.items), ZERO)
    water = _resource(
        water_required, plan.available_water_kl, sum(1 for i in plan.items if i.water_kl_per_acre is None)
    )
    labour = _resource(labour_required, plan.available_labour_person_days, 0)

    # ---- plan risk
    cost_weights = [e.cost_expected for e in econs]
    crop_risk = scoring.weighted_average([r.risk.score for r in results], cost_weights)
    max_share = max(e.revenue.expected for e in econs) / revenue.expected * HUNDRED if revenue.expected > 0 else HUNDRED
    if continuity.level is ContinuityLevel.SINGLE_HARVEST:
        gap_points, gap_detail = Decimal(50), "All income lands in a single month."
    else:
        gap_points = scoring.clamp(Decimal(continuity.gap_months) / Decimal(continuity.span_months) * HUNDRED)
        gap_detail = f"{continuity.gap_months} of {continuity.span_months} month(s) between first and last harvest have no income."
    overuse = [
        (name, (req / avail - 1) * HUNDRED)
        for name, req, avail in (
            ("water", water_required, plan.available_water_kl),
            ("labour", labour_required, plan.available_labour_person_days),
        )
        if avail is not None and req > avail
    ]
    if overuse:
        worst_name, worst_pct = max(overuse, key=lambda t: t[1])
        resource_points = scoring.clamp(worst_pct * 2)
        resource_detail = f"{worst_name.capitalize()} need exceeds availability by {num(worst_pct, 0)}%."
    else:
        resource_points, resource_detail = (
            ZERO,
            "Water and labour needs are within what you stated (or none was stated).",
        )

    risk = scoring.plan_risk(
        crop_risk=crop_risk,
        max_revenue_share_pct=max_share,
        gap_points=gap_points,
        gap_detail=gap_detail,
        resource_points=resource_points,
        resource_detail=resource_detail,
    )
    confidence = scoring.plan_confidence([r.confidence.score for r in results], [e.revenue.expected for e in econs])

    findings = _findings(
        plan,
        plan.items,
        results,
        land.peak_in_use_acres,
        land.first_over_limit_on,
        expected_cost,
        high_cost,
        water_required,
        labour_required,
        continuity.gap_month_list,
    )
    feasible = not any(f.severity is FindingSeverity.HARD for f in findings)

    return PlanResult(
        period=period,
        totals=totals,
        land=land,
        budget=budget_summary,
        water=water,
        labour=labour,
        continuity=continuity,
        items=tuple(results),
        risk=risk,
        confidence=confidence,
        findings=tuple(findings),
        feasible=feasible,
        explanations=_plan_explanations(
            totals,
            results,
            land.peak_utilization_pct,
            land.peak_in_use_acres,
            plan,
            continuity.level,
            risk,
            confidence,
            feasible,
        ),
        assumptions=ASSUMPTIONS,
        disclaimer=DISCLAIMER,
    )
