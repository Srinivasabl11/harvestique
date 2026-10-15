from datetime import date

import pytest

from app.core.clock import FixedClock
from app.providers.llm.base import LLMMessage, LLMProvider, LLMRequest
from app.providers.llm.fake import FakeLLMProvider
from app.providers.notifications.base import NotificationChannel
from app.providers.registry import build_llm_provider, build_notification_channel, build_weather_provider
from app.providers.weather.base import WeatherProvider
from app.providers.weather.fake import FakeWeatherProvider


def test_registry_builds_fakes(settings):
    assert isinstance(build_weather_provider(settings), WeatherProvider)
    assert isinstance(build_llm_provider(settings), LLMProvider)
    assert isinstance(build_notification_channel(settings), NotificationChannel)


@pytest.mark.parametrize(
    ("field", "value", "builder", "name"),
    [
        ("llm_provider", "ollama", build_llm_provider, "ollama"),  # Phase 6: implemented (optional, local)
        ("notification_channel", "in_app", build_notification_channel, "in_app"),  # Phase 6: in-app feed
    ],
)
def test_phase6_providers_are_built(settings, field, value, builder, name):
    assert builder(settings.model_copy(update={field: value})).name == name


def test_fake_weather_is_deterministic():
    p = FakeWeatherProvider()
    a = p.get_daily_history(12.3, 76.6, date(2026, 1, 1), date(2026, 1, 10))
    b = p.get_daily_history(12.3, 76.6, date(2026, 1, 1), date(2026, 1, 10))
    assert a.days == b.days and len(a.days) == 10


def test_fake_weather_forecast_limits():
    with pytest.raises(ValueError):
        FakeWeatherProvider().get_daily_forecast(0, 0, 30)


def test_fake_llm_records_requests():
    llm = FakeLLMProvider()
    llm.generate(LLMRequest(messages=(LLMMessage("user", "hi"),)))
    assert len(llm.requests) == 1


def test_fixed_clock_requires_tz():
    from datetime import datetime

    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 1, 1))


def test_open_meteo_is_built_when_configured(settings):
    from app.providers.registry import build_prediction_provider
    from app.providers.weather.open_meteo import OpenMeteoWeatherProvider

    provider = build_weather_provider(settings.model_copy(update={"weather_provider": "open_meteo"}))
    assert isinstance(provider, OpenMeteoWeatherProvider) and isinstance(provider, WeatherProvider)
    predictor = build_prediction_provider(settings)
    assert predictor.name == "hybrid-rules" and predictor.version
