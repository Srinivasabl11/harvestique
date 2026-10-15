"""DEMO-ONLY prediction provider. It does NOT predict: it echoes the farmer's own estimate (expected kg/acre x area)
as an exact quantity so the scripted demo (A 500 / B 350 / C 450 / D 300 / E 400 kg, then C 450 -> 200 kg) is
repeatable. Every output is labelled SIMULATED. Refused in production by configuration validation."""

from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal

from app.core.enums import DataKind, PredictionStatus
from app.domain.prediction.engine import RuleBasedPredictor
from app.domain.prediction.models import PredictionInput, PredictionResult, Quantiles, SourceUse


class DemoScriptedPredictor:
    name = "demo-scripted"
    version = "1.0.0"

    def __init__(self) -> None:
        self._real = RuleBasedPredictor()

    def predict(self, inp: PredictionInput) -> PredictionResult:
        base = self._real.predict(inp)  # timing, confidence and risk inputs still come from the real rule model
        est = inp.farmer_estimate
        if est is None:
            return replace(base, model_name=self.name, model_version=self.version, output_kind=DataKind.SIMULATED)
        qty = (est.expected * inp.cycle.area_acres).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        per = est.expected.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        return replace(
            base,
            status=PredictionStatus.OK,
            model_name=self.name,
            model_version=self.version,
            quantity_kg=Quantiles(qty, qty, qty),
            yield_per_acre_kg=Quantiles(per, per, per),
            sources=(SourceUse("demo script (farmer estimate echoed exactly)", DataKind.SIMULATED, True, "demo mode"),),
            warnings=(*base.warnings, "DEMO MODE: scripted quantity, not a prediction."),
            output_kind=DataKind.SIMULATED,
        )
