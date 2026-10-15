"""Crop-health colour heuristic (pure, numpy only). ADVISORY and NOT VALIDATED on labelled crop images.

It measures how much of the photo is green, yellow or brown plant tissue, whether brown areas look like spots on
green leaves, and photo quality (brightness, sharpness). From those transparent features it gives probabilities over
Healthy / Possible disease / Stress / Possible deficiency / Unknown. The highest probability is capped at 0.70 so the
output never claims certainty, and poor or non-plant photos are reported as Unknown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.enums import CropHealthClass

CLASSES = (
    CropHealthClass.HEALTHY,
    CropHealthClass.POSSIBLE_DISEASE,
    CropHealthClass.STRESS,
    CropHealthClass.POSSIBLE_DEFICIENCY,
    CropHealthClass.UNKNOWN,
)
MAX_PROBABILITY = 0.70
MIN_PLANT_FRACTION = 0.30  # a usable crop photo is at least about a third plant tissue (soil/sky around it is fine)
MAX_GAIN = 4.0  # exposure normalisation for dim photos (a shaded leaf is still a leaf)
MIN_LABEL_PROBABILITY = 0.40
MIN_GREEN_SHARE = 0.10


@dataclass(frozen=True)
class HealthAssessment:
    label: CropHealthClass
    probabilities: dict[str, float]
    features: dict[str, Any]
    quality_flags: list[str] = field(default_factory=list)
    explanation: str = ""
    advice: str = ""
    model_name: str = ""  # set when a classifier delegates (e.g. the vision model fell back to the heuristic)
    model_version: str = ""


def _hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = rgb.astype(np.float64) / 255.0
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    mx, mn = x.max(axis=-1), x.min(axis=-1)
    delta = mx - mn
    h = np.zeros_like(mx)
    nz = delta > 1e-9
    rm = nz & (mx == r)
    gm = nz & (mx == g) & ~rm
    bm = nz & ~rm & ~gm
    h[rm] = ((g[rm] - b[rm]) / delta[rm]) % 6
    h[gm] = (b[gm] - r[gm]) / delta[gm] + 2
    h[bm] = (r[bm] - g[bm]) / delta[bm] + 4
    h = h * 60.0
    s = np.where(mx > 1e-9, delta / np.maximum(mx, 1e-9), 0.0)
    return h, s, mx


def _box_mean(mask: np.ndarray, k: int) -> np.ndarray:
    """Mean of a boolean mask over a k x k window (edge-padded), via 2-D cumulative sums."""
    pad = k // 2
    m = np.pad(mask.astype(np.float64), pad, mode="edge")
    c = np.cumsum(np.cumsum(m, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    h, w = mask.shape
    total = c[k : k + h, k : k + w] - c[:h, k : k + w] - c[k : k + h, :w] + c[:h, :w]
    return np.asarray(total / (k * k))


def _softmax(z: np.ndarray) -> np.ndarray:
    e = np.exp(z - z.max())
    return np.asarray(e / e.sum())


def photo_quality(rgb: np.ndarray) -> tuple[float, float]:
    """(brightness 0..1, sharpness) of an RGB image: mean of the HSV value channel and the variance of a Laplacian
    on grey levels (x1000). Measured at about 384 px; darker images also read as less sharp."""
    _, _, v = _hsv(rgb)
    gray = rgb.astype(np.float64).mean(axis=-1) / 255.0
    lap = gray[1:-1, 1:-1] * 4 - gray[:-2, 1:-1] - gray[2:, 1:-1] - gray[1:-1, :-2] - gray[1:-1, 2:]
    return float(v.mean()), float(lap.var() * 1000)


def assess(rgb: np.ndarray, language: str = "en") -> HealthAssessment:
    if rgb.ndim != 3 or rgb.shape[2] != 3 or min(rgb.shape[:2]) < 16:
        raise ValueError("expected an RGB image of at least 16x16 pixels")
    h, s, v = _hsv(rgb)
    brightness, sharpness = photo_quality(rgb)
    over = float((v > 0.97).mean())
    # judge colours as if the photo were normally exposed: dim phone photos of green leaves otherwise fall below the
    # "lit" threshold and were reported as "little plant visible" (seen with real uploads)
    gain = min(MAX_GAIN, 0.9 / max(float(np.percentile(v, 98)), 1e-3))
    if gain > 1.0:
        v = np.clip(v * gain, 0.0, 1.0)
    lit = (v > 0.12) & (v < 0.97)
    green = lit & (h >= 70) & (h < 170) & (s > 0.20)
    yellow = lit & (h >= 40) & (h < 70) & (s > 0.25)
    brown = lit & (
        ((h >= 10) & (h < 40) & (s > 0.20) & (v < 0.80)) | (((h < 10) | (h >= 340)) & (s > 0.25) & (v < 0.60))
    )
    plant = green | yellow | brown
    pf = float(plant.mean())
    n = max(int(plant.sum()), 1)
    g, y, b = float(green.sum() / n), float(yellow.sum() / n), float(brown.sum() / n)
    k = max(7, (min(rgb.shape[:2]) // 6) | 1)  # window ~3x a typical lesion: a spot's surroundings are visible
    near_green = _box_mean(green, k)
    spot = float(near_green[brown].mean()) if brown.any() else 0.0  # brown surrounded by green = spots on a leaf
    features = {
        "plant_fraction": round(pf, 3),
        "green": round(g, 3),
        "yellow": round(y, 3),
        "brown": round(b, 3),
        "spot_index": round(spot, 3),
        "brightness": round(brightness, 3),
        "exposure_gain": round(max(gain, 1.0), 2),
        "sharpness": round(sharpness, 2),
    }
    flags = []
    if brightness * max(gain, 1.0) < 0.20 or brightness < 0.06:  # still dark after normalising
        flags.append("too_dark")
    if over > 0.40:
        flags.append("too_bright")
    if sharpness < 0.5:
        flags.append("blurry")
    if pf < MIN_PLANT_FRACTION:
        flags.append("little_plant_visible")
    elif g < MIN_GREEN_SHARE:  # colour alone cannot tell dead leaves from bare soil: do not guess
        flags.append("no_green_tissue")
    if flags:
        probs = dict.fromkeys((c.value for c in CLASSES), 0.0)
        probs[CropHealthClass.UNKNOWN.value] = 1.0
        return _finish(CropHealthClass.UNKNOWN, _cap(probs), features, flags, language)
    bn, yn = min(1.0, b / 0.15), min(1.0, y / 0.40)  # brown/yellow relative to a clearly visible amount
    logits = np.array(
        [
            3.0 * g - 7.0 * bn - 4.0 * yn,  # healthy: mostly green, little brown or yellow
            6.0 * bn * spot + 1.0 * bn - 2.0 * yn,  # possible disease: brown spots surrounded by green tissue
            5.0 * bn * (1.0 - spot) + 1.5 * yn * bn - 0.5,  # stress: browning/drying that is not in spots
            5.0 * yn - 3.0 * bn - 0.5,  # possible deficiency: broad, even yellowing
            0.8,  # unknown: always some weight (the heuristic is not validated)
        ]
    )
    p = _softmax(logits * 1.6)
    probs = {c.value: float(x) for c, x in zip(CLASSES, p, strict=True)}
    probs = _cap(probs)
    top = max(probs, key=lambda c: probs[c])
    label = CropHealthClass(top) if probs[top] >= MIN_LABEL_PROBABILITY else CropHealthClass.UNKNOWN
    return _finish(label, probs, features, [], language)


def _cap(probs: dict[str, float]) -> dict[str, float]:
    """Mix with the uniform distribution just enough that no class exceeds MAX_PROBABILITY, then round to whole
    percentages that add up to exactly 100 (shown as bars in the app)."""
    k, top = len(probs), max(probs.values())
    if top > MAX_PROBABILITY:
        lam = (top - MAX_PROBABILITY) / (top - 1.0 / k)
        probs = {c: (1 - lam) * x + lam / k for c, x in probs.items()}
    return {c: p / 100 for c, p in percent_shares(probs).items()}


def percent_shares(values: dict[str, float]) -> dict[str, int]:
    """Whole percentages summing to exactly 100 (largest-remainder rounding). Rounding each value on its own gave
    65 + 21 + 5 + 5 + 5 = 101 % for a "high" vision answer."""
    total = sum(max(v, 0.0) for v in values.values())
    if total <= 0:
        return dict.fromkeys(values, 0)
    exact = {c: 100 * max(v, 0.0) / total for c, v in values.items()}
    out = {c: int(x) for c, x in exact.items()}
    by_remainder = sorted(exact, key=lambda c: (exact[c] - out[c], exact[c]), reverse=True)
    for c in by_remainder[: 100 - sum(out.values())]:
        out[c] += 1
    return out


TEXT = {
    "en": {
        CropHealthClass.HEALTHY: (
            "Leaves look mostly green; no strong sign of yellowing or spots in this photo.",
            "Keep observing the crop regularly.",
        ),
        CropHealthClass.POSSIBLE_DISEASE: (
            "Brown patches appear as spots on green leaves, which can be a sign of disease.",
            "Record an observation, check nearby plants, and confirm with an agriculture officer before spraying.",
        ),
        CropHealthClass.STRESS: (
            "Browning or drying that is not in spots, which can indicate heat or water stress.",
            "Check soil moisture and irrigation; record an observation.",
        ),
        CropHealthClass.POSSIBLE_DEFICIENCY: (
            "Broad, even yellowing, which can indicate a nutrient deficiency.",
            "Consider a soil test and ask an agriculture officer before adding fertilizer.",
        ),
        CropHealthClass.UNKNOWN: (
            "The photo does not give a clear enough signal to say anything useful.",
            "Retake a sharp, well-lit close-up of the affected leaves.",
        ),
    },
    "kn": {
        CropHealthClass.HEALTHY: (
            "ಎಲೆಗಳು ಹೆಚ್ಚಾಗಿ ಹಸಿರಾಗಿವೆ; ಈ ಫೋಟೋದಲ್ಲಿ ಹಳದಿ ಅಥವಾ ಕಲೆಗಳ ಸ್ಪಷ್ಟ ಲಕ್ಷಣ ಇಲ್ಲ.",
            "ಬೆಳೆಯನ್ನು ನಿಯಮಿತವಾಗಿ ಗಮನಿಸುತ್ತಿರಿ.",
        ),
        CropHealthClass.POSSIBLE_DISEASE: (
            "ಹಸಿರು ಎಲೆಗಳ ಮೇಲೆ ಕಂದು ಕಲೆಗಳು ಕಾಣುತ್ತಿವೆ; ಇದು ರೋಗದ ಲಕ್ಷಣ ಆಗಿರಬಹುದು.",
            "ವೀಕ್ಷಣೆ ದಾಖಲಿಸಿ, ಸುತ್ತಲಿನ ಗಿಡಗಳನ್ನು ಪರಿಶೀಲಿಸಿ, ಸಿಂಪಡಣೆಗೆ ಮೊದಲು ಕೃಷಿ ಅಧಿಕಾರಿಯೊಂದಿಗೆ ಖಚಿತಪಡಿಸಿ.",
        ),
        CropHealthClass.STRESS: (
            "ಕಲೆಗಳಲ್ಲದ ಕಂದುಬಣ್ಣ ಅಥವಾ ಒಣಗುವಿಕೆ ಕಾಣುತ್ತಿದೆ; ಇದು ಬಿಸಿಲು ಅಥವಾ ನೀರಿನ ಒತ್ತಡ ಆಗಿರಬಹುದು.",
            "ಮಣ್ಣಿನ ತೇವಾಂಶ ಮತ್ತು ನೀರಾವರಿ ಪರಿಶೀಲಿಸಿ; ವೀಕ್ಷಣೆ ದಾಖಲಿಸಿ.",
        ),
        CropHealthClass.POSSIBLE_DEFICIENCY: (
            "ಎಲೆಗಳು ಸಮವಾಗಿ ಹಳದಿಯಾಗಿವೆ; ಇದು ಪೋಷಕಾಂಶ ಕೊರತೆ ಆಗಿರಬಹುದು.",
            "ಗೊಬ್ಬರ ಹಾಕುವ ಮೊದಲು ಮಣ್ಣು ಪರೀಕ್ಷೆ ಮಾಡಿಸಿ ಮತ್ತು ಕೃಷಿ ಅಧಿಕಾರಿಯನ್ನು ಕೇಳಿ.",
        ),
        CropHealthClass.UNKNOWN: (
            "ಈ ಫೋಟೋದಿಂದ ಸ್ಪಷ್ಟವಾಗಿ ಏನನ್ನೂ ಹೇಳಲು ಸಾಧ್ಯವಿಲ್ಲ.",
            "ಬಾಧಿತ ಎಲೆಗಳ ಸ್ಪಷ್ಟ, ಬೆಳಕಿನಲ್ಲಿ ತೆಗೆದ ಹತ್ತಿರದ ಫೋಟೋ ಮತ್ತೆ ತೆಗೆಯಿರಿ.",
        ),
    },
}


def _finish(
    label: CropHealthClass, probs: dict[str, float], features: dict[str, float], flags: list[str], language: str
) -> HealthAssessment:
    explanation, advice = TEXT.get(language, TEXT["en"])[label]
    return HealthAssessment(label, probs, features, flags, explanation, advice)
