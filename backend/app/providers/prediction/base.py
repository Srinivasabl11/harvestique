"""PredictionProvider: the seam for swapping the rule model for a trained ML model later.

Any implementation receives the same pure PredictionInput and returns a PredictionResult (with p10/p50/p90,
timing, confidence and provenance). It must not access the database; the service gathers inputs for it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.prediction.models import PredictionInput, PredictionResult


@runtime_checkable
class PredictionProvider(Protocol):
    name: str
    version: str

    def predict(self, inp: PredictionInput) -> PredictionResult: ...
