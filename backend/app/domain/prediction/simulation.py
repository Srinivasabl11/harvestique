"""SIMULATED calibration study (synthetic data, seeded). Results describe the method, not real accuracy.

A synthetic 'true' yield process (lognormal-like noise, CV ~0.30, mean 10% below the reference) is predicted by
the rule model using only the reference yield (narrow CV 0.15, i.e. deliberately over-confident). Half of the
outcomes calibrate the model; coverage and error are compared on the other half before and after.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from app.core.enums import CropCategory, CycleStatus, WeatherStatus
from app.domain.prediction.calibration import Outcome, calibrate
from app.domain.prediction.engine import RuleBasedPredictor
from app.domain.prediction.models import CalibrationFacts, CropProfile, CycleFacts, PredictionInput
from app.domain.weather import WeatherContext

D = Decimal


@dataclass(frozen=True, slots=True)
class StudyResult:
    seed: int
    n_train: int
    n_test: int
    coverage_before: Decimal
    coverage_after: Decimal
    mape_before: Decimal
    mape_after: Decimal
    bias_factor: Decimal
    interval_scale: Decimal
    label: str = "SIMULATED"


def run_study(seed: int = 7, n: int = 200) -> StudyResult:
    rng = random.Random(seed)  # noqa: S311 - reproducible synthetic data, not security
    crop = CropProfile("SimCrop", CropCategory.VEGETABLE, 100, D(10000), D("0.15"))
    model = RuleBasedPredictor()
    base_input = PredictionInput(
        crop=crop,
        cycle=CycleFacts(D(1), date(2026, 1, 1), CycleStatus.GROWING),
        today=date(2026, 1, 1) + timedelta(days=90),
        weather=WeatherContext(WeatherStatus.FRESH),
    )
    truth = [D(str(round(9000 * math.exp(rng.gauss(0, 0.30) - 0.045), 3))) for _ in range(n)]

    def evaluate(inp: PredictionInput, actuals: list[Decimal]) -> tuple[Decimal, Decimal, list[Outcome]]:
        pred = model.predict(inp)
        assert pred.quantity_kg is not None
        q = pred.quantity_kg
        outs = [Outcome(q.p10, q.p50, q.p90, a) for a in actuals]
        inside = D(sum(1 for o in outs if o.p10 <= o.actual <= o.p90)) / len(outs)
        mape = sum((abs(o.actual - o.p50) / o.actual * 100 for o in outs), D(0)) / len(outs)
        return inside, mape, outs

    half = n // 2
    _, _, train_outcomes = evaluate(base_input, truth[:half])
    cov_before, mape_before, _ = evaluate(base_input, truth[half:])
    cal = calibrate(train_outcomes)
    calibrated = replace(
        base_input,
        calibration=CalibrationFacts(
            cal.sample_size, cal.sufficient, cal.coverage, cal.bias_factor, cal.interval_scale, None, "simulation"
        ),
    )
    cov_after, mape_after, _ = evaluate(calibrated, truth[half:])
    return StudyResult(
        seed,
        half,
        n - half,
        cov_before.quantize(D("0.001")),
        cov_after.quantize(D("0.001")),
        mape_before.quantize(D("0.01")),
        mape_after.quantize(D("0.01")),
        cal.bias_factor,
        cal.interval_scale,
    )
