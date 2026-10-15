"""Farm Risk Engine: nine categories, each scored 0-100 from explicit rules, or NOT ASSESSED.

A category with no data is reported as `insufficient_data` with score None. It is never guessed and is
excluded from the overall score (the report states how many categories were assessed).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.core.enums import DataKind, HealthStatus, IrrigationType, PredictionStatus, RiskCategory, WeatherStatus
from app.domain.planning.models import Range
from app.domain.prediction.models import CategoryRisk, ObservationFact, PredictionInput, PredictionResult, RiskReport
from app.domain.weather import EXTREME_HEAT_C, HEAVY_RAIN_MM, summarize

D = Decimal
ZERO = Decimal(0)
LOW_FROM, HIGH_FROM = D(35), D(65)  # same bands as the planning engine


@dataclass(frozen=True, slots=True)
class MarketContext:
    """Optional inputs the farmer may supply; categories without them stay unassessed."""

    price_per_kg: Range | None = None
    demand_quantity_kg: Decimal | None = None
    labour_person_days_needed: Decimal | None = None
    labour_person_days_available: Decimal | None = None
    committed_kg: Decimal = ZERO  # active + fulfilled inventory reservations


def _level(score: Decimal | None) -> str:
    if score is None:
        return "insufficient_data"
    return "high" if score >= HIGH_FROM else "medium" if score >= LOW_FROM else "low"


def _cat(cat: RiskCategory, score: Decimal | None, reasons: list[str], kinds: tuple[DataKind, ...]) -> CategoryRisk:
    s = None if score is None else max(D(0), min(D(100), score)).quantize(D("0.1"))
    return CategoryRisk(cat, s, _level(s), tuple(reasons), kinds)


def assess(inp: PredictionInput, pred: PredictionResult, market: MarketContext | None = None) -> RiskReport:
    m = market or MarketContext()
    today, w = inp.today, inp.weather
    out: list[CategoryRisk] = []
    observed = (
        summarize(w.observed, inp.cycle.sowing_date, today - timedelta(days=1))
        if today > inp.cycle.sowing_date
        else None
    )
    weather_ok = w.status is not WeatherStatus.UNAVAILABLE

    # WEATHER
    if weather_ok:
        fc_heat = sum(1 for d in w.forecast if d.tmax_c >= EXTREME_HEAT_C)
        fc_rain = sum(1 for d in w.forecast if d.rain_mm >= HEAVY_RAIN_MM)
        heat = observed.heat_stress_days if observed else 0
        heavy = observed.heavy_rain_days if observed else 0
        score = D(min(40, heat * 4) + min(30, heavy * 10) + min(30, (fc_heat + fc_rain) * 10))
        reasons = [
            f"{heat} heat-stress and {heavy} heavy-rain day(s) so far; {fc_heat} extreme-heat and {fc_rain} heavy-rain day(s) forecast."
        ]
        if w.status is WeatherStatus.STALE:
            reasons.append("Weather data is stale.")
        out.append(_cat(RiskCategory.WEATHER, score, reasons, (DataKind.MEASURED, DataKind.ESTIMATE)))
    else:
        out.append(_cat(RiskCategory.WEATHER, None, ["No weather data."], ()))

    # DISEASE
    recent = [o for o in inp.observations if 0 <= (today - o.observed_on).days <= 30]
    if recent:
        latest: ObservationFact = max(recent, key=lambda o: o.observed_on)
        pts = {
            HealthStatus.HEALTHY: 10,
            HealthStatus.STRESSED: 40,
            HealthStatus.PEST_AFFECTED: 70,
            HealthStatus.DISEASE_AFFECTED: 75,
            HealthStatus.DAMAGED: 85,
        }
        score = D(pts[latest.health_status]) + (latest.estimated_loss_percent or D(0)) / 2
        out.append(
            _cat(
                RiskCategory.DISEASE,
                score,
                [f"Latest observation {latest.observed_on}: {latest.health_status.value}."],
                (DataKind.MEASURED,),
            )
        )
    else:
        out.append(_cat(RiskCategory.DISEASE, None, ["No field observation in the last 30 days."], ()))

    # WATER
    irrigated = inp.cycle.irrigation is not None and inp.cycle.irrigation is not IrrigationType.RAINFED
    if weather_ok and observed and observed.days_with_data >= 7 and inp.crop.water_need_mm:
        duration = max(1, (pred.timing.start_p50 - inp.cycle.sowing_date).days)
        need = inp.crop.water_need_mm * D(min(observed.days_expected, duration)) / D(duration)
        ratio = observed.rain_mm / need if need > 0 else D(1)
        deficit = max(D(0), 1 - ratio) * 100
        score = deficit * (D("0.3") if irrigated else D(1)) + D(observed.longest_dry_spell_days)
        out.append(
            _cat(
                RiskCategory.WATER,
                score,
                [
                    f"Rain is {int(ratio * 100)}% of need so far; longest dry spell {observed.longest_dry_spell_days} days; {'irrigated' if irrigated else 'rainfed or unknown irrigation'}."
                ],
                (DataKind.MEASURED,),
            )
        )
    else:
        out.append(_cat(RiskCategory.WATER, None, ["Needs weather data and the crop's water need."], ()))

    # YIELD
    if pred.status is PredictionStatus.OK and pred.cv is not None:
        loss = D(1)
        for f in pred.factors:
            loss *= f.multiplier
        score = pred.cv * 150 + (1 - min(D(1), loss)) * 100
        out.append(
            _cat(
                RiskCategory.YIELD,
                score,
                [f"Prediction spread (CV) {pred.cv}; adjustments total x{loss.quantize(D('0.01'))}."],
                (DataKind.ESTIMATE,),
            )
        )
    else:
        out.append(_cat(RiskCategory.YIELD, None, ["No quantity prediction."], ()))

    # MARKET
    if m.price_per_kg is not None:
        out.append(
            _cat(
                RiskCategory.MARKET,
                m.price_per_kg.spread * 100,
                [f"Price range is {int(m.price_per_kg.spread * 100)}% of the expected price wide."],
                (DataKind.ESTIMATE,),
            )
        )
    else:
        out.append(_cat(RiskCategory.MARKET, None, ["No price range supplied."], ()))

    # DEMAND
    if m.demand_quantity_kg is not None and pred.quantity_kg is not None:
        ratio = pred.quantity_kg.p50 / m.demand_quantity_kg
        out.append(
            _cat(
                RiskCategory.DEMAND,
                max(D(0), (ratio - D("0.8")) * 150),
                [f"Expected supply is {int(ratio * 100)}% of the stated demand."],
                (DataKind.ESTIMATE,),
            )
        )
    else:
        out.append(_cat(RiskCategory.DEMAND, None, ["No demand quantity supplied."], ()))

    # LABOUR
    if m.labour_person_days_needed is not None and m.labour_person_days_available:
        ratio = m.labour_person_days_needed / m.labour_person_days_available
        out.append(
            _cat(
                RiskCategory.LABOUR,
                max(D(0), (ratio - D("0.7")) * 200),
                [f"Labour need is {int(ratio * 100)}% of what is available."],
                (DataKind.ESTIMATE,),
            )
        )
    else:
        out.append(_cat(RiskCategory.LABOUR, None, ["No labour need/availability supplied."], ()))

    # TIMING
    t = pred.timing
    score = D(t.spread_days) * 2
    reasons = [f"Harvest start uncertain by +/-{t.spread_days} days."]
    if inp.cycle.expected_harvest_date:
        delay = (t.start_p50 - inp.cycle.expected_harvest_date).days
        score += abs(delay) * 3
        reasons.append(f"Predicted start is {delay:+d} day(s) from your expected date.")
    out.append(_cat(RiskCategory.TIMING, score, reasons, (DataKind.ESTIMATE,)))

    # FULFILMENT
    if pred.quantity_kg is None:
        out.append(_cat(RiskCategory.FULFILMENT, None, ["No quantity prediction to compare commitments with."], ()))
    else:
        q, c = pred.quantity_kg, m.committed_kg
        if c <= 0:
            score, why = D(0), "Nothing is committed from this crop."
        elif c <= q.p10:
            score, why = D(15), "Commitments are within the pessimistic (p10) quantity."
        elif c <= q.p50:
            score, why = D(50), "Commitments exceed p10: a poor harvest could not cover them."
        else:
            score, why = D(85), "Commitments exceed the expected (p50) quantity."
        out.append(
            _cat(
                RiskCategory.FULFILMENT,
                score,
                [why, f"Committed {c} kg vs p10 {q.p10} / p50 {q.p50} kg."],
                (DataKind.MEASURED, DataKind.ESTIMATE),
            )
        )

    scored = [c.score for c in out if c.score is not None]
    overall = (sum(scored, D(0)) / len(scored)).quantize(D("0.1")) if scored else None
    return RiskReport(
        overall_score=overall,
        overall_level=_level(overall),
        assessed=len(scored),
        categories=tuple(out),
        note=f"{len(scored)} of {len(out)} categories assessed; unassessed categories are excluded, not guessed.",
    )


def days_until(day: date, today: date) -> int:
    return (day - today).days
