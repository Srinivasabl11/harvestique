"""Agricultural intelligence persistence: weather cache, versioned predictions, measured harvests,
feedback, versioned calibration profiles, and the virtual harvest inventory.

Predictions, feedback and calibration profiles are APPEND-ONLY: a new version is a new row; history is never
updated in place. The weather table is a cache (forecast rows are refreshed in place by design).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, false, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import LotStatus, PredictionStatus, QualityGrade, ReservationStatus, WeatherKind, WeatherStatus
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column

JSONType = JSON().with_variant(JSONB(), "postgresql")


class WeatherDaily(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "weather_daily"
    __table_args__ = (UniqueConstraint("lat_key", "lon_key", "day", "kind", name="uq_weather_daily_point_day_kind"),)

    lat_key: Mapped[Decimal] = mapped_column(Numeric(6, 2))  # rounded to ~1 km grid
    lon_key: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    day: Mapped[date]
    kind: Mapped[WeatherKind] = mapped_column(enum_column(WeatherKind, name="weather_kind", length=16))
    tmin_c: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    tmax_c: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    rain_mm: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    et0_mm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    source: Mapped[str] = mapped_column(String(40))
    fetched_at: Mapped[datetime]


class YieldPrediction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "yield_predictions"
    __table_args__ = (
        UniqueConstraint("crop_cycle_id", "version", name="uq_yield_predictions_cycle_version"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "(p50_kg IS NULL) OR (p10_kg >= 0 AND p10_kg <= p50_kg AND p50_kg <= p90_kg)", name="quantiles_ordered"
        ),
        CheckConstraint(
            "harvest_start_p10 <= harvest_start_p50 AND harvest_start_p50 <= harvest_start_p90", name="dates_ordered"
        ),
        CheckConstraint("confidence_score BETWEEN 0 AND 100", name="confidence_range"),
    )

    crop_cycle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_cycles.id", ondelete="RESTRICT"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[PredictionStatus] = mapped_column(enum_column(PredictionStatus, name="prediction_status", length=24))
    model_name: Mapped[str] = mapped_column(String(40))
    model_version: Mapped[str] = mapped_column(String(20))
    p10_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    p50_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    p90_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    harvest_start_p10: Mapped[date]
    harvest_start_p50: Mapped[date]
    harvest_start_p90: Mapped[date]
    harvest_end_p90: Mapped[date]
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(4, 1))
    confidence_level: Mapped[str] = mapped_column(String(16))
    confidence_basis: Mapped[str] = mapped_column(String(16))
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    risk_level: Mapped[str] = mapped_column(String(20))
    weather_status: Mapped[WeatherStatus] = mapped_column(enum_column(WeatherStatus, name="weather_status", length=16))
    calibration_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calibration_profiles.id", ondelete="RESTRICT")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)  # full explainable result, risk, sources, change
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class HarvestActual(UUIDPrimaryKeyMixin, Base):
    """A MEASURED harvest, recorded by the farmer. One per crop cycle."""

    __tablename__ = "harvest_actuals"
    __table_args__ = (CheckConstraint("quantity_kg >= 0", name="quantity_non_negative"),)

    crop_cycle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_cycles.id", ondelete="RESTRICT"), unique=True)
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    harvest_start_date: Mapped[date]
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # A correction (allowed only before any produce from this harvest reached a hub) keeps an audit trail.
    previous_quantity_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    corrected_at: Mapped[datetime | None]
    correction_reason: Mapped[str | None] = mapped_column(String(255))


class ProduceGrading(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The farmer's A/B/C quality grade of one recorded harvest (domain.produce_grading), with its evidence.

    An AI photo proposal (optional) and the farmer's confirmed ratings are kept side by side, so a correction of the
    AI is visible. `grade` is set only when every check of the profile was rated and the farmer confirmed it; it may
    be lower than the ratings support (with a reason), never higher. Locked once produce reached a collection hub,
    whose measured quality check then decides."""

    __tablename__ = "produce_gradings"
    __table_args__ = (
        CheckConstraint("(grade IS NULL) = (confirmed_at IS NULL)", name="grade_iff_confirmed"),
        CheckConstraint("(grade IS NULL) = (criteria_grade IS NULL)", name="criteria_grade_with_grade"),
        CheckConstraint("grade IS NULL OR grade >= criteria_grade", name="grade_not_above_criteria"),
        CheckConstraint(
            "grade_source IS NULL OR grade_source IN ('manual', 'photo_confirmed', 'photo_corrected')",
            name="grade_source_known",
        ),
        CheckConstraint(
            "proposal_status IS NULL OR proposal_status IN "
            "('proposed', 'needs_more_evidence', 'retake_photo', 'unavailable')",
            name="proposal_status_known",
        ),
    )

    harvest_actual_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("harvest_actuals.id", ondelete="RESTRICT"), unique=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    profile: Mapped[str] = mapped_column(String(16))  # fresh | dry (domain.produce_grading.PROFILES)
    criteria_version: Mapped[int] = mapped_column(Integer)
    # latest AI photo proposal (photo itself not stored: only its SHA-256 in proposal_details)
    proposal_status: Mapped[str | None] = mapped_column(String(24))
    proposal_reason: Mapped[str | None] = mapped_column(String(40))
    proposed_levels: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    proposed_grade: Mapped[QualityGrade | None] = mapped_column(
        enum_column(QualityGrade, name="proposed_grade", length=2)
    )
    proposal_details: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    proposed_at: Mapped[datetime | None]
    # the farmer's confirmed grade
    levels: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    criteria_grade: Mapped[QualityGrade | None] = mapped_column(
        enum_column(QualityGrade, name="criteria_grade", length=2)
    )
    grade: Mapped[QualityGrade | None] = mapped_column(enum_column(QualityGrade, name="produce_grade", length=2))
    grade_source: Mapped[str | None] = mapped_column(String(16))
    override_reason: Mapped[str | None] = mapped_column(String(255))
    confirmed_at: Mapped[datetime | None]
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class PredictionFeedback(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "prediction_feedback"

    prediction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("yield_predictions.id", ondelete="RESTRICT"), unique=True
    )
    harvest_actual_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("harvest_actuals.id", ondelete="RESTRICT"), index=True
    )
    signed_error_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    abs_error_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    abs_pct_error: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    within_interval: Mapped[bool]
    pinball_loss: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    date_error_days: Mapped[int | None]
    date_within_window: Mapped[bool | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CalibrationProfile(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "calibration_profiles"
    __table_args__ = (
        UniqueConstraint("scope", "version", name="uq_calibration_profiles_scope_version"),
        CheckConstraint("sample_size >= 0", name="sample_size_non_negative"),
        CheckConstraint("bias_factor > 0 AND interval_scale > 0", name="factors_positive"),
    )

    scope: Mapped[str] = mapped_column(String(64))  # "global" or "crop:<uuid>"
    crop_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crops.id", ondelete="RESTRICT"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    sample_size: Mapped[int] = mapped_column(Integer)
    sufficient: Mapped[bool]
    coverage: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    mape: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    bias_factor: Mapped[Decimal] = mapped_column(Numeric(6, 4))
    interval_scale: Mapped[Decimal] = mapped_column(Numeric(6, 4))
    date_mae_days: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class InventoryLot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The virtual (not yet harvested) inventory of one crop cycle."""

    __tablename__ = "inventory_lots"
    __table_args__ = (
        CheckConstraint(
            "committable_kg >= 0 AND committed_kg >= 0 AND available_kg >= 0 AND shortfall_kg >= 0",
            name="quantities_non_negative",
        ),
    )

    crop_cycle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_cycles.id", ondelete="RESTRICT"), unique=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    prediction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("yield_predictions.id", ondelete="RESTRICT"))
    status: Mapped[LotStatus] = mapped_column(enum_column(LotStatus, name="lot_status", length=16))
    p10_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    p50_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    p90_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    actual_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    committable_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    committed_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    available_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    shortfall_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    basis: Mapped[str] = mapped_column(String(80))
    # Phase 5: a farmer must opt a lot in before any buyer pool can use it
    pool_eligible: Mapped[bool] = mapped_column(default=False, server_default=false())
    expected_grade: Mapped[QualityGrade] = mapped_column(
        enum_column(QualityGrade, name="expected_grade", length=2), default=QualityGrade.B, server_default="B"
    )


class InventoryReservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "inventory_reservations"
    __table_args__ = (
        UniqueConstraint("lot_id", "booking_key", name="uq_inventory_reservations_lot_id_booking_key"),
        CheckConstraint("quantity_kg > 0", name="quantity_positive"),
    )

    lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_lots.id", ondelete="RESTRICT"), index=True)
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    booking_key: Mapped[str] = mapped_column(String(80))  # idempotency/booking reference: one use per lot
    status: Mapped[ReservationStatus] = mapped_column(
        enum_column(ReservationStatus, name="reservation_status", length=16), default=ReservationStatus.ACTIVE
    )
    note: Mapped[str | None] = mapped_column(String(255))


class MarketPrice(UUIDPrimaryKeyMixin, Base):
    """AGMARKNET mandi prices fetched from data.gov.in (which only serves the current day): kept so the latest
    AVAILABLE price can be shown with its reporting date. INR per quintal, as reported. A cache, not farm data."""

    __tablename__ = "market_prices"
    __table_args__ = (
        UniqueConstraint(
            "state",
            "district",
            "market",
            "commodity",
            "variety",
            "grade",
            "arrival_date",
            name="uq_market_prices_report",
        ),
        CheckConstraint(
            "min_price > 0 AND min_price <= modal_price AND modal_price <= max_price", name="prices_ordered"
        ),
    )

    state: Mapped[str] = mapped_column(String(60), index=True)
    district: Mapped[str] = mapped_column(String(80))
    market: Mapped[str] = mapped_column(String(120))
    commodity: Mapped[str] = mapped_column(String(80), index=True)
    variety: Mapped[str] = mapped_column(String(80))
    grade: Mapped[str] = mapped_column(String(40))
    arrival_date: Mapped[date]
    min_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    modal_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    max_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    source: Mapped[str] = mapped_column(String(40))
    fetched_at: Mapped[datetime]
