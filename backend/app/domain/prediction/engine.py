"""Hybrid rule-based harvest prediction (deterministic; used until real training data exists).

QUANTITY.  base yield/acre = evidence-weighted blend of
    own recorded harvests (MEASURED, weight 2 per record up to 5), the farmer's estimate (ESTIMATE, 3),
    the catalog reference yield (ASSUMPTION, 1);
then multiplied by explicit adjustment factors (water deficit, heat stress, heavy rain, latest field
observation, calibrated bias). Uncertainty is a coefficient of variation (CV) from the same evidence, WIDENED
for every missing/stale input and for time still to go; quantiles assume an approximately normal spread:
    p50 = base x factors x area;  p10 = max(0, p50 (1 - 1.2816 CV));  p90 = p50 (1 + 1.2816 CV).
TIMING.  start = the farmer's expected harvest date, else sowing + typical duration; the remaining days are
scaled by growing-degree-day speed (observed + forecast mean temperature vs a 25 C reference), bounded to
+/-20%; the window widens with time remaining, missing weather and calibrated date error.
CONFIDENCE is a transparent heuristic unless a calibration profile with enough recorded outcomes exists.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.core.enums import (
    CropCategory,
    CycleStatus,
    DataKind,
    HealthStatus,
    IrrigationType,
    PredictionStatus,
    WeatherStatus,
)
from app.domain.planning.models import Component
from app.domain.planning.scoring import confidence_level
from app.domain.prediction.models import (
    Factor,
    HarvestTiming,
    NotPredictableError,
    ObservationFact,
    PredictionConfidence,
    PredictionInput,
    PredictionResult,
    Quantiles,
    SourceUse,
    Widening,
)
from app.domain.weather import GDD_BASE_C, WindowSummary, summarize

D = Decimal
Z90 = D("1.2816")
DEFAULT_CV, MIN_CV, MAX_CV = D("0.30"), D("0.10"), D("0.80")
REF_TEMP_C = D(25)
REF_GDD_RATE = REF_TEMP_C - GDD_BASE_C  # 15 degree-days per day at the reference temperature
OBS_RECENT_DAYS, OBS_MAX_AGE_DAYS = 14, 30
HEALTH_MULTIPLIER = {
    HealthStatus.HEALTHY: D(1),
    HealthStatus.STRESSED: D("0.95"),
    HealthStatus.PEST_AFFECTED: D("0.92"),
    HealthStatus.DISEASE_AFFECTED: D("0.90"),
    HealthStatus.DAMAGED: D("0.85"),
}
HARVEST_SPAN_DAYS = {
    CropCategory.VEGETABLE: 30,
    CropCategory.FRUIT: 30,
    CropCategory.SPICE: 30,
    CropCategory.FLOWER: 20,
}
DEFAULT_HARVEST_SPAN_DAYS = 10
MIN_CALIBRATION_SAMPLES = 5


def _q(x: Decimal, places: str = "0.001") -> Decimal:
    return x.quantize(D(places), rounding=ROUND_HALF_UP)


class RuleBasedPredictor:
    name = "hybrid-rules"
    version = "1.0.0"

    def predict(self, inp: PredictionInput) -> PredictionResult:
        cycle, crop = inp.cycle, inp.crop
        if cycle.status is CycleStatus.ABANDONED:
            raise NotPredictableError("cycle_abandoned", "An abandoned crop cycle has nothing to predict")
        if cycle.status is CycleStatus.HARVESTED:
            raise NotPredictableError(
                "cycle_harvested", "This crop cycle is harvested; record the actual harvest instead"
            )

        warnings: list[str] = []
        sources: list[SourceUse] = []
        factors: list[Factor] = []
        widenings: list[Widening] = []

        # ---------------------------------------------------------- timeline
        base_start = cycle.expected_harvest_date or cycle.sowing_date + timedelta(days=crop.typical_duration_days)
        if cycle.expected_harvest_date:
            sources.append(
                SourceUse(
                    "expected_harvest_date", DataKind.ESTIMATE, True, "Your expected harvest date anchors timing."
                )
            )
        else:
            sources.append(
                SourceUse(
                    "typical_duration",
                    DataKind.ASSUMPTION,
                    True,
                    f"Catalog duration of {crop.typical_duration_days} days anchors timing.",
                )
            )
        duration = max(1, (base_start - cycle.sowing_date).days)
        elapsed = min(max(0, (inp.today - cycle.sowing_date).days), duration)
        remaining_fraction = D(duration - elapsed) / D(duration)

        # ----------------------------------------------------------- weather
        w = inp.weather
        observed = summarize(w.observed, cycle.sowing_date, inp.today - timedelta(days=1)) if elapsed else None
        if w.status is WeatherStatus.UNAVAILABLE:
            widenings.append(
                Widening("weather_unavailable", D("0.10"), f"No weather data ({w.note or 'unavailable'}).")
            )
            warnings.append("Weather data unavailable: the prediction ignores weather and is less certain.")
            sources.append(SourceUse("weather", DataKind.MEASURED, False, w.note or "unavailable"))
        else:
            if w.status is WeatherStatus.STALE:
                widenings.append(Widening("weather_stale", D("0.05"), "Weather data is out of date (cached)."))
                warnings.append("Weather data is stale (last refresh failed); forecast parts may be outdated.")
            sources.append(
                SourceUse(
                    "weather_observed",
                    DataKind.MEASURED,
                    bool(w.observed),
                    "Open-Meteo reanalysis for the season so far (model-based observation, not an on-farm gauge).",
                )
            )
            sources.append(
                SourceUse(
                    "weather_forecast", DataKind.ESTIMATE, bool(w.forecast), "Open-Meteo forecast for the coming days."
                )
            )
            if observed and observed.days_expected and observed.coverage < D("0.5"):
                widenings.append(
                    Widening(
                        "weather_sparse",
                        D("0.05"),
                        f"Only {int(observed.coverage * 100)}% of season days have weather data.",
                    )
                )

        # ------------------------------------------------- base yield + CV
        n_hist = len(inp.history)
        evidence: list[tuple[Decimal, Decimal, Decimal | None]] = []  # (weight, value, cv)
        if n_hist:
            values = [h.yield_kg_per_acre for h in inp.history]
            mean = sum(values, D(0)) / n_hist
            hist_cv: Decimal | None = None
            if n_hist >= 3 and mean > 0:
                var = sum(((v - mean) ** 2 for v in values), D(0)) / (n_hist - 1)
                hist_cv = var.sqrt() / mean
            evidence.append((D(2 * min(n_hist, 5)), mean, hist_cv))
            sources.append(
                SourceUse(
                    "farm_history",
                    DataKind.MEASURED,
                    True,
                    f"{n_hist} recorded harvest(s) of {crop.name} on your land, mean {_q(mean, '1')} kg/acre.",
                )
            )
        else:
            sources.append(
                SourceUse("farm_history", DataKind.MEASURED, False, "No recorded harvests of this crop yet.")
            )
        if inp.farmer_estimate is not None:
            est = inp.farmer_estimate
            est_cv = (est.high - est.low) / (2 * Z90 * est.expected)
            evidence.append((D(3), est.expected, est_cv))
            sources.append(
                SourceUse("farmer_estimate", DataKind.ESTIMATE, True, f"Your estimate: {est.expected} kg/acre.")
            )
        if crop.reference_yield_kg_per_acre is not None:
            evidence.append((D(1), crop.reference_yield_kg_per_acre, crop.reference_yield_cv))
            sources.append(
                SourceUse(
                    "reference_yield",
                    DataKind.ASSUMPTION,
                    True,
                    f"Catalog reference {crop.reference_yield_kg_per_acre} kg/acre (indicative, not your farm).",
                )
            )

        timing = self._timing(inp, base_start, duration, elapsed, remaining_fraction, widenings, warnings)

        if not evidence:
            warnings.append(
                "No basis for a yield estimate: record past harvests, give your own estimate, or ask an admin to add a "
                "reference yield for this crop."
            )
            return PredictionResult(
                status=PredictionStatus.INSUFFICIENT_DATA,
                model_name=self.name,
                model_version=self.version,
                quantity_kg=None,
                yield_per_acre_kg=None,
                cv=None,
                timing=timing,
                confidence=PredictionConfidence(
                    D(0), confidence_level(D(0)), "heuristic", (), "No quantity prediction was made."
                ),
                factors=(),
                widenings=tuple(widenings),
                sources=tuple(sources),
                warnings=tuple(warnings),
                explanations=(
                    "Quantity cannot be estimated without any yield evidence; only harvest timing is given.",
                ),
            )

        total_w = sum((e[0] for e in evidence), D(0))
        base = sum((e[0] * e[1] for e in evidence), D(0)) / total_w
        cvs = [(e[0], e[2]) for e in evidence if e[2] is not None]
        base_cv = sum((wt * cv for wt, cv in cvs), D(0)) / sum((wt for wt, _ in cvs), D(0)) if cvs else DEFAULT_CV
        if not cvs:
            widenings.append(
                Widening("no_spread_evidence", D(0), f"No evidence of spread; default CV {DEFAULT_CV} used.")
            )

        # ------------------------------------------------------- adjustments
        if observed and observed.days_with_data:
            irrigated = cycle.irrigation is not None and cycle.irrigation is not IrrigationType.RAINFED
            if crop.water_need_mm and elapsed >= 14 and observed.coverage >= D("0.5"):
                expected_rain = crop.water_need_mm * D(elapsed) / D(duration)
                ratio = observed.rain_mm / expected_rain if expected_rain > 0 else D(1)
                if irrigated:
                    sources.append(
                        SourceUse(
                            "irrigation",
                            DataKind.MEASURED,
                            True,
                            f"Plot is irrigated ({cycle.irrigation}); rainfall deficit not penalised.",
                        )
                    )
                elif ratio < D("0.6"):
                    m = D(1) - D("0.25") * (D("0.6") - ratio) / D("0.6")
                    factors.append(
                        Factor(
                            "water_deficit",
                            _q(m, "0.0001"),
                            DataKind.MEASURED,
                            f"Rain so far {_q(observed.rain_mm, '1')} mm is {int(ratio * 100)}% of the crop's need to date.",
                        )
                    )
            if observed.heat_stress_days:
                m = D(1) - min(D("0.20"), D("0.01") * observed.heat_stress_days)
                factors.append(
                    Factor(
                        "heat_stress",
                        m,
                        DataKind.MEASURED,
                        f"{observed.heat_stress_days} day(s) at or above 35 C so far.",
                    )
                )
            if observed.heavy_rain_days:
                m = D(1) - min(D("0.10"), D("0.03") * observed.heavy_rain_days)
                factors.append(
                    Factor(
                        "heavy_rain",
                        m,
                        DataKind.MEASURED,
                        f"{observed.heavy_rain_days} heavy-rain day(s) (>= 64.5 mm).",
                    )
                )

        recent = [o for o in inp.observations if 0 <= (inp.today - o.observed_on).days <= OBS_MAX_AGE_DAYS]
        if recent:
            latest = max(recent, key=lambda o: o.observed_on)
            if latest.estimated_loss_percent is not None:
                m = D(1) - latest.estimated_loss_percent / 100
                detail = f"Latest observation ({latest.observed_on}) estimates {latest.estimated_loss_percent}% loss."
            else:
                m = HEALTH_MULTIPLIER[latest.health_status]
                detail = f"Latest observation ({latest.observed_on}): {latest.health_status.value}."
            if m != 1:
                factors.append(Factor("field_observation", m, DataKind.MEASURED, detail))
            if latest.health_status in (
                HealthStatus.PEST_AFFECTED,
                HealthStatus.DISEASE_AFFECTED,
                HealthStatus.DAMAGED,
            ):
                widenings.append(Widening("crop_problem", D("0.05"), f"Crop reported {latest.health_status.value}."))
            sources.append(
                SourceUse(
                    "observations",
                    DataKind.MEASURED,
                    True,
                    f"{len(recent)} observation(s) in the last {OBS_MAX_AGE_DAYS} days.",
                )
            )
        else:
            sources.append(
                SourceUse("observations", DataKind.MEASURED, False, "No field observation in the last 30 days.")
            )
            if inp.observations:
                warnings.append("Field observations are older than 30 days and were not used.")

        cal = inp.calibration
        calibrated = cal is not None and cal.sufficient and cal.sample_size >= MIN_CALIBRATION_SAMPLES
        if calibrated and cal is not None and cal.bias_factor != 1:
            factors.append(
                Factor(
                    "calibration_bias",
                    cal.bias_factor,
                    DataKind.MEASURED,
                    f"Past predictions were off by a median ratio of {cal.bias_factor} ({cal.sample_size} outcomes, {cal.reference}).",
                )
            )

        widenings.append(
            Widening(
                "time_remaining",
                _q(D("0.10") * remaining_fraction, "0.0001"),
                f"{int(remaining_fraction * 100)}% of the season is still ahead.",
            )
        )

        multiplier = D(1)
        for f in factors:
            multiplier *= f.multiplier
        cv = max(MIN_CV, base_cv) + sum((w_.amount for w_ in widenings), D(0))
        if calibrated and cal is not None:
            cv *= cal.interval_scale
        cv = min(MAX_CV, max(MIN_CV, cv))

        per_acre_p50 = base * multiplier
        p50 = per_acre_p50 * cycle.area_acres
        quantity = Quantiles(_q(max(D(0), p50 * (1 - Z90 * cv))), _q(p50), _q(p50 * (1 + Z90 * cv)))
        per_acre = Quantiles(*(_q(v / cycle.area_acres) for v in (quantity.p10, quantity.p50, quantity.p90)))

        confidence = self._confidence(inp, n_hist, elapsed, duration, observed, recent, calibrated)
        explanations = (
            f"Base yield {_q(base, '1')} kg/acre from {', '.join(s.name for s in sources if s.used and s.name in ('farm_history', 'farmer_estimate', 'reference_yield'))}.",
            "Adjustments: " + ("; ".join(f"{f.name} x{_q(f.multiplier, '0.01')}" for f in factors) or "none") + ".",
            f"Uncertainty (CV) {_q(cv, '0.01')}: base {_q(base_cv, '0.01')} plus "
            + ", ".join(f"{w_.name} +{w_.amount}" for w_ in widenings if w_.amount)
            + ".",
            f"Expected {quantity.p50} kg (80% range {quantity.p10}-{quantity.p90} kg) on {cycle.area_acres} acres.",
            f"Harvest likely to start {timing.start_p50} (between {timing.start_p10} and {timing.start_p90}).",
            "This is an estimate, not a guarantee of yield, harvest date or income.",
        )
        return PredictionResult(
            status=PredictionStatus.OK,
            model_name=self.name,
            model_version=self.version,
            quantity_kg=quantity,
            yield_per_acre_kg=per_acre,
            cv=_q(cv, "0.0001"),
            timing=timing,
            confidence=confidence,
            factors=tuple(factors),
            widenings=tuple(widenings),
            sources=tuple(sources),
            warnings=tuple(warnings),
            explanations=explanations,
        )

    # ------------------------------------------------------------------ timing

    def _timing(
        self,
        inp: PredictionInput,
        base_start: date,
        duration: int,
        elapsed: int,
        remaining_fraction: Decimal,
        widenings: list[Widening],
        warnings: list[str],
    ) -> HarvestTiming:
        today = inp.today
        temps = [d for d in (*inp.weather.observed, *inp.weather.forecast) if d.day >= inp.cycle.sowing_date]
        p50 = base_start
        remaining = (base_start - today).days
        if remaining > 0 and len(temps) >= 7:
            mean = sum((d.mean_c for d in temps), D(0)) / len(temps)
            rate = max(D(1), mean - GDD_BASE_C)
            speed = min(D("1.2"), max(D("0.8"), REF_GDD_RATE / rate))
            p50 = today + timedelta(days=int((D(remaining) * speed).to_integral_value(rounding=ROUND_HALF_UP)))
        elif remaining <= 0:
            p50 = max(base_start, today)
            warnings.append("The expected harvest date has passed; record the actual harvest when it happens.")
        spread = max(
            3,
            int((D(duration) * (D("0.05") + D("0.10") * remaining_fraction)).to_integral_value(rounding=ROUND_HALF_UP)),
        )
        if inp.weather.status is WeatherStatus.UNAVAILABLE:
            spread += 3
        cal = inp.calibration
        if cal is not None and cal.sufficient and cal.date_mae_days is not None:
            spread = max(spread, int((cal.date_mae_days * Z90).to_integral_value(rounding=ROUND_HALF_UP)))
        start_p10 = max(inp.cycle.sowing_date + timedelta(days=1), p50 - timedelta(days=spread))
        start_p90 = p50 + timedelta(days=spread)
        span = HARVEST_SPAN_DAYS.get(inp.crop.category, DEFAULT_HARVEST_SPAN_DAYS)
        return HarvestTiming(start_p10, p50, start_p90, start_p90 + timedelta(days=span), spread)

    # -------------------------------------------------------------- confidence

    def _confidence(
        self,
        inp: PredictionInput,
        n_hist: int,
        elapsed: int,
        duration: int,
        observed: WindowSummary | None,
        recent: list[ObservationFact],
        calibrated: bool,
    ) -> PredictionConfidence:
        if n_hist >= 5:
            ev, ev_d = D(90), f"{n_hist} recorded harvests."
        elif n_hist >= 3:
            ev, ev_d = D(75), f"{n_hist} recorded harvests."
        elif n_hist:
            ev, ev_d = D(60), f"Only {n_hist} recorded harvest(s)."
        elif inp.farmer_estimate is not None:
            ev, ev_d = D(50), "Based on your estimate (no recorded harvests)."
        else:
            ev, ev_d = D(30), "Based only on an indicative reference yield."
        st = inp.weather.status
        if st is WeatherStatus.UNAVAILABLE:
            wx, wx_d = D(20), "No weather data."
        elif st is WeatherStatus.STALE:
            wx, wx_d = D(50), "Weather data is stale."
        elif observed is not None and observed.coverage < D("0.8"):
            wx, wx_d = D(60), "Weather data covers part of the season."
        else:
            wx, wx_d = D(90), "Fresh weather data."
        if recent:
            age = min((inp.today - o.observed_on).days for o in recent)
            ob, ob_d = (
                (D(90), "Recent field observation.")
                if age <= OBS_RECENT_DAYS
                else (D(60), "Field observation 2-4 weeks old.")
            )
        else:
            ob, ob_d = D(30), "No recent field observation."
        progress = max(D(10), D(elapsed) / D(duration) * 100)
        comps: tuple[Component, ...] = (
            Component("evidence", ev, D("0.35"), ev_d),
            Component("weather_data", wx, D("0.25"), wx_d),
            Component("observations", ob, D("0.15"), ob_d),
            Component(
                "season_progress",
                _q(progress, "0.1"),
                D("0.25"),
                f"{int(D(elapsed) / D(duration) * 100)}% of the season has passed.",
            ),
        )
        heuristic = sum((c.score * c.weight for c in comps), D(0))
        cal = inp.calibration
        if calibrated and cal is not None and cal.coverage is not None:
            empirical = min(D(100), cal.coverage / D("0.8") * 100)
            score = D("0.7") * heuristic + D("0.3") * empirical
            comps = (
                *comps,
                Component(
                    "calibration",
                    _q(empirical, "0.1"),
                    D("0.3"),
                    f"{int(cal.coverage * 100)}% of {cal.sample_size} past outcomes fell inside the 80% range.",
                ),
            )
            note = f"Calibrated with {cal.sample_size} recorded outcomes ({cal.reference})."
            basis = "calibrated"
        else:
            score = heuristic
            n = cal.sample_size if cal else 0
            note = f"Not calibrated: {n} recorded outcome(s), at least {MIN_CALIBRATION_SAMPLES} needed. Confidence is a rule-based heuristic, not a measured accuracy."
            basis = "heuristic"
        score = _q(score, "0.1")
        return PredictionConfidence(score, confidence_level(score), basis, comps, note)
