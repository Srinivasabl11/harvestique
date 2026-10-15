from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.core.enums import HealthStatus, IrrigationType, PredictionStatus, RiskCategory
from app.domain.planning.models import Range
from app.domain.prediction.calibration import MIN_SAMPLES, Outcome, calibrate, feedback, pinball
from app.domain.prediction.engine import RuleBasedPredictor
from app.domain.prediction.models import ObservationFact
from app.domain.prediction.risk import MarketContext, assess
from app.domain.prediction.simulation import run_study
from app.domain.weather import WeatherContext
from tests.intelligence_factory import TODAY, crop, cycle, inp, weather

P = RuleBasedPredictor()


def report(i=None, market=None):
    i = i or inp()
    return {c.category: c for c in assess(i, P.predict(i), market).categories}


# --------------------------------------------------------------------- risk


def test_all_nine_categories_are_always_reported():
    assert set(report()) == set(RiskCategory)


def test_missing_inputs_are_not_assessed_not_guessed():
    r = report()
    for cat in (RiskCategory.MARKET, RiskCategory.DEMAND, RiskCategory.LABOUR, RiskCategory.DISEASE):
        assert r[cat].score is None and r[cat].level == "insufficient_data"
    full = assess(inp(), P.predict(inp()))
    assert full.assessed == 5 and "not guessed" in full.note


def test_overall_score_averages_only_assessed_categories():
    i = inp()
    rep = assess(i, P.predict(i))
    scored = [c.score for c in rep.categories if c.score is not None]
    assert rep.overall_score == (sum(scored) / len(scored)).quantize(D("0.1"))


def test_no_weather_makes_weather_and_water_unassessed():
    r = report(inp(weather=WeatherContext.unavailable("x")))
    assert r[RiskCategory.WEATHER].score is None and r[RiskCategory.WATER].score is None


def test_weather_risk_rises_with_heat():
    assert (
        report(inp(weather=weather(tmax=36, forecast_tmax=39)))[RiskCategory.WEATHER].score
        > report()[RiskCategory.WEATHER].score
    )


def test_water_risk_rainfed_vs_irrigated():
    dry = inp(weather=weather(observed_rain=0))
    irrigated = inp(weather=weather(observed_rain=0), cycle=cycle(irrigation=IrrigationType.CANAL))
    assert report(dry)[RiskCategory.WATER].level == "high"
    assert report(irrigated)[RiskCategory.WATER].score < report(dry)[RiskCategory.WATER].score


def test_disease_risk_from_observations():
    sick = inp(observations=(ObservationFact(TODAY - timedelta(days=2), HealthStatus.DISEASE_AFFECTED, None, D(20)),))
    healthy = inp(observations=(ObservationFact(TODAY - timedelta(days=2), HealthStatus.HEALTHY),))
    assert report(sick)[RiskCategory.DISEASE].level == "high" and report(healthy)[RiskCategory.DISEASE].level == "low"


def test_market_demand_and_labour_when_supplied():
    q = P.predict(inp()).quantity_kg
    r = report(market=MarketContext(Range(D(5), D(10), D(20)), q.p50, D(90), D(100)))
    assert r[RiskCategory.MARKET].score == D("150.0").min(D(100))  # spread 1.5 -> capped at 100
    assert r[RiskCategory.DEMAND].score == D("30.0")  # supply = 100% of demand: (1.0 - 0.8) x 150
    assert r[RiskCategory.LABOUR].score == D("40.0")  # need 90% of available: (0.9 - 0.7) x 200


@pytest.mark.parametrize(
    ("committed_of", "level"), [("none", "low"), ("p10", "low"), ("p50", "medium"), ("over", "high")]
)
def test_fulfilment_risk_bands(committed_of, level):
    q = P.predict(inp()).quantity_kg
    committed = {"none": D(0), "p10": q.p10, "p50": q.p50, "over": q.p50 + 1}[committed_of]
    assert report(market=MarketContext(committed_kg=committed))[RiskCategory.FULFILMENT].level == level


