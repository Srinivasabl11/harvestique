from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

from app.core.enums import WeatherKind
from app.domain.weather import DayWeather, is_stale, summarize
from tests.intelligence_factory import days


def day(d, tmax=30, tmin=20, rain=0):
    return DayWeather(d, D(tmin), D(tmax), D(rain), None, WeatherKind.OBSERVED)


def test_summary_features_by_hand():
    rows = [day(date(2026, 1, 1), 36, 20, 0), day(date(2026, 1, 2), 30, 20, 70), day(date(2026, 1, 3), 39, 21, 0)]
    s = summarize(rows, date(2026, 1, 1), date(2026, 1, 4))
    assert (s.days_expected, s.days_with_data, s.coverage) == (4, 3, D("0.75"))
    assert s.mean_temp_c == (D(28) + D(25) + D(30)) / 3
    assert s.gdd == D(18) + D(15) + D(20)  # mean - 10 C, per day
    assert (s.rain_mm, s.heat_stress_days, s.extreme_heat_days, s.heavy_rain_days) == (D(70), 2, 1, 1)


def test_dry_spell_counts_consecutive_dry_days_and_breaks_on_gaps():
    rows = (
        [day(date(2026, 1, i)) for i in (1, 2, 3)]
        + [day(date(2026, 1, 4), rain=5)]
        + [day(date(2026, 1, i)) for i in (5, 6)]
    )
    assert summarize(rows, date(2026, 1, 1), date(2026, 1, 6)).longest_dry_spell_days == 3
    gappy = [day(date(2026, 1, 1)), day(date(2026, 1, 2)), day(date(2026, 1, 5)), day(date(2026, 1, 6))]  # 3-4 missing
    assert summarize(gappy, date(2026, 1, 1), date(2026, 1, 6)).longest_dry_spell_days == 2  # gaps are not assumed dry


def test_no_data_is_reported_not_invented():
    s = summarize([], date(2026, 1, 1), date(2026, 1, 10))
    assert (s.days_with_data, s.coverage, s.mean_temp_c, s.rain_mm) == (0, 0, None, 0)


def test_days_outside_the_window_and_duplicates_are_ignored():
    rows = [*days(date(2026, 1, 1), 5), *days(date(2026, 1, 3), 1)]
    assert summarize(rows, date(2026, 1, 2), date(2026, 1, 3)).days_with_data == 2


def test_staleness():
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert is_stale(None, now, timedelta(hours=12))
    assert not is_stale(now - timedelta(hours=11), now, timedelta(hours=12))
    assert is_stale(now - timedelta(hours=13), now, timedelta(hours=12))
