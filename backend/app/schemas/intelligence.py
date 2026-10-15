"""Intelligence DTOs: weather, predictions, feedback, calibration, inventory, risk."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.enums import (
    ConfidenceLevel,
    DataKind,
    DemandLevel,
    LotStatus,
    PredictionStatus,
    QualityGrade,
    ReservationStatus,
    RiskCategory,
    RiskLevel,
    WeatherKind,
    WeatherStatus,
)
from app.schemas.base import _AS_JSON_NUMBER, JsonNumber, LongText, StrictModel
from app.schemas.planning import CostIn, DemandKg, LabourDays, PriceRangeIn, WaterPerAcre, YieldRangeIn

QuantityKg = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3), _AS_JSON_NUMBER]
PositiveKg = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3), _AS_JSON_NUMBER]
BookingKey = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._:\-]+$")
]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------- weather


class WeatherDayOut(_Out):
    day: date
    kind: WeatherKind
    data_kind: DataKind
    tmin_c: JsonNumber
    tmax_c: JsonNumber
    rain_mm: JsonNumber


class FarmWeatherOut(BaseModel):
    farm_id: uuid.UUID
    status: WeatherStatus
    fetched_at: datetime | None
    note: str
    forecast: list[WeatherDayOut]
    recent: list[WeatherDayOut]


class WeatherCurrentOut(BaseModel):
    time: datetime
    temperature_c: float
    humidity_pct: float | None
    condition: str
    weather_code: int
    raining_now: bool = Field(description="The weather MODEL estimates rain right now; not a rain-gauge reading")
    precipitation_mm: float
    wind_kmh: float | None
    is_day: bool


class WeatherHourOut(BaseModel):
    time: datetime
    temperature_c: float | None
    rain_probability_pct: float | None
    precipitation_mm: float | None


class WeatherDayOutlookOut(BaseModel):
    day: date
    tmin_c: float
    tmax_c: float
    rain_mm: float
    rain_probability_pct: float | None
    condition: str


class WeatherNowOut(BaseModel):
    farm_id: uuid.UUID
    status: WeatherStatus
    fetched_at: datetime | None
    source: str
    current: WeatherCurrentOut | None
    next_hours: list[WeatherHourOut]
    days: list[WeatherDayOutlookOut]
    note: str


# --------------------------------------------------------------- predictions


class PredictionRequest(StrictModel):
    """All optional. Supplying them sharpens the yield estimate and lets more risk categories be assessed."""

    farmer_estimate_per_acre: YieldRangeIn | None = Field(default=None, description="Your own yield estimate (kg/acre)")
    price_per_kg: PriceRangeIn | None = None
    demand_quantity_kg: DemandKg | None = None
    labour_person_days_needed: LabourDays | None = None
    labour_person_days_available: LabourDays | None = None


class QuantilesOut(_Out):
    p10: JsonNumber
    p50: JsonNumber
    p90: JsonNumber


class TimingOut(_Out):
    start_p10: date
    start_p50: date
    start_p90: date
    end_p90: date
    spread_days: int


class ComponentOut(_Out):
    name: str
    score: JsonNumber
    weight: JsonNumber
    detail: str


class ConfidenceOut(_Out):
    score: JsonNumber
    level: ConfidenceLevel
    basis: str = Field(description="'heuristic' (rule-based) or 'calibrated' (backed by recorded outcomes)")
    components: list[ComponentOut]
    calibration_note: str


class FactorOut(_Out):
    name: str
    multiplier: JsonNumber
    kind: DataKind
    detail: str


class WideningOut(_Out):
    name: str
    amount: JsonNumber
    detail: str


class SourceOut(_Out):
    name: str
    kind: DataKind
    used: bool
    detail: str


class CategoryRiskOut(_Out):
    category: RiskCategory
    score: JsonNumber | None
    level: str
    reasons: list[str]
    data_kinds: list[DataKind]


class RiskReportOut(_Out):
    overall_score: JsonNumber | None
    overall_level: str
    assessed: int
    categories: list[CategoryRiskOut]
    note: str


class ChangeOut(BaseModel):
    previous_version: int
    p50_change_kg: JsonNumber | None
    p50_change_pct: JsonNumber | None
    start_p50_shift_days: int
    confidence_change: JsonNumber


class PredictionOut(BaseModel):
    """A versioned, immutable harvest prediction. ESTIMATE, never a guarantee."""

    id: uuid.UUID
    crop_cycle_id: uuid.UUID
    version: int
    created_at: datetime
    status: PredictionStatus
    model_name: str
    model_version: str
    output_kind: DataKind
    quantity_kg: QuantilesOut | None
    yield_per_acre_kg: QuantilesOut | None
    cv: JsonNumber | None
    timing: TimingOut
    confidence: ConfidenceOut
    risk: RiskReportOut
    factors: list[FactorOut]
    widenings: list[WideningOut]
    sources: list[SourceOut]
    warnings: list[str]
    explanations: list[str]
    weather_status: WeatherStatus
    calibration_profile_id: uuid.UUID | None
    change: ChangeOut | None
    disclaimer: str


# ------------------------------------------------------------------ feedback


class HarvestActualIn(StrictModel):
    quantity_kg: QuantityKg = Field(description="MEASURED harvested quantity (0 = total crop failure)")
    harvest_start_date: date | None = Field(
        default=None, description="Defaults to the crop cycle's actual harvest date"
    )


class HarvestCorrectionIn(StrictModel):
    """Fix a wrongly entered harvest. Allowed only before produce from it was received at a hub."""

    quantity_kg: QuantityKg
    harvest_start_date: date | None = None
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]


class HarvestActualOut(_Out):
    id: uuid.UUID
    crop_cycle_id: uuid.UUID
    quantity_kg: JsonNumber
    harvest_start_date: date
    data_kind: DataKind = DataKind.MEASURED
    created_at: datetime


class FeedbackOut(BaseModel):
    prediction_id: uuid.UUID
    prediction_version: int
    predicted: QuantilesOut
    actual_kg: JsonNumber
    signed_error_kg: JsonNumber
    abs_error_kg: JsonNumber
    abs_pct_error: JsonNumber | None
    within_interval: bool
    pinball_loss: JsonNumber
    date_error_days: int | None
    date_within_window: bool | None


class FeedbackReport(BaseModel):
    actual: HarvestActualOut | None
    feedback: list[FeedbackOut]
    note: str


class CalibrationOut(_Out):
    id: uuid.UUID
    scope: str
    crop_id: uuid.UUID | None
    version: int
    sample_size: int
    sufficient: bool
    coverage: JsonNumber | None
    mape: JsonNumber | None
    bias_factor: JsonNumber
    interval_scale: JsonNumber
    date_mae_days: JsonNumber | None
    note: str
    created_at: datetime


# ----------------------------------------------------------------- inventory


class ReservationIn(StrictModel):
    quantity_kg: PositiveKg
    booking_key: BookingKey = Field(
        description="Your unique reference for this booking; reusing it on the same lot is refused"
    )
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None


class ReservationOut(_Out):
    id: uuid.UUID
    lot_id: uuid.UUID
    quantity_kg: JsonNumber
    booking_key: str
    status: ReservationStatus
    note: str | None
    created_at: datetime
    updated_at: datetime


class LotOut(_Out):
    id: uuid.UUID
    crop_cycle_id: uuid.UUID
    prediction_id: uuid.UUID | None
    status: LotStatus
    p10_kg: JsonNumber | None
    p50_kg: JsonNumber | None
    p90_kg: JsonNumber | None
    actual_kg: JsonNumber | None
    committable_kg: JsonNumber
    committed_kg: JsonNumber
    available_kg: JsonNumber
    shortfall_kg: JsonNumber
    basis: str
    pool_eligible: bool = Field(description="The farmer offers this lot to buyer harvest pools")
    expected_grade: QualityGrade
    updated_at: datetime
    # which crop the lot is (filled by the inventory listing; None where a response does not look them up)
    crop_name: str | None = None
    plot_name: str | None = None
    farm_name: str | None = None
    sowing_date: date | None = None
    # buyer orders on this lot, split by the farmer's confirmation (filled by the inventory listing)
    awaiting_confirmation_kg: JsonNumber | None = Field(default=None, description="Ordered; you have not answered")
    confirmed_kg: JsonNumber | None = Field(default=None, description="You accepted; not yet delivered")
    fulfilled_kg: JsonNumber | None = Field(default=None, description="Delivered and accepted (measured)")


class LotDetail(LotOut):
    reservations: list[ReservationOut]


# ---------------------------------------------------------------------- risk


class CycleRiskOut(BaseModel):
    crop_cycle_id: uuid.UUID
    crop_name: str
    prediction_version: int
    risk: RiskReportOut


class FarmRiskOut(BaseModel):
    farm_id: uuid.UUID
    overall_score: JsonNumber | None
    overall_level: str
    worst_by_category: dict[str, JsonNumber | None]
    cycles: list[CycleRiskOut]
    note: str


# ----------------------------------------------------------- planning bridge


class PlanItemFromPrediction(StrictModel):
    prediction_id: uuid.UUID
    price_per_kg: PriceRangeIn
    cost: CostIn = Field(default_factory=CostIn)
    water_kl_per_acre: WaterPerAcre | None = None
    demand_level: DemandLevel = DemandLevel.MEDIUM
    demand_quantity_kg: DemandKg | None = None
    declared_risk: RiskLevel = RiskLevel.MEDIUM
    notes: LongText | None = None