def test_timing_risk_counts_spread_and_delay():
    r = report(inp(cycle=cycle(expected_harvest_date=date(2026, 11, 1)), weather=weather(tmax=20, forecast_tmax=20)))
    assert r[RiskCategory.TIMING].score > report()[RiskCategory.TIMING].score


def test_insufficient_prediction_leaves_yield_and_fulfilment_unassessed():
    i = inp(crop=crop(reference_yield_kg_per_acre=None))
    pred = P.predict(i)
    assert pred.status is PredictionStatus.INSUFFICIENT_DATA
    r = {c.category: c for c in assess(i, pred).categories}
    assert r[RiskCategory.YIELD].score is None and r[RiskCategory.FULFILMENT].score is None


# ----------------------------------------------------------------- feedback


def test_feedback_metrics_by_hand():
    m = feedback(
        D(800), D(1000), D(1300), D(900), date(2026, 3, 1), date(2026, 3, 10), date(2026, 3, 20), date(2026, 3, 14)
    )
    assert (m.signed_error_kg, m.abs_error_kg, m.abs_pct_error, m.within_interval) == (
        D(-100),
        D(100),
        D("11.11"),
        True,
    )
    expected_loss = (D("0.1") * 100 + D("0.5") * 100 + D("0.1") * 400) / 3  # pinball at 0.1, 0.5, 0.9
    assert m.pinball_loss == expected_loss.quantize(D("0.001"))
    assert (m.date_error_days, m.date_within_window) == (4, True)


def test_feedback_outside_interval_and_zero_actual():
    m = feedback(D(800), D(1000), D(1300), D(0), None, None, None, None)
    assert m.within_interval is False and m.abs_pct_error is None and m.date_error_days is None


def test_pinball_is_asymmetric():
    assert pinball(D(10), D("0.9"), D(20)) == D(9) and pinball(D(10), D("0.9"), D(0)) == D(1)


# -------------------------------------------------------------- calibration


def outcomes(n, actual=D(900)):
    return [Outcome(D(800), D(1000), D(1200), actual) for _ in range(n)]


def test_calibration_is_not_applied_below_the_minimum():
    r = calibrate(outcomes(MIN_SAMPLES - 1))
    assert r.sufficient is False and r.bias_factor == 1 and r.interval_scale == 1
    assert r.sample_size == 4 and "not applied" in r.note


def test_no_outcomes_means_no_metrics_at_all():
    r = calibrate([])
    assert (r.sample_size, r.coverage, r.mape, r.sufficient) == (0, None, None, False)


def test_sufficient_calibration_learns_bias_and_scale():
    r = calibrate(outcomes(6, D(900)))
    assert r.sufficient and r.bias_factor == D("0.9") and r.coverage == 1

    # scattered misses around an unbiased p50: the range is far too narrow -> widened (capped at the bound)
    scattered = [Outcome(D(950), D(1000), D(1050), D(a)) for a in (700, 1300, 700, 1300, 1000, 1000)]
    s = calibrate(scattered)
    assert s.bias_factor == 1 and s.interval_scale == D("3.0") and s.coverage == D("0.3333")


def test_a_consistent_bias_is_corrected_by_the_bias_factor_not_by_widening():
    """Every actual is exactly 1.2 x p50: the bias factor explains the whole miss, so the range may shrink."""
    s = calibrate([Outcome(D(950), D(1000), D(1050), D(1200)) for _ in range(6)])
    assert s.bias_factor == D("1.2") and s.interval_scale == D("0.5")


def test_bias_factor_is_bounded():
    assert calibrate(outcomes(6, D(100))).bias_factor == D("0.7")
    assert calibrate(outcomes(6, D(5000))).bias_factor == D("1.3")


def test_simulated_study_shows_calibration_improves_coverage_and_is_labelled():
    s = run_study(7)
    assert s.label == "SIMULATED"
    assert s.coverage_after > s.coverage_before and s.mape_after < s.mape_before


def test_simulated_study_is_reproducible():
    from app.cli.evaluate_simulation import study, summary

    first, second = study(range(1, 6)), study(range(1, 6))
    assert first == second and summary(first) == summary(second)
