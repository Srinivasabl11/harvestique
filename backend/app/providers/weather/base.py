"""Weather provider contract (Open-Meteo is the planned real implementation)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class DailyWeather:
    day: date
    temp_min_c: float
    temp_max_c: float
    precipitation_mm: float
    et0_mm: float | None = None  # reference evapotranspiration


@dataclass(frozen=True, slots=True)
class WeatherSeries:
    latitude: float
    longitude: float
    days: tuple[DailyWeather, ...]
    source: str
    fetched_at: datetime
    is_forecast: bool


@dataclass(frozen=True, slots=True)
class CurrentWeather:
    """Model estimate of conditions now (Open-Meteo 'current'): NOT a station or rain-gauge reading."""

    time: datetime
    temperature_c: float
    humidity_pct: float | None
    precipitation_mm: float
    weather_code: int
    wind_kmh: float | None
    is_day: bool


@dataclass(frozen=True, slots=True)
class HourOutlook:
    time: datetime
    temperature_c: float | None
    precipitation_mm: float | None
    rain_probability_pct: float | None


@dataclass(frozen=True, slots=True)
class DayOutlook:
    day: date
    temp_min_c: float
    temp_max_c: float
    precipitation_mm: float
    rain_probability_pct: float | None
    weather_code: int | None


@dataclass(frozen=True, slots=True)
class WeatherNow:
    latitude: float
    longitude: float
    current: CurrentWeather
    hours: tuple[HourOutlook, ...]
    days: tuple[DayOutlook, ...]
    source: str
    fetched_at: datetime


@runtime_checkable
class WeatherProvider(Protocol):
    name: str

    def get_daily_forecast(self, latitude: float, longitude: float, days: int) -> WeatherSeries: ...

    def get_daily_history(self, latitude: float, longitude: float, start: date, end: date) -> WeatherSeries: ...

    def get_now(self, latitude: float, longitude: float) -> WeatherNow: ...
