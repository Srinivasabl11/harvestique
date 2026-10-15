"""The hybrid rule model: ranges, evidence, factors, uncertainty, timing, confidence, missing data."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.core.enums import (
    ConfidenceLevel,
    CycleStatus,
    DataKind,
    HealthStatus,
    IrrigationType,
    PredictionStatus,
    WeatherStatus,
)
from app.domain.planning.models import Range
from app.domain.prediction.engine import Z90, RuleBasedPredictor
from app.domain.prediction.models import CalibrationFacts, NotPredictableError, ObservationFact, PastHarvest
from app.domain.weather import WeatherContext
from tests.intelligence_factory import SOWN, TODAY, crop, cycle, inp, weather

P = RuleBasedPredictor()


def factor(result, name):
    return {f.name: f.multiplier for f in result.factors}.get(name)


# ----------------------------------------------------------------- ranges


def test_quantiles_follow_the_documented_formula():
    r = P.predict(inp())
    q, cv = r.quantity_kg, r.cv
    assert r.status is PredictionStatus.OK
    assert q.p10 <= q.p50 <= q.p90
    assert abs(q.p90 - q.p50 * (1 + Z90 * cv)) < D("0.01")
    assert abs(q.p10 - q.p50 * (1 - Z90 * cv)) < D("0.01")
    assert r.yield_per_acre_kg.p50 == (q.p50 / 2).quantize(D("0.001"))  # 2 acres


def test_reference_only_with_good_rain_gives_reference_times_area():
    r = P.predict(inp())  # rain 5 mm/day ~ 305 mm vs need 254 mm: no deficit; no heat; no observations
    assert r.factors == () and r.quantity_kg.p50 == D("20000.000")


def test_p10_is_never_negative_even_with_huge_uncertainty():
    r = P.predict(inp(weather=WeatherContext.unavailable("x"), crop=crop(reference_yield_cv=D(2))))
    assert r.quantity_kg.p10 >= 0 and r.cv == D("0.8")  # capped


def test_cv_never_below_the_floor():
    hist = tuple(PastHarvest(D(10000), date(2025, 1, 1)) for _ in range(5))  # zero spread history
    r = P.predict(inp(history=hist, today=SOWN + timedelta(days=120), crop=crop(reference_yield_kg_per_acre=None)))
    assert r.cv >= D("0.10")


# --------------------------------------------------------------- evidence


def test_history_outweighs_the_reference():
    hist = tuple(PastHarvest(D(6000), date(2025, 1, 1)) for _ in range(5))
    r = P.predict(inp(history=hist))
    # weights: history 10 x 6000, reference 1 x 10000 -> 6363.6/acre
    assert abs(r.yield_per_acre_kg.p50 - (D(60000) + D(10000)) / 11) < D("0.01")
    assert {s.name: s.kind for s in r.sources if s.used}["farm_history"] is DataKind.MEASURED


def test_farmer_estimate_blends_in():
    r = P.predict(inp(farmer_estimate=Range(D(7000), D(8000), D(9000))))
    assert abs(r.yield_per_acre_kg.p50 - (3 * D(8000) + D(10000)) / 4) < D("0.01")


def test_no_evidence_is_insufficient_data_not_a_guess():
    r = P.predict(inp(crop=crop(reference_yield_kg_per_acre=None)))
    assert r.status is PredictionStatus.INSUFFICIENT_DATA
    assert r.quantity_kg is None and r.yield_per_acre_kg is None and r.cv is None
    assert r.timing.start_p50  # timing is still available
    assert r.confidence.score == 0 and any("No basis" in w for w in r.warnings)


@pytest.mark.parametrize(
    ("status", "code"), [(CycleStatus.ABANDONED, "cycle_abandoned"), (CycleStatus.HARVESTED, "cycle_harvested")]
)
def test_closed_cycles_are_not_predicted(status, code):
    with pytest.raises(NotPredictableError) as exc:
        P.predict(inp(cycle=cycle(status=status)))
    assert exc.value.code == code


def test_planned_cycle_in_the_future_is_predictable():
    r = P.predict(inp(cycle=cycle(status=CycleStatus.PLANNED, sowing_date=TODAY + timedelta(days=20))))
    assert r.status is PredictionStatus.OK and {w.name: w.amount for w in r.widenings}["time_remaining"] == D("0.1")


# ----------------------------------------------------------------- factors


def test_water_deficit_by_hand():
    r = P.predict(inp(weather=weather(observed_rain=1)))  # 61 mm vs need 500*61/120 = 254.2 -> ratio 0.24
    ratio = D(61) / (D(500) * D(61) / D(120))
    assert factor(r, "water_deficit") == (1 - D("0.25") * (D("0.6") - ratio) / D("0.6")).quantize(D("0.0001"))


def test_irrigated_plots_are_not_penalised_for_low_rain():
    r = P.predict(inp(weather=weather(observed_rain=1), cycle=cycle(irrigation=IrrigationType.DRIP)))
    assert factor(r, "water_deficit") is None and any(s.name == "irrigation" for s in r.sources)


def test_heat_stress_and_heavy_rain():
    hot = P.predict(inp(weather=weather(tmax=36)))  # 61 hot days -> capped at -20%
    assert factor(hot, "heat_stress") == D("0.80")
    wet = P.predict(inp(weather=weather(observed_rain=70)))  # 61 heavy days -> capped at -10%
    assert factor(wet, "heavy_rain") == D("0.90")


def test_latest_observation_loss_is_applied():
    obs = (
        ObservationFact(TODAY - timedelta(days=20), HealthStatus.HEALTHY),
        ObservationFact(TODAY - timedelta(days=3), HealthStatus.PEST_AFFECTED, None, D(25)),
    )
    r = P.predict(inp(observations=obs))
    assert factor(r, "field_observation") == D("0.75")
    assert "crop_problem" in {w.name for w in r.widenings}


def test_health_status_without_loss_uses_the_documented_multiplier():
    r = P.predict(inp(observations=(ObservationFact(TODAY - timedelta(days=2), HealthStatus.DISEASE_AFFECTED),)))
    assert factor(r, "field_observation") == D("0.90")


def test_old_observations_are_ignored_with_a_warning():
    r = P.predict(inp(observations=(ObservationFact(TODAY - timedelta(days=45), HealthStatus.DAMAGED),)))
    assert factor(r, "field_observation") is None and any("older than 30 days" in w for w in r.warnings)


def test_a_damaging_observation_lowers_the_prediction():
    before = P.predict(inp()).quantity_kg.p50
    after = P.predict(inp(observations=(ObservationFact(TODAY, HealthStatus.DAMAGED, None, D(40)),))).quantity_kg.p50
    assert after == before * D("0.6")


# ---------------------------------------------------- missing / stale data


def test_missing_weather_widens_uncertainty_and_lowers_confidence():
    good = P.predict(inp())
    none = P.predict(inp(weather=WeatherContext.unavailable("farm has no coordinates")))
    assert none.cv - good.cv == D("0.10")
    assert none.confidence.score < good.confidence.score
    assert none.timing.spread_days == good.timing.spread_days + 3
    assert any(not s.used and s.name == "weather" for s in none.sources)


def test_stale_weather_widens_a_little():
    stale = P.predict(inp(weather=replace(weather(), status=WeatherStatus.STALE)))
    assert {w.name: w.amount for w in stale.widenings}["weather_stale"] == D("0.05")
    assert any("stale" in w for w in stale.warnings)


def test_sparse_weather_is_flagged():
    sparse = replace(weather(), observed=weather().observed[:10])
    assert "weather_sparse" in {w.name for w in P.predict(inp(weather=sparse)).widenings}


def test_time_remaining_widens_early_season():
    early = P.predict(inp(today=SOWN + timedelta(days=5)))
    late = P.predict(inp(today=SOWN + timedelta(days=115)))
    assert early.cv > late.cv


# ------------------------------------------------------------------- timing


def test_timing_anchors_on_the_farmers_date_or_the_catalog_duration():
    r = P.predict(inp())
    assert r.timing.start_p50 in {SOWN + timedelta(days=120 + d) for d in (-1, 0, 1)}  # ~25 C: neutral speed
    own = P.predict(inp(cycle=cycle(expected_harvest_date=date(2026, 12, 15))))
    assert abs((own.timing.start_p50 - date(2026, 12, 15)).days) <= 1


def test_cool_weather_delays_and_warm_weather_advances_harvest_within_bounds():
    base = P.predict(inp()).timing.start_p50
    cool = P.predict(inp(weather=weather(tmax=20, forecast_tmax=20))).timing.start_p50  # mean 20 C -> slower
    warm = P.predict(inp(weather=weather(tmax=40, forecast_tmax=40))).timing.start_p50
    assert cool > base > warm
    remaining = (base - TODAY).days
    assert (cool - TODAY).days <= round(remaining * 1.2) + 1 and (warm - TODAY).days >= round(remaining * 0.8) - 1


def test_window_is_ordered_and_widens_with_time_remaining():
    t = P.predict(inp()).timing
    assert t.start_p10 < t.start_p50 < t.start_p90 < t.end_p90
    assert (
        P.predict(inp(today=SOWN + timedelta(days=5))).timing.spread_days
        > P.predict(inp(today=SOWN + timedelta(days=110))).timing.spread_days
    )


def test_overdue_harvest_is_flagged():
    r = P.predict(inp(today=SOWN + timedelta(days=150)))
    assert r.timing.start_p50 == SOWN + timedelta(days=150) and any("passed" in w for w in r.warnings)


# ------------------------------------------------------- confidence / calibration


def test_confidence_is_heuristic_without_enough_history():
    c = P.predict(inp(calibration=CalibrationFacts(3, False, D("0.6"), D(1), D(1), None, "global v3"))).confidence
    assert (
        c.basis == "heuristic"
        and "3 recorded outcome(s)" in c.calibration_note
        and "not a measured accuracy" in c.calibration_note
    )
    assert {x.name for x in c.components} == {"evidence", "weather_data", "observations", "season_progress"}


def test_confidence_components_by_hand():
    c = P.predict(inp()).confidence  # reference only 30; fresh weather 90; no obs 30; progress 61/120
    progress = (D(61) / D(120) * 100).quantize(D("0.1"))
    expected = D(30) * D("0.35") + D(90) * D("0.25") + D(30) * D("0.15") + progress * D("0.25")
    assert c.score == expected.quantize(D("0.1"))


def test_calibration_is_used_only_when_sufficient():
    weak = CalibrationFacts(4, False, D("0.5"), D("0.8"), D(2), None, "global v4")
    strong = CalibrationFacts(12, True, D("0.6"), D("0.8"), D(2), D(10), "crop v2")
    base = P.predict(inp())
    with_weak = P.predict(inp(calibration=weak))
    with_strong = P.predict(inp(calibration=strong))
    assert with_weak.quantity_kg == base.quantity_kg  # insufficient: no effect at all
    assert factor(with_strong, "calibration_bias") == D(
        "0.8"
    ) and with_strong.quantity_kg.p50 == base.quantity_kg.p50 * D("0.8")
    assert with_strong.cv > base.cv and with_strong.confidence.basis == "calibrated"
    assert with_strong.timing.spread_days >= 13  # 1.28 x 10-day calibrated date error


def test_more_and_better_evidence_raises_confidence():
    ref = P.predict(inp()).confidence.score
    hist = P.predict(inp(history=tuple(PastHarvest(D(9000), date(2025, 1, 1)) for _ in range(5)))).confidence.score
    assert hist > ref
    assert (
        P.predict(inp(history=tuple(PastHarvest(D(9000), date(2025, 1, 1)) for _ in range(5)))).confidence.level
        is not ConfidenceLevel.LOW
    )


# ------------------------------------------------------- provenance & honesty


def test_every_source_is_labelled_measured_estimate_or_assumption():
    r = P.predict(inp(farmer_estimate=Range(D(7000), D(8000), D(9000))))
    kinds = {s.name: s.kind for s in r.sources}
    assert kinds["weather_observed"] is DataKind.MEASURED and kinds["weather_forecast"] is DataKind.ESTIMATE
    assert kinds["reference_yield"] is DataKind.ASSUMPTION and kinds["farmer_estimate"] is DataKind.ESTIMATE
    assert r.output_kind is DataKind.ESTIMATE


def test_explanations_never_promise():
    text = " ".join(P.predict(inp()).explanations)
    assert "not a guarantee" in text and "80% range" in text


def test_prediction_is_deterministic():
    assert P.predict(inp()) == P.predict(inp())
