"""Crop-health image classifier contract. A trained model can replace the colour heuristic by implementing it."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import numpy as np

from app.core.enums import CropHealthClass
from app.domain.crop_profiles import CropContext
from app.domain.vision import TEXT, HealthAssessment, _cap

HEURISTIC_SIDE = 384


@runtime_checkable
class CropHealthClassifier(Protocol):
    name: str
    version: str

    def assess(self, rgb: np.ndarray, language: str, crop: CropContext | None = None) -> HealthAssessment: ...


class ColourHeuristicClassifier:
    """Colour measurements only. On real photos (docs/STAGE3_PROGRESS.md, item 9) the heuristic's health labels were
    wrong far too often (a tractor came out as "stress", healthy tomato leaves as "possible deficiency"), so it no
    longer gives a health label: it reports photo problems and how much green, yellow and brown it measured."""

    name = "colour-heuristic"
    version = "0.2.0"

    def assess(self, rgb: np.ndarray, language: str, crop: CropContext | None = None) -> HealthAssessment:
        from PIL import Image

        from app.domain.vision import assess

        if max(rgb.shape[:2]) > HEURISTIC_SIDE:  # the heuristic's thresholds were tuned at this size
            img = Image.fromarray(rgb)
            img.thumbnail((HEURISTIC_SIDE, HEURISTIC_SIDE))
            rgb = np.asarray(img, dtype=np.uint8)
        r = assess(rgb, language)
        features = {**r.features, "mode": "measurements_only"}
        explanation, advice = measurement_text(features, r.quality_flags, language)
        probs = dict.fromkeys((c.value for c in CropHealthClass), 0.0)
        probs[CropHealthClass.UNKNOWN.value] = 1.0
        return HealthAssessment(CropHealthClass.UNKNOWN, _cap(probs), features, r.quality_flags, explanation, advice)


def measurement_text(features: dict[str, Any], flags: list[str], language: str) -> tuple[str, str]:
    """Plain description of the colour measurements (no health judgement)."""
    if flags:
        _, advice = TEXT.get(language, TEXT["en"])[CropHealthClass.UNKNOWN]
        if language == "kn":
            return "ಈ ಫೋಟೋದಿಂದ ಬಣ್ಣಗಳನ್ನು ಸರಿಯಾಗಿ ಅಳೆಯಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ.", advice
        return "The colours in this photo could not be measured reliably.", advice
    g, y, b = (round(100 * float(features.get(k, 0))) for k in ("green", "yellow", "brown"))
    if language == "kn":
        return (
            f"ಸಸ್ಯದಂತೆ ಕಾಣುವ ಭಾಗಗಳಲ್ಲಿ ಸುಮಾರು {g}% ಹಸಿರು, {y}% ಹಳದಿ ಮತ್ತು {b}% ಕಂದು ಬಣ್ಣ ಕಂಡುಬಂದಿದೆ. "
            "ಬಣ್ಣ ಪರಿಶೀಲನೆಯಿಂದ ಮಾತ್ರ ಸಮಸ್ಯೆಯನ್ನು ಹೇಳಲು ಸಾಧ್ಯವಿಲ್ಲ, ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಸ್ಥಿತಿಯನ್ನು ನೀಡಿಲ್ಲ.",
            "ವೀಕ್ಷಣೆ ದಾಖಲಿಸಿ; ಸಂದೇಹವಿದ್ದರೆ ಕೃಷಿ ಅಧಿಕಾರಿಗೆ ಗಿಡವನ್ನು ತೋರಿಸಿ.",
        )
    return (
        f"In the parts of the photo that look like plant, about {g}% is green, {y}% yellow and {b}% brown. "
        "A colour check alone cannot tell what is wrong, so no health label is given.",
        "Record an observation and, if you are worried, show the plant to an agriculture officer.",
    )
