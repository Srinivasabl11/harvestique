"""Builders for intelligence-layer unit tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D
from typing import Any

from app.core.enums import CropCategory, CycleStatus, IrrigationType, WeatherKind, WeatherStatus
from app.domain.prediction.models import CropProfile, CycleFacts, PredictionInput
from app.domain.weather import DayWeather, WeatherContext

TODAY = date(2026, 10, 1)
SOWN = date(2026, 8, 1)  # 61 days before TODAY


def crop(**kw: Any) -> CropProfile:
    base: dict[str, Any] = dict(
        name="Tomato",
        category=CropCategory.VEGETABLE,
        typical_duration_days=120,
        reference_yield_kg_per_acre=D(10000),
        reference_yield_cv=D("0.25"),
        water_need_mm=D(500),
    )
    return CropProfile(**{**base, **kw})


def cycle(**kw: Any) -> CycleFacts:
    base: dict[str, Any] = dict(
        area_acres=D(2), sowing_date=SOWN, status=CycleStatus.GROWING, irrigation=IrrigationType.RAINFED
    )
    return CycleFacts(**{**base, **kw})


def days(
    start: date, n: int, *, tmin: Any = 20, tmax: Any = 30, rain: Any = 5, kind: WeatherKind = WeatherKind.OBSERVED
) -> tuple[DayWeather, ...]:
    return tuple(
        DayWeather(start + timedelta(days=i), D(str(tmin)), D(str(tmax)), D(str(rain)), None, kind) for i in range(n)
    )


def weather(
    observed_rain: Any = 5, tmax: Any = 30, status: WeatherStatus = WeatherStatus.FRESH, forecast_tmax: Any = 30
) -> WeatherContext:
    n = (TODAY - SOWN).days
    return WeatherContext(
        status,
        observed=days(SOWN, n, tmax=tmax, rain=observed_rain),
        forecast=days(TODAY, 10, tmax=forecast_tmax, kind=WeatherKind.FORECAST),
    )


def inp(**kw: Any) -> PredictionInput:
    base = PredictionInput(crop=crop(), cycle=cycle(), today=TODAY, weather=weather())
    return replace(base, **kw)
