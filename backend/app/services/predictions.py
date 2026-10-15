"""Future Harvest Prediction, Farm Risk and Prediction Feedback/Calibration use cases.

The service only GATHERS inputs (weather, recorded history, observations, calibration, commitments) and
PERSISTS outputs; all reasoning happens in the pure domain via the configured PredictionProvider.
Predictions are append-only: each call adds version N+1, older versions are never changed.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.config import Settings
from app.core.enums import ConfidenceLevel, CycleStatus, DataKind, PredictionStatus
from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.domain.planning.models import Range
from app.domain.prediction.calibration import Outcome, calibrate, feedback
from app.domain.prediction.models import (
    CalibrationFacts,
    CropProfile,
    CycleFacts,
    HarvestTiming,
    NotPredictableError,
    ObservationFact,
    PastHarvest,
    PredictionConfidence,
    PredictionInput,
    PredictionResult,
    Quantiles,
    SourceUse,
)
from app.domain.prediction.risk import MarketContext, assess
from app.models.crop import CropCycle
from app.models.farm import Farm, FarmPlot
from app.models.farm_records import CropObservation
from app.models.intelligence import CalibrationProfile, HarvestActual, PredictionFeedback, YieldPrediction
from app.providers.prediction.base import PredictionProvider
from app.repositories.crops import CropCycleRepository
from app.repositories.farms import FarmRepository
from app.repositories.intelligence import (
    ActualRepository,
    CalibrationRepository,
    FeedbackRepository,
    InventoryRepository,
    PredictionRepository,
)
from app.schemas.common import Page
from app.schemas.intelligence import (
    CalibrationOut,
    CycleRiskOut,
    FarmRiskOut,
    FeedbackOut,
    FeedbackReport,
    HarvestActualIn,
    HarvestActualOut,
    HarvestCorrectionIn,
    PredictionOut,
    PredictionRequest,
    QuantilesOut,
    RiskReportOut,
)
from app.services._common import conflict_on_integrity, to_jsonable
from app.services.inventory import InventoryService
from app.services.weather import WeatherService

DISCLAIMER = (
    "An estimate built from the data listed in `sources`. It does not guarantee any yield, harvest date or income."
)
GLOBAL_SCOPE = "global"


def crop_scope(crop_id: uuid.UUID) -> str:
    return f"crop:{crop_id}"


class PredictionService:
    def __init__(
        self,
        *,
        session: Session,
        predictions: PredictionRepository,
        actuals: ActualRepository,
        feedback: FeedbackRepository,
        calibration: CalibrationRepository,
        inventory: InventoryService,
        inventory_repo: InventoryRepository,
        weather: WeatherService,
        predictor: PredictionProvider,
        clock: Clock,
        settings: Settings,
        on_lot_changed: Callable[[uuid.UUID, str], object] | None = None,
    ) -> None:
        self._on_lot_changed = on_lot_changed
        self._session = session
        self._predictions = predictions
        self._actuals = actuals
        self._feedback = feedback
        self._calibration = calibration
        self._inventory = inventory
        self._inventory_repo = inventory_repo
        self._weather = weather
        self._predictor = predictor
        self._clock = clock
        self._min_samples = settings.calibration_min_samples

    # ------------------------------------------------------------ predictions

    def create(self, owner_id: uuid.UUID, cycle_id: uuid.UUID, payload: PredictionRequest) -> PredictionOut:
        cycle = self._predictions.lock_cycle(cycle_id, owner_id)
        if cycle is None:
            raise NotFoundError("Crop cycle not found")
        plot = self._session.get(FarmPlot, cycle.plot_id)
        farm = self._session.get(Farm, plot.farm_id) if plot else None
        assert plot is not None and farm is not None
        today = self._clock.now().date()

        crop = cycle.crop
        profile = self._calibration_for(crop.id)
        inp = PredictionInput(
            crop=CropProfile(
                crop.name,
                crop.category,
                crop.typical_duration_days,
                crop.reference_yield_kg_per_acre,
                crop.reference_yield_cv,
                crop.water_need_mm,
            ),
            cycle=CycleFacts(
                cycle.area_acres, cycle.sowing_date, cycle.status, cycle.expected_harvest_date, plot.irrigation_type
            ),
            today=today,
            history=tuple(
                PastHarvest(q / a, d) for q, a, d in self._actuals.history(owner_id, crop.id, cycle.id) if a > 0
            ),
            observations=self._observations(cycle.id),
            weather=self._weather.context(farm.latitude, farm.longitude, cycle.sowing_date),
            farmer_estimate=Range(
                payload.farmer_estimate_per_acre.low,
                payload.farmer_estimate_per_acre.expected,
                payload.farmer_estimate_per_acre.high,
            )
            if payload.farmer_estimate_per_acre
            else None,
            calibration=self._facts(profile),
        )
        try:
            result = self._predictor.predict(inp)
        except NotPredictableError as exc:
            raise ConflictError(exc.message, code=exc.code) from exc

        lot = self._inventory_repo.lot_for_cycle(cycle.id)
        committed = Decimal(0)
        if lot is not None:
            active, fulfilled = self._inventory_repo.totals(self._inventory_repo.reservations(lot.id))
            committed = active + fulfilled
        price = payload.price_per_kg
        risk = assess(
            inp,
            result,
            MarketContext(
                price_per_kg=Range(price.low, price.expected, price.high) if price else None,
                demand_quantity_kg=payload.demand_quantity_kg,
                labour_person_days_needed=payload.labour_person_days_needed,
                labour_person_days_available=payload.labour_person_days_available,
                committed_kg=committed,
            ),
        )
        previous = self._predictions.latest(cycle.id)
        q, t = result.quantity_kg, result.timing
        payload_json: dict[str, Any] = to_jsonable(result)
        payload_json["risk"] = to_jsonable(risk)
        payload_json["change"] = self._change(previous, result) if previous else None
        row = YieldPrediction(
            crop_cycle_id=cycle.id,
            version=(previous.version + 1) if previous else 1,
            status=result.status,
            model_name=result.model_name,
            model_version=result.model_version,
            p10_kg=q.p10 if q else None,
            p50_kg=q.p50 if q else None,
            p90_kg=q.p90 if q else None,
            harvest_start_p10=t.start_p10,
            harvest_start_p50=t.start_p50,
            harvest_start_p90=t.start_p90,
            harvest_end_p90=t.end_p90,
            confidence_score=result.confidence.score,
            confidence_level=result.confidence.level.value,
            confidence_basis=result.confidence.basis,
            risk_score=risk.overall_score,
            risk_level=risk.overall_level,
            weather_status=inp.weather.status,
            calibration_profile_id=profile.id if profile and profile.sufficient else None,
            payload=payload_json,
        )
        with conflict_on_integrity(
            self._session, "Another prediction was created at the same time; retry", "prediction_conflict"
        ):
            self._predictions.add(row)
            lot = self._inventory.sync_lot(cycle, owner_id)
            self._session.commit()
        self._notify(lot.id, f"prediction:{row.id}")
        return self.read(row)

    def _notify(self, lot_id: uuid.UUID, trigger_ref: str) -> None:
        """Phase 5 hook: pools using this lot detect shortages and reallocate (each pool atomically)."""
        if self._on_lot_changed is not None:
            self._on_lot_changed(lot_id, trigger_ref)

    def list_for_cycle(
        self, owner_id: uuid.UUID, cycle_id: uuid.UUID, *, limit: int, offset: int
    ) -> Page[PredictionOut]:
        self._require_cycle(owner_id, cycle_id)
        rows, total = self._predictions.list_for_cycle(cycle_id, limit=limit, offset=offset)
        return Page[PredictionOut](items=[self.read(r) for r in rows], total=total, limit=limit, offset=offset)

    def get(self, owner_id: uuid.UUID, prediction_id: uuid.UUID) -> PredictionOut:
        row = self._predictions.get_owned(prediction_id, owner_id)
        if row is None:
            raise NotFoundError("Prediction not found")
        return self.read(row)

    @staticmethod
    def read(row: YieldPrediction) -> PredictionOut:
        p = row.payload
        return PredictionOut.model_validate(
            {
                **{
                    k: p[k]
                    for k in (
                        "quantity_kg",
                        "yield_per_acre_kg",
                        "cv",
                        "timing",
                        "confidence",
                        "factors",
                        "widenings",
                        "sources",
                        "warnings",
                        "explanations",
                        "output_kind",
                        "risk",
                        "change",
                    )
                },
                "id": row.id,
                "crop_cycle_id": row.crop_cycle_id,
                "version": row.version,
                "created_at": row.created_at,
                "status": row.status,
                "model_name": row.model_name,
                "model_version": row.model_version,
                "weather_status": row.weather_status,
                "calibration_profile_id": row.calibration_profile_id,
                "disclaimer": DISCLAIMER,
            }
        )

    @staticmethod
    def domain_result(row: YieldPrediction) -> PredictionResult:
        """Rehydrate the parts of a stored prediction the planning bridge needs."""
        p = row.payload
        q = p["yield_per_acre_kg"]
        return PredictionResult(
            status=row.status,
            model_name=row.model_name,
            model_version=row.model_version,
            quantity_kg=None,
            yield_per_acre_kg=Quantiles(Decimal(q["p10"]), Decimal(q["p50"]), Decimal(q["p90"])) if q else None,
            cv=None,
            timing=HarvestTiming(
                row.harvest_start_p10,
                row.harvest_start_p50,
                row.harvest_start_p90,
                row.harvest_end_p90,
                p["timing"]["spread_days"],
            ),
            confidence=PredictionConfidence(
                row.confidence_score, ConfidenceLevel(row.confidence_level), row.confidence_basis, (), ""
            ),
            factors=(),
            widenings=(),
            sources=tuple(SourceUse(s["name"], DataKind(s["kind"]), s["used"], s["detail"]) for s in p["sources"]),
            warnings=(),
            explanations=(),
        )

    # ------------------------------------------------------------------ risk

    def farm_risk(self, owner_id: uuid.UUID, farm_id: uuid.UUID) -> FarmRiskOut:
        if FarmRepository(self._session).get_owned(farm_id, owner_id) is None:
            raise NotFoundError("Farm not found")
        cycles = self._predictions.latest_for_open_cycles(farm_id)
        rows = [
            CycleRiskOut(
                crop_cycle_id=c.id,
                crop_name=c.crop_name,
                prediction_version=p.version,
                risk=RiskReportOut.model_validate(p.payload["risk"]),
            )
            for c, p in cycles
        ]
        worst: dict[str, Decimal | None] = {}
        for r in rows:
            for cat in r.risk.categories:
                key = cat.category.value
                if cat.score is not None and (worst.get(key) is None or cat.score > (worst[key] or 0)):
                    worst[key] = cat.score
                worst.setdefault(key, None)
        scores = [r.risk.overall_score for r in rows if r.risk.overall_score is not None]
        overall = (sum(scores, Decimal(0)) / len(scores)).quantize(Decimal("0.1")) if scores else None
        level = (
            "insufficient_data"
            if overall is None
            else "high"
            if overall >= 65
            else "medium"
            if overall >= 35
            else "low"
        )
        return FarmRiskOut(
            farm_id=farm_id,
            overall_score=overall,
            overall_level=level,
            worst_by_category=worst,
            cycles=rows,
            note=(
                "Built from the latest prediction of each planned or growing crop cycle. "
                "Cycles without a prediction are not included."
            ),
        )

    # ---------------------------------------------------- feedback & calibration

    def record_actual(self, owner_id: uuid.UUID, cycle_id: uuid.UUID, payload: HarvestActualIn) -> FeedbackReport:
        cycle = self._predictions.lock_cycle(cycle_id, owner_id)
        if cycle is None:
            raise NotFoundError("Crop cycle not found")
        if cycle.status is not CycleStatus.HARVESTED:
            raise ConflictError(
                "Mark the crop cycle as harvested (with its harvest date) before recording the quantity",
                code="cycle_not_harvested",
            )
        if self._actuals.for_cycle(cycle.id) is not None:
            raise ConflictError("The harvest of this crop cycle is already recorded", code="actual_already_recorded")
        start = payload.harvest_start_date or cycle.actual_harvest_date
        assert start is not None
        if start < cycle.sowing_date:
            raise DomainValidationError(
                "Harvest cannot start before sowing",
                code="harvest_before_sowing",
                details={"field": "harvest_start_date"},
            )
        with conflict_on_integrity(
            self._session, "The harvest of this crop cycle is already recorded", "actual_already_recorded"
        ):
            actual = self._actuals.add(
                HarvestActual(
                    crop_cycle_id=cycle.id,
                    quantity_kg=payload.quantity_kg,
                    harvest_start_date=start,
                    recorded_by=owner_id,
                )
            )
            for pred in self._predictions.all_for_cycle(cycle.id):
                if pred.status is not PredictionStatus.OK or pred.p50_kg is None:
                    continue
                assert pred.p10_kg is not None and pred.p90_kg is not None
                m = feedback(
                    pred.p10_kg,
                    pred.p50_kg,
                    pred.p90_kg,
                    actual.quantity_kg,
                    pred.harvest_start_p10,
                    pred.harvest_start_p50,
                    pred.harvest_start_p90,
                    start,
                )
                self._feedback.add(PredictionFeedback(prediction_id=pred.id, harvest_actual_id=actual.id, **to_dict(m)))
            self._session.flush()
            self._recalibrate(cycle.crop_id)
            lot = self._inventory.sync_lot(cycle, owner_id)
            self._session.commit()
        self._notify(lot.id, f"harvest:{actual.id}")
        return self.feedback_report(owner_id, cycle_id)

    def correct_actual(self, owner_id: uuid.UUID, cycle_id: uuid.UUID, payload: HarvestCorrectionIn) -> FeedbackReport:
        """Correct a mistyped harvest before any of it was collected: every prediction version is re-scored,
        calibration and the inventory lot are updated, and the old value, time and reason are kept."""
        cycle = self._predictions.lock_cycle(cycle_id, owner_id)
        if cycle is None:
            raise NotFoundError("Crop cycle not found")
        actual = self._actuals.for_cycle(cycle.id)
        if actual is None:
            raise NotFoundError("No harvest has been recorded for this crop yet")
        if self._actuals.batches_received(actual.id):
            raise ConflictError(
                "Produce from this harvest was already received at a collection hub, so the recorded harvest can no "
                "longer be changed. Ask the hub to correct the received batch instead.",
                code="harvest_in_use",
            )
        start = payload.harvest_start_date or actual.harvest_start_date
        if start < cycle.sowing_date:
            raise DomainValidationError(
                "Harvest cannot start before sowing",
                code="harvest_before_sowing",
                details={"field": "harvest_start_date"},
            )
        actual.previous_quantity_kg = actual.quantity_kg
        actual.quantity_kg = payload.quantity_kg
        actual.harvest_start_date = start
        actual.corrected_at = self._clock.now()
        actual.correction_reason = payload.reason
        self._feedback.delete_for_actual(actual.id)
        for pred in self._predictions.all_for_cycle(cycle.id):
            if pred.status is not PredictionStatus.OK or pred.p50_kg is None:
                continue
            assert pred.p10_kg is not None and pred.p90_kg is not None
            m = feedback(
                pred.p10_kg,
                pred.p50_kg,
                pred.p90_kg,
                actual.quantity_kg,
                pred.harvest_start_p10,
                pred.harvest_start_p50,
                pred.harvest_start_p90,
                start,
            )
            self._feedback.add(PredictionFeedback(prediction_id=pred.id, harvest_actual_id=actual.id, **to_dict(m)))
        self._session.flush()
        self._recalibrate(cycle.crop_id)
        lot = self._inventory.sync_lot(cycle, owner_id)
        self._session.commit()
        self._notify(lot.id, f"harvest-correction:{actual.id}:{actual.corrected_at.isoformat()}")
        return self.feedback_report(owner_id, cycle_id)

    def feedback_report(self, owner_id: uuid.UUID, cycle_id: uuid.UUID) -> FeedbackReport:
        self._require_cycle(owner_id, cycle_id)
        actual = self._actuals.for_cycle(cycle_id)
        rows = [
            FeedbackOut(
                prediction_id=p.id,
                prediction_version=p.version,
                predicted=QuantilesOut(p10=p.p10_kg, p50=p.p50_kg, p90=p.p90_kg),
                actual_kg=actual.quantity_kg if actual else Decimal(0),
                signed_error_kg=f.signed_error_kg,
                abs_error_kg=f.abs_error_kg,
                abs_pct_error=f.abs_pct_error,
                within_interval=f.within_interval,
                pinball_loss=f.pinball_loss,
                date_error_days=f.date_error_days,
                date_within_window=f.date_within_window,
            )
            for f, p in self._feedback.for_cycle(cycle_id)
        ]
        note = (
            "Errors compare each prediction version with the MEASURED harvest."
            if actual
            else "No harvest recorded yet."
        )
        return FeedbackReport(
            actual=HarvestActualOut.model_validate(actual) if actual else None, feedback=rows, note=note
        )

    def latest_calibration(self) -> list[CalibrationOut]:
        return [CalibrationOut.model_validate(p) for p in self._calibration.latest_all()]

    def recompute_all(self) -> list[CalibrationOut]:
        """Append a fresh profile for every crop that has recorded harvests, then the global one."""
        crop_ids = set(
            self._session.scalars(
                select(CropCycle.crop_id).join(HarvestActual, HarvestActual.crop_cycle_id == CropCycle.id)
            )
        )
        for crop_id in sorted(crop_ids, key=str):
            self._recalibrate(crop_id, include_global=False)
        self._append_profile(GLOBAL_SCOPE, None)
        self._session.commit()
        return self.latest_calibration()

    # --------------------------------------------------------------- helpers

    def _require_cycle(self, owner_id: uuid.UUID, cycle_id: uuid.UUID) -> None:
        if CropCycleRepository(self._session).get_owned(cycle_id, owner_id) is None:
            raise NotFoundError("Crop cycle not found")

    def _observations(self, cycle_id: uuid.UUID) -> tuple[ObservationFact, ...]:
        rows = self._session.scalars(select(CropObservation).where(CropObservation.crop_cycle_id == cycle_id))
        return tuple(
            ObservationFact(o.observed_on, o.health_status, o.growth_stage, o.estimated_loss_percent) for o in rows
        )

    def _calibration_for(self, crop_id: uuid.UUID) -> CalibrationProfile | None:
        specific = self._calibration.latest(crop_scope(crop_id))
        if specific is not None and specific.sufficient:
            return specific
        general = self._calibration.latest(GLOBAL_SCOPE)
        if general is not None and general.sufficient:
            return general
        return specific or general

    @staticmethod
    def _facts(profile: CalibrationProfile | None) -> CalibrationFacts | None:
        if profile is None:
            return None
        return CalibrationFacts(
            profile.sample_size,
            profile.sufficient,
            profile.coverage,
            profile.bias_factor,
            profile.interval_scale,
            profile.date_mae_days,
            f"{profile.scope} v{profile.version}",
        )

    def _recalibrate(self, crop_id: uuid.UUID, *, include_global: bool = True) -> None:
        self._append_profile(crop_scope(crop_id), crop_id)
        if include_global:
            self._append_profile(GLOBAL_SCOPE, None)

    def _append_profile(self, scope: str, crop_id: uuid.UUID | None) -> None:
        outcomes = [
            Outcome(p.p10_kg, p.p50_kg, p.p90_kg, a.quantity_kg, f.date_error_days)  # type: ignore[arg-type]
            for p, a, f in self._feedback.outcomes(crop_id)
        ]
        r = calibrate(outcomes, self._min_samples)
        self._calibration.add(
            CalibrationProfile(
                scope=scope,
                crop_id=crop_id,
                version=self._calibration.next_version(scope),
                sample_size=r.sample_size,
                sufficient=r.sufficient,
                coverage=r.coverage,
                mape=r.mape,
                bias_factor=r.bias_factor,
                interval_scale=r.interval_scale,
                date_mae_days=r.date_mae_days,
                note=r.note,
            )
        )

    @staticmethod
    def _change(previous: YieldPrediction, result: Any) -> dict[str, Any]:
        new_p50 = result.quantity_kg.p50 if result.quantity_kg else None
        delta = new_p50 - previous.p50_kg if new_p50 is not None and previous.p50_kg is not None else None
        pct = (
            (delta / previous.p50_kg * 100).quantize(Decimal("0.01")) if delta is not None and previous.p50_kg else None
        )
        change: dict[str, Any] = to_jsonable(
            {
                "previous_version": previous.version,
                "p50_change_kg": delta,
                "p50_change_pct": pct,
                "start_p50_shift_days": (result.timing.start_p50 - previous.harvest_start_p50).days,
                "confidence_change": result.confidence.score - previous.confidence_score,
            }
        )
        return change


def to_dict(m: Any) -> dict[str, Any]:
    return {f.name: getattr(m, f.name) for f in dataclasses.fields(m)}
