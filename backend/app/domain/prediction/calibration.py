"""Prediction feedback (error metrics) and calibration from recorded outcomes.

Calibration is applied only when at least MIN_SAMPLES outcomes exist. Below that the profile is reported as
`insufficient` and has no effect; no accuracy figure is ever invented.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

D = Decimal
MIN_SAMPLES = 5
TARGET_COVERAGE = D("0.8")  # p10-p90 should contain 80% of outcomes
BIAS_BOUNDS = (D("0.7"), D("1.3"))
SCALE_BOUNDS = (D("0.5"), D("3.0"))


def _q(x: Decimal, p: str = "0.0001") -> Decimal:
    return x.quantize(D(p), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class FeedbackMetrics:
    signed_error_kg: Decimal  # actual - p50
    abs_error_kg: Decimal
    abs_pct_error: Decimal | None  # None when the actual is 0
    within_interval: bool  # p10 <= actual <= p90
    pinball_loss: Decimal  # mean quantile loss at 0.1 / 0.5 / 0.9
    date_error_days: int | None  # actual start - predicted p50 start
    date_within_window: bool | None


def pinball(q: Decimal, tau: Decimal, actual: Decimal) -> Decimal:
    diff = actual - q
    return max(tau * diff, (tau - 1) * diff)


def feedback(
    p10: Decimal,
    p50: Decimal,
    p90: Decimal,
    actual: Decimal,
    start_p10: date | None,
    start_p50: date | None,
    start_p90: date | None,
    actual_start: date | None,
) -> FeedbackMetrics:
    signed = actual - p50
    loss = (pinball(p10, D("0.1"), actual) + pinball(p50, D("0.5"), actual) + pinball(p90, D("0.9"), actual)) / 3
    date_err = (actual_start - start_p50).days if actual_start and start_p50 else None
    within_date = start_p10 <= actual_start <= start_p90 if actual_start and start_p10 and start_p90 else None
    return FeedbackMetrics(
        signed_error_kg=_q(signed, "0.001"),
        abs_error_kg=_q(abs(signed), "0.001"),
        abs_pct_error=_q(abs(signed) / actual * 100, "0.01") if actual > 0 else None,
        within_interval=p10 <= actual <= p90,
        pinball_loss=_q(loss, "0.001"),
        date_error_days=date_err,
        date_within_window=within_date,
    )


@dataclass(frozen=True, slots=True)
class Outcome:
    p10: Decimal
    p50: Decimal
    p90: Decimal
    actual: Decimal
    date_error_days: int | None = None


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    sample_size: int
    sufficient: bool
    coverage: Decimal | None
    mape: Decimal | None
    bias_factor: Decimal
    interval_scale: Decimal
    date_mae_days: Decimal | None
    note: str


def _quantile(values: Sequence[Decimal], q: Decimal) -> Decimal:
    s = sorted(values)
    idx = D(len(s) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def calibrate(outcomes: Sequence[Outcome], min_samples: int = MIN_SAMPLES) -> CalibrationResult:
    n = len(outcomes)
    if n == 0:
        return CalibrationResult(
            0, False, None, None, D(1), D(1), None, f"No recorded outcomes yet; at least {min_samples} are needed."
        )
    coverage = _q(D(sum(1 for o in outcomes if o.p10 <= o.actual <= o.p90)) / n)
    apes = [abs(o.actual - o.p50) / o.actual * 100 for o in outcomes if o.actual > 0]
    mape = _q(sum(apes, D(0)) / len(apes), "0.01") if apes else None
    dates = [abs(D(o.date_error_days)) for o in outcomes if o.date_error_days is not None]
    date_mae = _q(sum(dates, D(0)) / len(dates), "0.1") if dates else None
    if n < min_samples:
        return CalibrationResult(
            n,
            False,
            coverage,
            mape,
            D(1),
            D(1),
            date_mae,
            f"Only {n} outcome(s); at least {min_samples} needed. Descriptive only; not applied.",
        )
    ratios = [o.actual / o.p50 for o in outcomes if o.p50 > 0]
    bias = _q(min(BIAS_BOUNDS[1], max(BIAS_BOUNDS[0], _quantile(ratios, D("0.5")))) if ratios else D(1))
    # split-conformal style: how many half-widths away were the actuals? Scale so ~80% fall inside.
    resid = [abs(o.actual - o.p50 * bias) / ((o.p90 - o.p10) / 2) for o in outcomes if o.p90 > o.p10]
    scale = _q(min(SCALE_BOUNDS[1], max(SCALE_BOUNDS[0], _quantile(resid, TARGET_COVERAGE)))) if resid else D(1)
    return CalibrationResult(n, True, coverage, mape, bias, scale, date_mae, f"Calibrated from {n} recorded outcomes.")
