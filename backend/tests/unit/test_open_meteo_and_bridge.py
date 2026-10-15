from datetime import date
from decimal import Decimal as D

import httpx
import pytest

from app.core.enums import EstimateBasis
from app.core.errors import ProviderUnavailableError
from app.domain.planning.models import Range
from app.domain.prediction.engine import RuleBasedPredictor
from app.domain.prediction.models import PastHarvest
from app.domain.prediction.planning_bridge import PredictionNotUsable, basis_from_sources, planning_estimate
from app.providers.weather.open_meteo import OpenMeteoWeatherProvider
from tests.intelligence_factory import SOWN, crop, inp

GOOD = {
    "daily": {
        "time": ["2026-10-01", "2026-10-02", "2026-10-03"],
        "temperature_2m_max": [31.2, None, 29.0],
        "temperature_2m_min": [20.1, 19.0, 18.5],
        "precipitation_sum": [0.0, 3.0, 12.4],
        "et0_fao_evapotranspiration": [4.1, 3.9, None],
    }
}


def provider(handler):
    return OpenMeteoWeatherProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://api.open-meteo.com/v1",
        archive_url="https://archive-api.open-meteo.com/v1",
    )


def test_forecast_is_parsed_and_gaps_are_skipped_not_invented():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        seen["path"] = request.url.path
        return httpx.Response(200, json=GOOD)

    s = provider(handler).get_daily_forecast(12.3, 76.6, 3)
    assert seen["path"] == "/v1/forecast" and seen["forecast_days"] == "3" and "precipitation_sum" in seen["daily"]
    assert [d.day for d in s.days] == [date(2026, 10, 1), date(2026, 10, 3)]  # the day with a missing max is dropped
    assert s.days[0].temp_max_c == 31.2 and s.days[1].et0_mm is None and s.is_forecast


def test_history_uses_the_archive_endpoint():
    seen = {}

    def handler(request):
        seen["host"], seen["params"] = request.url.host, dict(request.url.params)
        return httpx.Response(200, json=GOOD)

    s = provider(handler).get_daily_history(12.3, 76.6, date(2026, 9, 1), date(2026, 9, 30))
    assert (
        seen["host"] == "archive-api.open-meteo.com"
        and seen["params"]["start_date"] == "2026-09-01"
        and not s.is_forecast
    )


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(500, text="boom"),
        lambda r: httpx.Response(200, text="not json"),
        lambda r: httpx.Response(200, json={"error": True, "reason": "bad coords"}),
        lambda r: httpx.Response(200, json={"hourly": {}}),
        lambda r: httpx.Response(200, json={"daily": {"time": ["2026-10-01"], "temperature_2m_max": [30]}}),
    ],
)
def test_every_failure_becomes_provider_unavailable(handler):
    with pytest.raises(ProviderUnavailableError):
        provider(handler).get_daily_forecast(12.3, 76.6, 3)


def test_network_errors_and_timeouts_become_provider_unavailable():
    def boom(request):
        raise httpx.ConnectTimeout("slow", request=request)

    with pytest.raises(ProviderUnavailableError):
        provider(boom).get_daily_forecast(12.3, 76.6, 3)


def test_forecast_day_limits():
    with pytest.raises(ValueError):
        provider(lambda r: httpx.Response(200, json=GOOD)).get_daily_forecast(0, 0, 17)


# ------------------------------------------------------------------ bridge


def test_bridge_turns_quantiles_into_a_planning_range():
    pred = RuleBasedPredictor().predict(inp())
    est = planning_estimate(pred, SOWN)
    y = pred.yield_per_acre_kg
    assert (est.yield_per_acre_kg.low, est.yield_per_acre_kg.expected, est.yield_per_acre_kg.high) == (
        y.p10,
        y.p50,
        y.p90,
    )
    assert est.duration_days == (pred.timing.start_p50 - SOWN).days
    assert est.harvest_window_days == (pred.timing.end_p90 - pred.timing.start_p50).days + 1
    assert est.estimate_basis is EstimateBasis.ASSUMPTION  # reference only


def test_bridge_basis_reflects_the_evidence():
    with_hist = RuleBasedPredictor().predict(inp(history=(PastHarvest(D(9000), date(2025, 1, 1)),)))
    with_est = RuleBasedPredictor().predict(inp(farmer_estimate=Range(D(1), D(2), D(3))))
    assert basis_from_sources(with_hist.sources) is EstimateBasis.OWN_RECORDS
    assert basis_from_sources(with_est.sources) is EstimateBasis.LOCAL_KNOWLEDGE


def test_bridge_refuses_insufficient_predictions():
    with pytest.raises(PredictionNotUsable):
        planning_estimate(RuleBasedPredictor().predict(inp(crop=crop(reference_yield_kg_per_acre=None))), SOWN)
