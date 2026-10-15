"""Value objects for prediction, risk and calibration (pure)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.core.enums import (
    ConfidenceLevel,
    CropCategory,
    CycleStatus,
    DataKind,
    GrowthStage,
    HealthStatus,
    IrrigationType,
    PredictionStatus,
    RiskCategory,
)
from app.domain.planning.models import Component, Range
from app.domain.weather import WeatherContext


class NotPredictableError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ------------------------------------------------------------------ inputs


@dataclass(frozen=True, slots=True)
class CropProfile:
    name: str
    category: CropCategory
    typical_duration_days: int
    reference_yield_kg_per_acre: Decimal | None = None
    reference_yield_cv: Decimal | None = None
    water_need_mm: Decimal | None = None  # season total


@dataclass(frozen=True, slots=True)
class CycleFacts:
    area_acres: Decimal
    sowing_date: date
    status: CycleStatus
    expected_harvest_date: date | None = None  # the farmer's own estimate
    irrigation: IrrigationType | None = None


@dataclass(frozen=True, slots=True)
class PastHarvest:
    """A recorded (measured) harvest of the same crop on the same farmer's land."""

    yield_kg_per_acre: Decimal
    harvest_date: date


@dataclass(frozen=True, slots=True)
class ObservationFact:
    observed_on: date
    health_status: HealthStatus
    growth_stage: GrowthStage | None = None
    estimated_loss_percent: Decimal | None = None


@dataclass(frozen=True, slots=True)
class CalibrationFacts:
    sample_size: int
    sufficient: bool
    coverage: Decimal | None  # share of past actuals inside p10-p90
    bias_factor: Decimal  # median(actual / p50); 1 when not sufficient
    interval_scale: Decimal  # multiplies the uncertainty; 1 when not sufficient
    date_mae_days: Decimal | None
    reference: str  # which profile (scope/version) this came from


@dataclass(frozen=True, slots=True)
class PredictionInput:
    crop: CropProfile
    cycle: CycleFacts
    today: date
    history: tuple[PastHarvest, ...] = ()
    observations: tuple[ObservationFact, ...] = ()
    weather: WeatherContext = field(default_factory=lambda: WeatherContext.unavailable("no weather requested"))
    farmer_estimate: Range | None = None  # per acre
    calibration: CalibrationFacts | None = None


# ----------------------------------------------------------------- outputs


@dataclass(frozen=True, slots=True)
class Quantiles:
    p10: Decimal
    p50: Decimal
    p90: Decimal


@dataclass(frozen=True, slots=True)
class HarvestTiming:
    start_p10: date
    start_p50: date
    start_p90: date
    end_p90: date  # latest plausible end of harvest
    spread_days: int


@dataclass(frozen=True, slots=True)
class Factor:
    name: str
    multiplier: Decimal
    kind: DataKind
    detail: str


@dataclass(frozen=True, slots=True)
class Widening:
    name: str
    amount: Decimal  # added to the coefficient of variation
    detail: str


@dataclass(frozen=True, slots=True)
class SourceUse:
    name: str
    kind: DataKind
    used: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PredictionConfidence:
    score: Decimal
    level: ConfidenceLevel
    basis: str  # "heuristic" or "calibrated"
    components: tuple[Component, ...]
    calibration_note: str


@dataclass(frozen=True, slots=True)
class PredictionResult:
    status: PredictionStatus
    model_name: str
    model_version: str
    quantity_kg: Quantiles | None
    yield_per_acre_kg: Quantiles | None
    cv: Decimal | None
    timing: HarvestTiming
    confidence: PredictionConfidence
    factors: tuple[Factor, ...]
    widenings: tuple[Widening, ...]
    sources: tuple[SourceUse, ...]
    warnings: tuple[str, ...]
    explanations: tuple[str, ...]
    output_kind: DataKind = DataKind.ESTIMATE


# -------------------------------------------------------------------- risk


@dataclass(frozen=True, slots=True)
class CategoryRisk:
    category: RiskCategory
    score: Decimal | None  # None = not assessed (insufficient data), never guessed
    level: str  # low / medium / high / insufficient_data
    reasons: tuple[str, ...]
    data_kinds: tuple[DataKind, ...]


@dataclass(frozen=True, slots=True)
class RiskReport:
    overall_score: Decimal | None
    overall_level: str
    assessed: int
    categories: tuple[CategoryRisk, ...]
    note: str
