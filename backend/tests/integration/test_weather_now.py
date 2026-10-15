"""The farm weather card: current conditions and rain chance (model estimates), cached, with honest fallbacks."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from app.core.errors import ProviderUnavailableError
from app.providers.weather.fake import FakeWeatherProvider
from app.providers.weather.open_meteo import OpenMeteoWeatherProvider
from app.services import weather as weather_service

pytestmark = pytest.mark.integration
API = "/api/v1"


@pytest.fixture(autouse=True)
def empty_cache():
    weather_service._NOW_CACHE.clear()
    yield
    weather_service._NOW_CACHE.clear()


class Counting(FakeWeatherProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.down = False

    def get_now(self, latitude, longitude):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.down:
            raise ProviderUnavailableError("Open-Meteo unreachable")
        return super().get_now(latitude, longitude)


def now(client, actor, farm_id):
    r = client.get(f"{API}/farms/{farm_id}/weather/now", headers=actor.headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_card_shows_current_conditions_and_rain_chance(db_client, farmer, geo_farm):
    w = now(db_client, farmer, geo_farm["id"])
    assert w["status"] == "fresh" and w["source"] == "fake" and "SIMULATED" in w["note"]  # never passed off as real
    assert w["current"]["condition"] and isinstance(w["current"]["raining_now"], bool)
    assert len(w["next_hours"]) == 12 and len(w["days"]) == 7
    assert w["days"][2]["condition"] == "Light rain" and w["days"][0]["rain_probability_pct"] == 40


def test_a_farm_without_location_gets_guidance_not_an_error(db_client, farmer, api):
    farm = api.farm(farmer, name="No GPS farm")
    w = now(db_client, farmer, farm["id"])
    assert w["status"] == "unavailable" and w["current"] is None and "Edit farm" in w["note"]


def test_another_farmers_farm_is_not_found(db_client, other_farmer, geo_farm):
    assert db_client.get(f"{API}/farms/{geo_farm['id']}/weather/now", headers=other_farmer.headers).status_code == 404


def test_cached_for_15_minutes_then_stale_when_offline_then_unavailable(
    db_client, db_container, farmer, geo_farm, fixed_clock
):
    provider = Counting()
    db_container.weather = provider
    now(db_client, farmer, geo_farm["id"])
    now(db_client, farmer, geo_farm["id"])
    assert provider.calls == 1  # second view within 15 minutes: no new request
    fixed_clock.advance_to(fixed_clock.now() + timedelta(minutes=16))
    provider.down = True
    from tests.conftest import relogin

    h = relogin(db_client)
    w = db_client.get(f"{API}/farms/{geo_farm['id']}/weather/now", headers=h).json()
    assert w["status"] == "stale" and "Could not refresh" in w["note"] and w["current"] is not None
    fixed_clock.advance_to(fixed_clock.now() + timedelta(hours=7))
    h = relogin(db_client)
    w = db_client.get(f"{API}/farms/{geo_farm['id']}/weather/now", headers=h).json()
    assert w["status"] == "unavailable" and w["current"] is None  # too old to show


def test_open_meteo_payload_is_parsed_with_the_local_time_zone():
    payload = {
        "utc_offset_seconds": 19800,
        "current": {
            "time": "2026-10-10T15:00",
            "temperature_2m": 29.4,
            "relative_humidity_2m": 61,
            "precipitation": 0.4,
            "weather_code": 61,
            "wind_speed_10m": 9.7,
            "is_day": 1,
        },
        "hourly": {
            "time": ["2026-10-10T15:00", "2026-10-10T16:00"],
            "temperature_2m": [29.4, 28.8],
            "precipitation": [0.4, 0.0],
            "precipitation_probability": [70, None],
        },
        "daily": {
            "time": ["2026-10-10", "2026-10-11"],
            "weather_code": [61, 3],
            "temperature_2m_max": [31.0, 32.5],
            "temperature_2m_min": [20.1, 20.9],
            "precipitation_sum": [3.2, 0.0],
            "precipitation_probability_max": [80, 15],
        },
    }
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=payload)

    p = OpenMeteoWeatherProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://api.open-meteo.com/v1",
        archive_url="https://archive-api.open-meteo.com/v1",
    )
    w = p.get_now(12.3, 76.64)
    assert "precipitation_probability" in seen["hourly"] and seen["forecast_days"] == "7"
    assert w.current.temperature_c == 29.4 and w.current.weather_code == 61
    assert w.current.time.utcoffset() == timedelta(hours=5, minutes=30)
    assert w.hours[1].rain_probability_pct is None  # missing values stay missing, never guessed
    assert w.days[0].rain_probability_pct == 80

    bad = OpenMeteoWeatherProvider(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"current": {}}))),
        base_url="https://x",
        archive_url="https://y",
    )
    with pytest.raises(ProviderUnavailableError):
        bad.get_now(1, 1)


def test_just_after_midnight_yesterday_and_past_hours_are_not_shown(db_client, db_container, farmer, geo_farm):
    """Seen on the phone at 00:01 IST: the outlook started with yesterday and the hours with 23:00."""
    from datetime import UTC, datetime

    from app.providers.weather.base import CurrentWeather, DayOutlook, HourOutlook, WeatherNow
    from app.services.weather import IST

    class Stale(FakeWeatherProvider):
        def get_now(self, latitude, longitude):  # type: ignore[no-untyped-def]
            real_now = datetime.now(UTC)
            today = real_now.astimezone(IST).date()
            hours = tuple(HourOutlook(real_now + timedelta(hours=h), 25.0, 0.0, 10.0) for h in (-3, -1.5, 0.5, 2))
            days = tuple(DayOutlook(today + timedelta(days=d), 20, 30, 0, 10.0, 3) for d in (-1, 0, 1))
            return WeatherNow(
                latitude,
                longitude,
                CurrentWeather(real_now, 25.0, 60.0, 0.0, 3, 5.0, True),
                hours,
                days,
                "fake",
                real_now,
            )

    db_container.weather = Stale()
    w = now(db_client, farmer, geo_farm["id"])
    today = datetime.now(UTC).astimezone(IST).date()
    assert [d["day"] for d in w["days"]] == [today.isoformat(), (today + timedelta(days=1)).isoformat()]
    assert len(w["next_hours"]) == 2  # the hours that already ended are gone
