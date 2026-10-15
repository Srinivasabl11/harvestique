"""Future-harvest matching: eligibility filters and an explainable, configurable allocation score."""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from app.core.enums import QualityGrade
from app.domain.pooling.models import ZERO, D, DemandSpec, Match, MatchSummary, Supply, Weights

GRADE_RANK = {QualityGrade.A: 3, QualityGrade.B: 2, QualityGrade.C: 1}
NEUTRAL = D(50)  # used when a component's data is unknown (stated in the reasons)


def haversine_km(lat1: Decimal, lon1: Decimal, lat2: Decimal, lon2: Decimal) -> Decimal:
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return D(str(round(2 * 6371.0 * math.asin(math.sqrt(a)), 3)))


def _q(x: Decimal) -> Decimal:
    return x.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def evaluate(supply: Supply, demand: DemandSpec, need_kg: Decimal, weights: Weights) -> Match:
    reasons: list[str] = []
    if supply.crop_id != demand.crop_id:
        reasons.append("crop_mismatch")
    if GRADE_RANK[supply.grade] < GRADE_RANK[demand.min_grade]:
        reasons.append("grade_below_minimum")
    if not supply.opted_in:
        reasons.append("not_opted_in")
    if not supply.lot_open:
        reasons.append("lot_not_open")
    if supply.available_kg <= 0:
        reasons.append("no_available_quantity")
    overlap = (min(supply.window_end, demand.window_end) - max(supply.window_start, demand.window_start)).days + 1
    if overlap <= 0:
        reasons.append("window_no_overlap")
    if supply.confidence < demand.min_confidence:
        reasons.append("confidence_below_minimum")
    if supply.risk is not None and supply.risk > demand.max_risk:
        reasons.append("risk_above_maximum")
    distance: Decimal | None = None
    if None not in (supply.latitude, supply.longitude, demand.latitude, demand.longitude):
        distance = haversine_km(supply.latitude, supply.longitude, demand.latitude, demand.longitude)  # type: ignore[arg-type]
    if demand.max_distance_km is not None:
        if distance is None:
            reasons.append("location_unknown")
        elif distance > demand.max_distance_km:
            reasons.append("too_far")

    lot_days = max(1, (supply.window_end - supply.window_start).days + 1)
    proximity = NEUTRAL
    if distance is not None and demand.max_distance_km:
        proximity = max(ZERO, (1 - distance / demand.max_distance_km) * 100)
    components = {
        "confidence": supply.confidence,
        "safety": NEUTRAL if supply.risk is None else 100 - supply.risk,
        "reliability": supply.reliability * 100,
        "window": max(ZERO, D(overlap) / D(lot_days) * 100),
        "proximity": proximity,
        "availability": min(D(1), supply.available_kg / need_kg) * 100 if need_kg > 0 else ZERO,
    }
    components = {k: _q(min(D(100), max(ZERO, v))) for k, v in components.items()}
    score = _q(sum((getattr(weights, k) * v for k, v in components.items()), ZERO))
    return Match(supply, not reasons, tuple(reasons), score, components, distance)


def rank(supplies: Sequence[Supply], demand: DemandSpec, need_kg: Decimal, weights: Weights) -> list[Match]:
    """All candidates, eligible first, best score first; ties broken by lot id (deterministic)."""
    matches = [evaluate(s, demand, need_kg, weights) for s in supplies]
    return sorted(matches, key=lambda m: (not m.eligible, -m.score, m.supply.lot_id))


REASON_TEXT = {
    "crop_mismatch": "a different crop",
    "grade_below_minimum": "expected grade below your minimum",
    "not_opted_in": "the farmer has not offered it to buyers",
    "lot_not_open": "no prediction yet, or the crop was abandoned",
    "no_available_quantity": "all of it is already committed",
    "window_no_overlap": "harvest dates do not fit your delivery window",
    "confidence_below_minimum": "prediction confidence below your minimum",
    "risk_above_maximum": "crop risk above your maximum",
    "location_unknown": "farm location unknown (you set a maximum distance)",
    "too_far": "farther than your maximum distance",
}
# what the BUYER can change to reach more supply, by the reason that excluded it (never a different crop silently)
_STEP_FOR_REASON = {
    "window_no_overlap": "revise_dates",
    "too_far": "widen_distance",
    "location_unknown": "widen_distance",
    "grade_below_minimum": "accept_lower_grade",
    "confidence_below_minimum": "relax_risk_limits",
    "risk_above_maximum": "relax_risk_limits",
}


def _kg(x: Decimal) -> str:
    return f"{x.quantize(D('0.001')).normalize():f} kg"


def summarize(need_kg: Decimal, matches: Sequence[Match], *, crop: str = "this crop") -> MatchSummary:
    """Full / partial / no supply for `need_kg`, the exact shortage, and why other lots were excluded.
    Only same-crop lots are ever passed in (the lot query filters by crop); a stray other crop still counts as
    excluded, never as supply."""
    eligible = [m for m in matches if m.eligible]
    eligible_kg = sum((m.supply.available_kg for m in eligible), ZERO)
    need = max(ZERO, need_kg)
    shortage = max(ZERO, need - eligible_kg)
    fulfilment = "full" if shortage == 0 else "partial" if eligible_kg > 0 else "none"
    excluded: dict[str, int] = {}
    for m in matches:
        for r in m.reasons if not m.eligible else ():
            excluded[r] = excluded.get(r, 0) + 1
    farms = len({m.supply.farm_ref for m in eligible})
    lines = [
        f"Only {crop} supply is considered; other crops are never matched.",
        f"Needed {_kg(need)}; eligible predicted supply {_kg(eligible_kg)} from {farms} "
        f"farm{'s' if farms != 1 else ''} (pessimistic p10 estimates, not harvested produce).",
    ]
    if fulfilment == "full":
        lines.append("The demand can be met in full from current predictions.")
    elif fulfilment == "partial":
        lines.append(f"Shortage {_kg(shortage)}: current predictions cannot cover the whole demand.")
    else:
        lines.append(
            f"No eligible {crop} supply: the whole {_kg(need)} is short."
            if matches
            else f"No farm has offered predicted {crop} supply yet: the whole {_kg(need)} is short."
        )
    if excluded:
        lines.append(
            "Excluded lots: "
            + "; ".join(
                f"{n} - {REASON_TEXT.get(r, r)}" for r, n in sorted(excluded.items(), key=lambda x: (-x[1], x[0]))
            )
            + "."
        )
    steps: list[str] = []
    if fulfilment != "none":
        steps.append("create_pool")
    if fulfilment != "full":
        steps.append("wait_for_supply")
        steps += sorted({_STEP_FOR_REASON[r] for r in excluded if r in _STEP_FOR_REASON})
        steps.append("choose_other_crop")  # only ever as the buyer's explicit choice
    return MatchSummary(fulfilment, need, eligible_kg, shortage, len(eligible), excluded, tuple(lines), tuple(steps))
