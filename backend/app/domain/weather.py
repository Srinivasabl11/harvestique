"""Pure weather features for agronomic rules (no I/O).

Thresholds are documented constants. Heavy rain follows the India Meteorological Department category
(>= 64.5 mm/day); heat stress uses 35 C (most field crops lose yield above it).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.core.enums import WeatherKind, WeatherStatus

# WMO weather interpretation codes (as used by Open-Meteo) -> plain English
WMO_TEXT = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    85: "Snow showers",
    86: "Snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with hail",
}
RAIN_CODES = frozenset({51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99})


def weather_text(code: int | None) -> str:
    return "Unknown" if code is None else WMO_TEXT.get(code, "Unknown")


def raining_now(code: int, precipitation_mm: float) -> bool:
    """The MODEL says it is raining now (rain-type weather code or precipitation this interval)."""
    return code in RAIN_CODES or precipitation_mm > 0


D = Decimal
GDD_BASE_C = D(10)
HEAT_STRESS_C = D(35)
EXTREME_HEAT_C = D(38)
HEAVY_RAIN_MM = D("64.5")
DRY_DAY_MM = D(1)


@dataclass(frozen=True, slots=True)
class DayWeather:
    day: date
    tmin_c: Decimal
    tmax_c: Decimal
    rain_mm: Decimal
    et0_mm: Decimal | None
    kind: WeatherKind

    @property
    def mean_c(self) -> Decimal:
        return (self.tmin_c + self.tmax_c) / 2


@dataclass(frozen=True, slots=True)
class WeatherContext:
    status: WeatherStatus
    observed: tuple[DayWeather, ...] = ()
    forecast: tuple[DayWeather, ...] = ()
    fetched_at: datetime | None = None
    note: str = ""

    @classmethod
    def unavailable(cls, note: str) -> WeatherContext:
        return cls(WeatherStatus.UNAVAILABLE, note=note)


@dataclass(frozen=True, slots=True)
class WindowSummary:
    days_expected: int
    days_with_data: int
    coverage: Decimal  # 0..1
    mean_temp_c: Decimal | None
    gdd: Decimal
    rain_mm: Decimal
    heat_stress_days: int
    extreme_heat_days: int
    heavy_rain_days: int
    longest_dry_spell_days: int


def summarize(days: Sequence[DayWeather], start: date, end: date) -> WindowSummary:
    """Features of the days inside [start, end]. Missing days lower `coverage`; nothing is invented."""
    expected = max(0, (end - start).days + 1)
    inside = sorted((d for d in days if start <= d.day <= end), key=lambda d: d.day)
    unique = {d.day: d for d in inside}
    rows = [unique[k] for k in sorted(unique)]
    longest = run = 0
    prev: date | None = None
    for d in rows:
        consecutive = prev is not None and d.day == prev + timedelta(days=1)
        dry = d.rain_mm < DRY_DAY_MM
        run = (run + 1 if consecutive else 1) if dry else 0
        longest = max(longest, run)
        prev = d.day
    n = len(rows)
    return WindowSummary(
        days_expected=expected,
        days_with_data=n,
        coverage=D(n) / D(expected) if expected else D(0),
        mean_temp_c=sum((d.mean_c for d in rows), D(0)) / n if n else None,
        gdd=sum((max(D(0), d.mean_c - GDD_BASE_C) for d in rows), D(0)),
        rain_mm=sum((d.rain_mm for d in rows), D(0)),
        heat_stress_days=sum(1 for d in rows if d.tmax_c >= HEAT_STRESS_C),
        extreme_heat_days=sum(1 for d in rows if d.tmax_c >= EXTREME_HEAT_C),
        heavy_rain_days=sum(1 for d in rows if d.rain_mm >= HEAVY_RAIN_MM),
        longest_dry_spell_days=longest,
    )


def is_stale(fetched_at: datetime | None, now: datetime, max_age: timedelta) -> bool:
    return fetched_at is None or now - fetched_at > max_age
