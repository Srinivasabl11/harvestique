"""Weather Intelligence: Open-Meteo via the provider, cached in PostgreSQL, degrading safely.

refresh succeeds           -> FRESH (cache updated)
refresh fails, cache exists -> STALE (cached rows served, uncertainty widened downstream)
nothing at all             -> UNAVAILABLE (predictions continue without weather, with wider ranges)
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.config import Settings
from app.core.enums import DataKind, WeatherKind, WeatherStatus
from app.core.errors import DomainValidationError, NotFoundError, ProviderUnavailableError
from app.domain.weather import DayWeather, WeatherContext, is_stale, raining_now, weather_text
from app.models.intelligence import WeatherDaily
from app.providers.weather.base import WeatherNow, WeatherProvider, WeatherSeries
from app.repositories.farms import FarmRepository
from app.repositories.intelligence import WeatherRepository
from app.schemas.intelligence import (
    FarmWeatherOut,
    WeatherCurrentOut,
    WeatherDayOut,
    WeatherDayOutlookOut,
    WeatherHourOut,
    WeatherNowOut,
)

logger = logging.getLogger(__name__)
GRID = Decimal("0.01")
MAX_HISTORY_DAYS = 365


def grid(value: Decimal) -> Decimal:
    return value.quantize(GRID)


# current-conditions cache: (location grid) -> (stored at, data). Per process; lost on restart, which is fine.
_NOW_CACHE: dict[tuple[Decimal, Decimal], tuple[datetime, WeatherNow]] = {}
NOW_TTL = timedelta(minutes=15)
NOW_STALE_LIMIT = timedelta(hours=6)
IST = timezone(timedelta(hours=5, minutes=30))


def local_today(now: datetime) -> date:
    """The farm-local calendar day (farms are in India; Open-Meteo dates are local days)."""
    return now.astimezone(IST).date()


class WeatherService:
    def __init__(
        self, *, session: Session, repo: WeatherRepository, provider: WeatherProvider, clock: Clock, settings: Settings
    ) -> None:
        self._session = session
        self._repo = repo
        self._provider = provider
        self._clock = clock
        self._max_age = timedelta(hours=settings.weather_forecast_max_age_hours)

    def context(self, lat: Decimal | None, lon: Decimal | None, season_start: date) -> WeatherContext:
        if lat is None or lon is None:
            return WeatherContext.unavailable("the farm has no coordinates")
        now = self._clock.now()
        today = local_today(now)  # forecast dates are farm-local days; the UTC date is yesterday before 05:30 IST
        la, lo = grid(lat), grid(lon)
        refreshed, problem = self._refresh(la, lo, season_start, today, now)
        observed = self._repo.rows(
            la,
            lo,
            WeatherKind.OBSERVED,
            max(season_start, today - timedelta(days=MAX_HISTORY_DAYS)),
            today - timedelta(days=1),
        )
        forecast = self._repo.rows(la, lo, WeatherKind.FORECAST, today, today + timedelta(days=16))
        if not observed and not forecast:
            return WeatherContext.unavailable(problem or "no weather data")
        fetched = self._repo.last_fetched(la, lo, WeatherKind.FORECAST)
        stale = not refreshed or is_stale(fetched, now, self._max_age)
        return WeatherContext(
            status=WeatherStatus.STALE if stale else WeatherStatus.FRESH,
            observed=tuple(self._day(r) for r in observed),
            forecast=tuple(self._day(r) for r in forecast),
            fetched_at=fetched,
            note=problem or "",
        )

    def farm_now(self, owner_id: uuid.UUID, farm_id: uuid.UUID) -> WeatherNowOut:
        """Current conditions, rain chance for the next hours and 7 days for the farm card. Cached 15 minutes per
        location; when Open-Meteo cannot be reached, the last copy (up to 6 h old) is shown as STALE."""
        farm = FarmRepository(self._session).get_owned(farm_id, owner_id)
        if farm is None:
            raise NotFoundError("Farm not found")
        if farm.latitude is None or farm.longitude is None:
            return WeatherNowOut(
                farm_id=farm.id,
                status=WeatherStatus.UNAVAILABLE,
                fetched_at=None,
                source="",
                current=None,
                next_hours=[],
                days=[],
                note="Add the farm location (latitude and longitude) to get weather: open the farm, then Edit farm.",
            )
        key = (grid(farm.latitude), grid(farm.longitude))
        now = self._clock.now()
        cached = _NOW_CACHE.get(key)
        status = WeatherStatus.FRESH
        if cached is None or now - cached[0] >= NOW_TTL:
            try:
                data = self._provider.get_now(float(key[0]), float(key[1]))
                _NOW_CACHE[key] = (now, data)
                cached = (now, data)
            except (ProviderUnavailableError, AttributeError):
                if cached is None or now - cached[0] >= NOW_STALE_LIMIT:
                    return WeatherNowOut(
                        farm_id=farm.id,
                        status=WeatherStatus.UNAVAILABLE,
                        fetched_at=None,
                        source="open_meteo",
                        current=None,
                        next_hours=[],
                        days=[],
                        note="Weather could not be loaded right now (no connection to Open-Meteo). Try again later.",
                    )
                status = WeatherStatus.STALE
        stored_at, w = cached
        simulated = w.source == "fake"
        note = (
            "SIMULATED weather (test data), not a real forecast."
            if simulated
            else "Model estimates from Open-Meteo (free), not measurements on your farm. A rain chance is a "
            "probability, not a promise, and 'raining now' is the model's estimate, not a rain gauge."
        )
        if status is WeatherStatus.STALE:
            note = (
                f"Could not refresh: showing the weather loaded at {stored_at.astimezone(IST).strftime('%H:%M')}. "
                + note
            )
        c = w.current
        return WeatherNowOut(
            farm_id=farm.id,
            status=status,
            fetched_at=stored_at,
            source=w.source,
            current=WeatherCurrentOut(
                time=c.time,
                temperature_c=c.temperature_c,
                humidity_pct=c.humidity_pct,
                condition=weather_text(c.weather_code),
                weather_code=c.weather_code,
                raining_now=raining_now(c.weather_code, c.precipitation_mm),
                precipitation_mm=c.precipitation_mm,
                wind_kmh=c.wind_kmh,
                is_day=c.is_day,
            ),
            next_hours=[
                WeatherHourOut(
                    time=h.time,
                    temperature_c=h.temperature_c,
                    rain_probability_pct=h.rain_probability_pct,
                    precipitation_mm=h.precipitation_mm,
                )
                for h in w.hours
                if h.time + timedelta(hours=1) > now  # this hour onwards (a cached answer can be up to 15 min old)
            ],
            days=[
                WeatherDayOutlookOut(
                    day=d.day,
                    tmin_c=d.temp_min_c,
                    tmax_c=d.temp_max_c,
                    rain_mm=d.precipitation_mm,
                    rain_probability_pct=d.rain_probability_pct,
                    condition=weather_text(d.weather_code),
                )
                for d in w.days
                if d.day >= local_today(now)  # never "yesterday" first, e.g. just after midnight
            ],
            note=note,
        )

    def farm_weather(self, owner_id: uuid.UUID, farm_id: uuid.UUID, days: int) -> FarmWeatherOut:
        farm = FarmRepository(self._session).get_owned(farm_id, owner_id)
        if farm is None:
            raise NotFoundError("Farm not found")
        if farm.latitude is None or farm.longitude is None:
            raise DomainValidationError(
                "Add latitude and longitude to the farm to get weather", code="farm_location_missing"
            )
        today = local_today(self._clock.now())
        ctx = self.context(farm.latitude, farm.longitude, today - timedelta(days=14))
        self._session.commit()

        def out(d: DayWeather) -> WeatherDayOut:
            kind = DataKind.MEASURED if d.kind is WeatherKind.OBSERVED else DataKind.ESTIMATE
            return WeatherDayOut(
                day=d.day, kind=d.kind, data_kind=kind, tmin_c=d.tmin_c, tmax_c=d.tmax_c, rain_mm=d.rain_mm
            )

        return FarmWeatherOut(
            farm_id=farm.id,
            status=ctx.status,
            fetched_at=ctx.fetched_at,
            note=ctx.note,
            forecast=[out(d) for d in ctx.forecast[:days]],
            recent=[out(d) for d in ctx.observed[-14:]],
        )

    # ------------------------------------------------------------- internals

    def _refresh(
        self, la: Decimal, lo: Decimal, season_start: date, today: date, now: datetime
    ) -> tuple[bool, str | None]:
        """Fetch only when the cached forecast is old. Returns (cache is current, problem description)."""
        if not is_stale(self._repo.last_fetched(la, lo, WeatherKind.FORECAST), now, self._max_age):
            return True, None
        try:
            forecast = self._provider.get_daily_forecast(float(la), float(lo), 16)
            history = None
            start = max(season_start, today - timedelta(days=MAX_HISTORY_DAYS))
            if start < today:
                history = self._provider.get_daily_history(float(la), float(lo), start, today - timedelta(days=1))
        except (ProviderUnavailableError, ValueError) as exc:
            logger.warning("weather refresh failed for %s,%s: %s", la, lo, exc)
            return False, f"weather service unavailable ({exc})"
        self._repo.upsert(self._rows(la, lo, forecast, WeatherKind.FORECAST, now))
        if history is not None:
            self._repo.upsert(self._rows(la, lo, history, WeatherKind.OBSERVED, now))
        self._session.flush()
        return True, None

    @staticmethod
    def _rows(
        la: Decimal, lo: Decimal, series: WeatherSeries, kind: WeatherKind, now: datetime
    ) -> list[dict[str, object]]:
        return [
            {
                "id": uuid.uuid4(),
                "lat_key": la,
                "lon_key": lo,
                "day": d.day,
                "kind": kind,
                "tmin_c": Decimal(str(d.temp_min_c)).quantize(Decimal("0.01")),
                "tmax_c": Decimal(str(d.temp_max_c)).quantize(Decimal("0.01")),
                "rain_mm": Decimal(str(d.precipitation_mm)).quantize(Decimal("0.01")),
                "et0_mm": Decimal(str(d.et0_mm)).quantize(Decimal("0.01")) if d.et0_mm is not None else None,
                "source": series.source,
                "fetched_at": now,
            }
            for d in series.days
        ]

    @staticmethod
    def _day(r: WeatherDaily) -> DayWeather:
        return DayWeather(r.day, r.tmin_c, r.tmax_c, r.rain_mm, r.et0_mm, r.kind)
