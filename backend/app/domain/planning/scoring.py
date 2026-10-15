"""Risk and confidence scores: transparent weighted sums, never a black box.

RISK (0-100, higher = riskier) answers "how exposed is this money?".
CONFIDENCE (0-100, higher = better founded) answers "how much should I trust these *inputs*?".
Neither is a probability. Weights, point tables and thresholds are constants below and every
component is returned with its score, weight and a plain-language reason.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.core.enums import ConfidenceLevel, CropSeason, DemandLevel, EstimateBasis, RiskLevel
from app.domain.planning.calculator import HUNDRED, SCORE, Economics, batch_schedules, num, q
from app.domain.planning.models import (
    ZERO,
    Component,
    ConfidenceAssessment,
    D,
    ItemInput,
    RiskAssessment,
)

# ---------------------------------------------------------------- item risk

ITEM_RISK_WEIGHTS: dict[str, Decimal] = {
    "yield_uncertainty": D("0.25"),
    "price_uncertainty": D("0.20"),
    "loss_exposure": D("0.20"),
    "declared_risk": D("0.15"),
    "demand": D("0.10"),
    "season_fit": D("0.10"),
}
DECLARED_RISK_POINTS: dict[RiskLevel, Decimal] = {RiskLevel.LOW: D(15), RiskLevel.MEDIUM: D(50), RiskLevel.HIGH: D(85)}
DEMAND_POINTS: dict[DemandLevel, Decimal] = {DemandLevel.LOW: D(70), DemandLevel.MEDIUM: D(35), DemandLevel.HIGH: D(10)}
RISK_MEDIUM_FROM = D(35)  # score < 35 -> low
RISK_HIGH_FROM = D(65)  # score >= 65 -> high

# Plan-level risk = capital-weighted crop risk + how concentrated, gappy and resource-stretched the plan is.
PLAN_RISK_WEIGHTS: dict[str, Decimal] = {
    "crop_risk": D("0.65"),
    "concentration": D("0.15"),
    "income_gaps": D("0.10"),
    "resource_pressure": D("0.10"),
}

# ----------------------------------------------------------------- confidence

BASIS_POINTS: dict[EstimateBasis, Decimal] = {
    EstimateBasis.OWN_RECORDS: D(90),
    EstimateBasis.LOCAL_KNOWLEDGE: D(65),
    EstimateBasis.ASSUMPTION: D(35),
}
CONFIDENCE_WEIGHTS: dict[str, Decimal] = {
    "estimate_basis": D("0.4"),
    "range_tightness": D("0.4"),
    "completeness": D("0.2"),
}
CONFIDENCE_MEDIUM_FROM = D(45)
CONFIDENCE_HIGH_FROM = D(70)

# Sowing months per season. INDICATIVE only (Karnataka-style calendar); a mismatch is a warning, not an error.
SEASON_SOWING_MONTHS: dict[CropSeason, frozenset[int]] = {
    CropSeason.KHARIF: frozenset({6, 7, 8, 9}),
    CropSeason.RABI: frozenset({10, 11, 12, 1}),
    CropSeason.SUMMER: frozenset({2, 3, 4, 5}),
    CropSeason.YEAR_ROUND: frozenset(range(1, 13)),
}


def clamp(value: Decimal, low: Decimal = ZERO, high: Decimal = HUNDRED) -> Decimal:
    return max(low, min(high, value))


def risk_level(score: Decimal) -> RiskLevel:
    if score >= RISK_HIGH_FROM:
        return RiskLevel.HIGH
    return RiskLevel.MEDIUM if score >= RISK_MEDIUM_FROM else RiskLevel.LOW


def confidence_level(score: Decimal) -> ConfidenceLevel:
    if score >= CONFIDENCE_HIGH_FROM:
        return ConfidenceLevel.HIGH
    return ConfidenceLevel.MEDIUM if score >= CONFIDENCE_MEDIUM_FROM else ConfidenceLevel.LOW


# ------------------------------------------------------------------ season


def season_fit_issues(item: ItemInput, plan_season: CropSeason) -> tuple[bool, bool]:
    """(some batch is sown outside the plan season, the catalog crop belongs to a different season)."""
    if plan_season is CropSeason.YEAR_ROUND:
        return False, False
    months = SEASON_SOWING_MONTHS[plan_season]
    outside = any(b.sowing_date.month not in months for b in batch_schedules(item))
    crop = item.crop_season
    mismatch = crop is not None and crop not in (CropSeason.YEAR_ROUND, plan_season)
    return outside, mismatch


# ----------------------------------------------------------------- item risk


def item_risk(item: ItemInput, econ: Economics, plan_season: CropSeason) -> RiskAssessment:
    y_spread, p_spread = item.yield_per_acre_kg.spread, item.price_per_kg.spread
    yield_pts = clamp(y_spread * HUNDRED)
    price_pts = clamp(p_spread * HUNDRED)

    if econ.margin.low >= 0:
        loss_pts, loss_detail = ZERO, "Even the pessimistic case (lowest yield and price, highest cost) is not a loss."
    else:
        loss_pts = clamp(-econ.margin.low / econ.cost_high * HUNDRED)
        loss_detail = f"The pessimistic case loses {num(-econ.margin.low)}, which is {num(loss_pts, 1)}% of the high cost estimate."

    if econ.demand_limited:
        demand_pts, demand_detail = (
            HUNDRED,
            "Expected production exceeds the stated demand, so part of the crop may go unsold.",
        )
    else:
        demand_pts = DEMAND_POINTS[item.demand_level]
        demand_detail = f"Demand is rated {item.demand_level.value} ({num(demand_pts, 0)} points)."

    outside, mismatch = season_fit_issues(item, plan_season)
    if mismatch:
        season_pts, season_detail = (
            HUNDRED,
            f"This crop's usual season ({item.crop_season}) differs from the plan season ({plan_season}).",
        )
    elif outside:
        season_pts, season_detail = (
            D(60),
            f"At least one sowing date falls outside the {plan_season.value} sowing months.",
        )
    else:
        season_pts, season_detail = ZERO, "Sowing dates fit the plan season."

    raw = {
        "yield_uncertainty": (yield_pts, f"Yield range is {num(y_spread * HUNDRED, 0)}% of its expected value wide."),
        "price_uncertainty": (price_pts, f"Price range is {num(p_spread * HUNDRED, 0)}% of its expected value wide."),
        "loss_exposure": (loss_pts, loss_detail),
        "declared_risk": (
            DECLARED_RISK_POINTS[item.declared_risk],
            f"You rated this crop's risk as {item.declared_risk.value}.",
        ),
        "demand": (demand_pts, demand_detail),
        "season_fit": (season_pts, season_detail),
    }
    return _risk_from(raw, ITEM_RISK_WEIGHTS)


def _risk_from(raw: dict[str, tuple[Decimal, str]], weights: dict[str, Decimal]) -> RiskAssessment:
    components = tuple(Component(name, q(pts, SCORE), weights[name], detail) for name, (pts, detail) in raw.items())
    score = q(sum((weights[n] * pts for n, (pts, _) in raw.items()), ZERO), SCORE)
    return RiskAssessment(score=score, level=risk_level(score), components=components)


# ------------------------------------------------------------ item confidence


def item_confidence(item: ItemInput) -> ConfidenceAssessment:
    basis_pts = BASIS_POINTS[item.estimate_basis]
    avg_spread = (item.yield_per_acre_kg.spread + item.price_per_kg.spread) / 2
    tightness_pts = clamp(HUNDRED - avg_spread * HUNDRED)

    checks = {
        "linked to the crop catalog": item.has_catalog_crop,
        "labour estimate given": item.cost.labour_person_days_per_acre > 0,
        "water estimate given": item.water_kl_per_acre is not None,
        "demand quantity given": item.demand_quantity_kg is not None,
        "yield/price not a pure assumption": item.estimate_basis is not EstimateBasis.ASSUMPTION,
    }
    completeness_pts = D(20) * sum(1 for ok in checks.values() if ok)
    missing = [name for name, ok in checks.items() if not ok]

    raw = {
        "estimate_basis": (basis_pts, f"Numbers come from {item.estimate_basis.value.replace('_', ' ')}."),
        "range_tightness": (
            tightness_pts,
            f"Average yield/price range width is {num(avg_spread * HUNDRED, 0)}% of expected.",
        ),
        "completeness": (completeness_pts, "Complete." if not missing else "Missing: " + ", ".join(missing) + "."),
    }
    components = tuple(Component(n, q(pts, SCORE), CONFIDENCE_WEIGHTS[n], d) for n, (pts, d) in raw.items())
    score = q(sum((CONFIDENCE_WEIGHTS[n] * pts for n, (pts, _) in raw.items()), ZERO), SCORE)
    return ConfidenceAssessment(score=score, level=confidence_level(score), components=components)


# --------------------------------------------------------------- plan level


def weighted_average(values: Sequence[Decimal], weights: Sequence[Decimal]) -> Decimal:
    """Weighted mean; falls back to a plain mean when every weight is zero."""
    total = sum(weights, ZERO)
    if total == 0:
        return sum(values, ZERO) / len(values)
    return sum((v * w for v, w in zip(values, weights, strict=True)), ZERO) / total


def plan_risk(
    *,
    crop_risk: Decimal,
    max_revenue_share_pct: Decimal,
    gap_points: Decimal,
    gap_detail: str,
    resource_points: Decimal,
    resource_detail: str,
) -> RiskAssessment:
    raw = {
        "crop_risk": (crop_risk, "Crop risk scores weighted by the money invested in each crop."),
        "concentration": (
            max_revenue_share_pct,
            f"The largest crop provides {num(max_revenue_share_pct, 0)}% of expected revenue.",
        ),
        "income_gaps": (gap_points, gap_detail),
        "resource_pressure": (resource_points, resource_detail),
    }
    return _risk_from(raw, PLAN_RISK_WEIGHTS)


def plan_confidence(item_scores: Sequence[Decimal], revenue_weights: Sequence[Decimal]) -> ConfidenceAssessment:
    score = q(weighted_average(item_scores, revenue_weights), SCORE)
    detail = "Crop confidence scores weighted by each crop's expected revenue."
    return ConfidenceAssessment(
        score=score,
        level=confidence_level(score),
        components=(Component("revenue_weighted_crop_confidence", score, D(1), detail),),
    )
