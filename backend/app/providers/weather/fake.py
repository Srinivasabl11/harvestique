"""Deterministic weather provider for tests, offline development and simulations."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

from app.providers.weather.base import CurrentWeather, DailyWeather, DayOutlook, HourOutlook, WeatherNow, WeatherSeries


class FakeWeatherProvider:
    name = "fake"

    def __init__(self, base_temp_c: float = 26.0, base_rain_mm: float = 3.0) -> None:
        self._base_temp = base_temp_c
        self._base_rain = base_rain_mm

    def _day(self, d: date) -> DailyWeather:
        phase = math.sin(d.toordinal() / 58.0)  # smooth, repeatable seasonal-ish signal
        return DailyWeather(
            day=d,
            temp_min_c=round(self._base_temp - 6 + 2 * phase, 2),
            temp_max_c=round(self._base_temp + 5 + 2 * phase, 2),
            precipitation_mm=round(max(0.0, self._base_rain * (1 + phase)), 2),
            et0_mm=round(4.0 + phase, 2),
        )

    def get_daily_forecast(self, latitude: float, longitude: float, days: int) -> WeatherSeries:
        if not 1 <= days <= 16:
            raise ValueError("days must be within 1..16 (Open-Meteo forecast limit)")
        today = datetime.now(UTC).date()
        return WeatherSeries(
            latitude=latitude,
            longitude=longitude,
            days=tuple(self._day(today + timedelta(days=i)) for i in range(days)),
            source=self.name,
            fetched_at=datetime.now(UTC),
            is_forecast=True,
        )

    def get_daily_history(self, latitude: float, longitude: float, start: date, end: date) -> WeatherSeries:
        if end < start:
            raise ValueError("end must be >= start")
        n = (end - start).days + 1
        return WeatherSeries(
            latitude=latitude,
            longitude=longitude,
            days=tuple(self._day(start + timedelta(days=i)) for i in range(n)),
            source=self.name,
            fetched_at=datetime.now(UTC),
            is_forecast=False,
        )

    def get_now(self, latitude: float, longitude: float) -> WeatherNow:
        """SIMULATED (tests and demo only; production refuses the fake provider)."""
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        today = (now + timedelta(hours=5, minutes=30)).date()  # like Open-Meteo with timezone=auto: local (IST) days
        d0 = self._day(today)
        return WeatherNow(
            latitude=latitude,
            longitude=longitude,
            current=CurrentWeather(now, d0.temp_max_c - 3, 70.0, 0.0, 3, 8.0, True),
            hours=tuple(
                HourOutlook(now + timedelta(hours=i), d0.temp_max_c - 3, 0.0, 10.0 * (i % 3)) for i in range(12)
            ),
            days=tuple(
                DayOutlook(
                    today + timedelta(days=i),
                    self._day(today + timedelta(days=i)).temp_min_c,
                    self._day(today + timedelta(days=i)).temp_max_c,
                    self._day(today + timedelta(days=i)).precipitation_mm,
                    40.0,
                    61 if i == 2 else 3,
                )
                for i in range(7)
            ),
            source=self.name,
            fetched_at=datetime.now(UTC),
        )
