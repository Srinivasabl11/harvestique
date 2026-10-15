"""Open-Meteo adapter (free, no API key). https://open-meteo.com/en/docs

* forecast  : /v1/forecast  (daily, up to 16 days)
* history   : archive-api /v1/archive (ERA5 reanalysis; usually lags real time by ~5 days)
Every transport, HTTP or payload problem becomes ProviderUnavailableError; callers fall back to cache.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import InvalidOperation
from typing import Any

import httpx

from app.core.errors import ProviderUnavailableError
from app.providers.weather.base import (
    CurrentWeather,
    DailyWeather,
    DayOutlook,
    HourOutlook,
    WeatherNow,
    WeatherSeries,
)

DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum,et0_fao_evapotranspiration"
NOW_CURRENT = "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,is_day"
NOW_HOURLY = "temperature_2m,precipitation,precipitation_probability"
NOW_DAILY = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max"


class OpenMeteoWeatherProvider:
    name = "open_meteo"

    def __init__(self, *, client: httpx.Client, base_url: str, archive_url: str) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._archive = archive_url.rstrip("/")

    def get_daily_forecast(self, latitude: float, longitude: float, days: int) -> WeatherSeries:
        if not 1 <= days <= 16:
            raise ValueError("days must be within 1..16 (Open-Meteo forecast limit)")
        payload = self._get(
            f"{self._base}/forecast",
            {"latitude": latitude, "longitude": longitude, "daily": DAILY, "forecast_days": days, "timezone": "auto"},
        )
        return self._series(payload, latitude, longitude, is_forecast=True)

    def get_daily_history(self, latitude: float, longitude: float, start: date, end: date) -> WeatherSeries:
        if end < start:
            raise ValueError("end must be >= start")
        payload = self._get(
            f"{self._archive}/archive",
            {
                "latitude": latitude,
                "longitude": longitude,
                "daily": DAILY,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "timezone": "auto",
            },
        )
        return self._series(payload, latitude, longitude, is_forecast=False)

    def get_now(self, latitude: float, longitude: float) -> WeatherNow:
        """Current conditions, the next 12 hours and 7 days, all from Open-Meteo's forecast model."""
        data = self._get(
            f"{self._base}/forecast",
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": NOW_CURRENT,
                "hourly": NOW_HOURLY,
                "daily": NOW_DAILY,
                "forecast_days": 7,
                "forecast_hours": 12,
                "timezone": "auto",
            },
        )
        try:
            tz = timezone(timedelta(seconds=int(data.get("utc_offset_seconds", 0))))

            def local(t: str) -> datetime:
                return datetime.fromisoformat(t).replace(tzinfo=tz)

            c = data["current"]
            current = CurrentWeather(
                time=local(c["time"]),
                temperature_c=float(c["temperature_2m"]),
                humidity_pct=None if c.get("relative_humidity_2m") is None else float(c["relative_humidity_2m"]),
                precipitation_mm=float(c.get("precipitation") or 0.0),
                weather_code=int(c["weather_code"]),
                wind_kmh=None if c.get("wind_speed_10m") is None else float(c["wind_speed_10m"]),
                is_day=bool(c.get("is_day", 1)),
            )
            h = data["hourly"]
            hours = tuple(
                HourOutlook(
                    time=local(t),
                    temperature_c=_opt(h.get("temperature_2m"), i),
                    precipitation_mm=_opt(h.get("precipitation"), i),
                    rain_probability_pct=_opt(h.get("precipitation_probability"), i),
                )
                for i, t in enumerate(h["time"])
            )
            d = data["daily"]
            days = tuple(
                DayOutlook(
                    day=date.fromisoformat(t),
                    temp_min_c=float(d["temperature_2m_min"][i]),
                    temp_max_c=float(d["temperature_2m_max"][i]),
                    precipitation_mm=float(d["precipitation_sum"][i] or 0.0),
                    rain_probability_pct=_opt(d.get("precipitation_probability_max"), i),
                    weather_code=None
                    if d.get("weather_code") is None or d["weather_code"][i] is None
                    else int(d["weather_code"][i]),
                )
                for i, t in enumerate(d["time"])
                if d["temperature_2m_min"][i] is not None and d["temperature_2m_max"][i] is not None
            )
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ProviderUnavailableError("Open-Meteo returned an unexpected current-weather payload") from exc
        return WeatherNow(latitude, longitude, current, hours, days, self.name, datetime.now(UTC))

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Open-Meteo request failed: {exc.__class__.__name__}") from exc
        if response.status_code != 200:
            raise ProviderUnavailableError(f"Open-Meteo returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderUnavailableError("Open-Meteo returned invalid JSON") from exc
        if not isinstance(data, dict) or data.get("error"):
            raise ProviderUnavailableError(
                f"Open-Meteo error: {data.get('reason') if isinstance(data, dict) else 'bad payload'}"
            )
        return data

    def _series(self, data: dict[str, Any], lat: float, lon: float, *, is_forecast: bool) -> WeatherSeries:
        daily = data.get("daily")
        if not isinstance(daily, dict):
            raise ProviderUnavailableError("Open-Meteo payload has no daily data")
        try:
            times = daily["time"]
            tmax, tmin = daily["temperature_2m_max"], daily["temperature_2m_min"]
            rain = daily["precipitation_sum"]
            et0 = daily.get("et0_fao_evapotranspiration") or [None] * len(times)
            days = tuple(
                DailyWeather(
                    day=date.fromisoformat(t),
                    temp_min_c=float(lo),
                    temp_max_c=float(hi),
                    precipitation_mm=float(p),
                    et0_mm=float(e) if e is not None else None,
                )
                for t, hi, lo, p, e in zip(times, tmax, tmin, rain, et0, strict=True)
                if hi is not None and lo is not None and p is not None  # skip gaps; never invent values
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ProviderUnavailableError("Open-Meteo payload is malformed") from exc
        return WeatherSeries(lat, lon, days, self.name, datetime.now(UTC), is_forecast)


def _opt(values: list[Any] | None, i: int) -> float | None:
    if values is None or i >= len(values) or values[i] is None:
        return None
    return float(values[i])
