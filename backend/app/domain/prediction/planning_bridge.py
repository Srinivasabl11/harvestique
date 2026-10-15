"""Turn a prediction into planning-engine inputs (yield range per acre, timing, estimate basis)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.core.enums import EstimateBasis, PredictionStatus
from app.domain.planning.models import Range
from app.domain.prediction.models import PredictionResult, SourceUse


@dataclass(frozen=True, slots=True)
class PlanningEstimate:
    yield_per_acre_kg: Range
    duration_days: int
    harvest_window_days: int
    estimate_basis: EstimateBasis


class PredictionNotUsable(ValueError):
    pass


def basis_from_sources(sources: tuple[SourceUse, ...]) -> EstimateBasis:
    used = {s.name for s in sources if s.used}
    if "farm_history" in used:
        return EstimateBasis.OWN_RECORDS
    if "farmer_estimate" in used:
        return EstimateBasis.LOCAL_KNOWLEDGE
    return EstimateBasis.ASSUMPTION  # reference yield only


def planning_estimate(pred: PredictionResult, sowing_date: date) -> PlanningEstimate:
    if pred.status is not PredictionStatus.OK or pred.yield_per_acre_kg is None:
        raise PredictionNotUsable("This prediction has no quantity estimate")
    y = pred.yield_per_acre_kg
    if y.p50 <= 0:
        raise PredictionNotUsable("The expected yield is zero")
    t = pred.timing
    duration = max(1, (t.start_p50 - sowing_date).days)
    window = max(1, min(365, (t.end_p90 - t.start_p50).days + 1))
    return PlanningEstimate(Range(y.p10, y.p50, y.p90), duration, window, basis_from_sources(pred.sources))
