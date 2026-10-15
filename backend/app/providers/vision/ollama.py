"""Crop-photo check with a local vision model served by Ollama (free, runs on this machine, no paid API).

The model only DESCRIBES what is visible, choosing from a fixed list of symptoms, and gives an overall category with
its own confidence. It is told not to name diseases, pests or chemicals. Its answer is validated here: unknown values
are dropped, an inconsistent answer is downgraded to low confidence, sentences about spraying or doses are removed, and
probabilities are capped so the result never claims certainty. If the model is not installed, times out or answers
nonsense, the colour heuristic is used instead and the result says so.

General vision models are NOT validated plant-disease classifiers; the output is advisory only.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
from typing import Any

import httpx
import numpy as np
from PIL import Image

from app.core.enums import CropHealthClass
from app.domain.crop_catalog import PARTS
from app.domain.crop_health_report import COLOURS, EXTENT_FACTOR, PART_NAME, PRODUCE_PARTS
from app.domain.crop_profiles import CropContext, crop_matches
from app.domain.vision import MAX_PROBABILITY, MIN_LABEL_PROBABILITY, TEXT, HealthAssessment, _cap, photo_quality
from app.providers.vision.base import CropHealthClassifier

logger = logging.getLogger(__name__)
SYMPTOMS = (
    "yellowing",
    "brown_spots",
    "dark_spots",
    "holes",
    "wilting",
    "dry_edges",
    "curling",
    "white_powder",
    "mould",
    "insects_visible",
    "rot",
    "cracking",
    "sunken_spots",
)
OVERALL = {
    "healthy": CropHealthClass.HEALTHY,
    "possible_disease": CropHealthClass.POSSIBLE_DISEASE,
    "stress": CropHealthClass.STRESS,
    "possible_deficiency": CropHealthClass.POSSIBLE_DEFICIENCY,
    "unclear": CropHealthClass.UNKNOWN,
}
CONFIDENCE = {"high": 0.65, "medium": 0.55, "low": 0.42}
KEEP_ALIVE = "10m"
SIDE = 768  # enough detail for leaf spots; the model rescales internally

# parts the model may report seeing (no "fungus", "latex" or "whole_plant": those are not photo parts)
SEEN_PARTS = tuple(p for p in PARTS if p not in ("fungus", "latex", "whole_plant"))

# Field order matters: the model writes its description BEFORE it judges, which made the judgement more consistent
# with what it saw in testing on real leaf photos.
SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "shows_plant": {"type": "boolean"},
        "close_up": {"type": "boolean"},
        "photo_quality": {"type": "string", "enum": ["good", "poor"]},
        "symptoms": {"type": "array", "items": {"type": "string", "enum": [*SYMPTOMS, "none"]}},
        "overall": {"type": "string", "enum": list(OVERALL)},
        "confidence": {"type": "string", "enum": list(CONFIDENCE)},
        # added AFTER the judgement fields, so the health answer is produced exactly as before
        "crop_seen": {"type": "string"},
        "plant_part": {"type": "string", "enum": [*SEEN_PARTS, "unknown"]},
    },
    "required": [
        "description",
        "shows_plant",
        "close_up",
        "photo_quality",
        "symptoms",
        "overall",
        "confidence",
        "crop_seen",
        "plant_part",
    ],
}
SYSTEM = (
    "You look at one photo sent by a farmer and describe only what is clearly visible on the plant. "
    "Do not name any specific disease, pest, nutrient or chemical, and do not recommend treatments. "
    "If the photo is not a plant, or is too blurry or dark to judge, say so. When unsure, choose 'unclear' "
    "and low confidence. Reply with JSON only."
)
PROMPT = (
    "Fill these fields in order: description (one or two short plain sentences about the leaves: colour, any spots, "
    "markings, holes, yellowing, drying or curling), shows_plant (is a crop plant or leaf the main subject?), "
    "close_up (are individual leaves shown up close, not a whole field?), photo_quality (good or poor), "
    "symptoms (every sign you described, from the allowed list, or ['none']), overall (healthy only if there are no "
    "spots or markings; possible_disease = spots or lesions; stress = wilting or drying; possible_deficiency = even "
    "yellowing; or unclear), confidence (low, medium, high), crop_seen (the crop you think this is, in one or two "
    "words, or 'unknown'), plant_part (the part of the plant that fills most of the photo)."
)
# CANDIDATE prompt v2 (CROP_HEALTH_PROMPT_VERSION=v2; default v1). Written 2026-10-15 from the failure pattern in the
# SEEN PlantDoc/Koppal answers (healthy leaves described as having "small light-coloured spots/markings" or "veins
# appear yellow"), so it must be judged on photos the model has not been shown: docs/CROP_PHOTO_ANALYSIS_2026-10-15.md.
# It names the normal features that are not damage, asks for colour and extent of each sign (used by the condition
# score), and asks for the part BEFORE the judgement.
EXTENTS = tuple(EXTENT_FACTOR)
TISSUE = ("most", "some", "little")
SCHEMA_V2 = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "shows_plant": {"type": "boolean"},
        "close_up": {"type": "boolean"},
        "photo_quality": {"type": "string", "enum": ["good", "poor"]},
        "plant_part": {"type": "string", "enum": [*SEEN_PARTS, "unknown"]},
        "observations": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "sign": {"type": "string", "enum": list(SYMPTOMS)},
                    "colour": {"type": "string", "enum": [*COLOURS, "other"]},
                    "extent": {"type": "string", "enum": list(EXTENTS)},
                },
                "required": ["sign", "colour", "extent"],
            },
        },
        "healthy_tissue": {"type": "string", "enum": list(TISSUE)},
        "overall": {"type": "string", "enum": list(OVERALL)},
        "confidence": {"type": "string", "enum": list(CONFIDENCE)},
        "crop_seen": {"type": "string"},
    },
    "required": [
        "description",
        "shows_plant",
        "close_up",
        "photo_quality",
        "plant_part",
        "observations",
        "healthy_tissue",
        "overall",
        "confidence",
        "crop_seen",
    ],
}
PROMPT_V2 = (
    "Fill these fields in order: description (one or two short plain sentences: the colour of the plant part and any "
    "damage you can clearly see), shows_plant (is a crop plant or plant part the main subject?), close_up (are "
    "individual leaves, fruit or other parts shown up close, not a whole field?), photo_quality (good or poor), "
    "plant_part (the part that fills most of the photo), observations (one entry per kind of damage you described: "
    "the sign, its colour, and whether one_or_few, several or many places show it; an empty list if there is no "
    "damage), healthy_tissue (how much of the visible plant looks normal: most, some or little), overall (healthy = "
    "no damage seen; possible_disease = spots, lesions, mould, powder or rot; stress = wilting, drying or curling; "
    "possible_deficiency = even yellowing; or unclear), confidence (low, medium, high), crop_seen (the crop you think "
    "this is, in one or two words, or 'unknown'). Normal features are NOT damage: veins (even pale or yellowish "
    "veins), shine or light reflections, dust, soil, water drops, leaf hairs and the variety's own colour pattern."
)
PROMPTS = {"v1": (SCHEMA, PROMPT, 240), "v2": (SCHEMA_V2, PROMPT_V2, 360)}  # schema, prompt, max answer tokens
# Signs named in the model's own description (it often leaves the symptom list empty). Negated mentions ("no spots")
# are ignored.
DESCRIPTION_SIGNS = (
    ("brown_spots", re.compile(r"\bbrown\w*[,\s]+(?:\w+[,\s]+){0,2}(?:spots?|patch\w*|lesions?)", re.I)),
    ("dark_spots", re.compile(r"\b(?:dark|black)\w*[,\s]+(?:\w+[,\s]+){0,2}(?:spots?|patch\w*|lesions?)", re.I)),
    ("spots", re.compile(r"\b(?:spots?|spotted|specks?|lesions?|markings?|blotch\w*)\b", re.I)),
    ("yellowing", re.compile(r"\b(?:yellow\w*|chloro\w*|mottl\w*|discolou?r\w*|pale)\b", re.I)),
    ("wilting", re.compile(r"\b(?:wilt\w*|droop\w*)\b", re.I)),
    ("dry_edges", re.compile(r"\b(?:dry\w*|dried|scorch\w*|crisp\w*)\b", re.I)),
    ("browning", re.compile(r"\b(?:brown(?:ing|ed)|turn(?:s|ing|ed)?\s+brown)\b", re.I)),
    ("holes", re.compile(r"\b(?:holes?|chewed|eaten)\b", re.I)),
    ("curling", re.compile(r"\b(?:curl\w*|crumpl\w*|crinkl\w*|deform\w*|distort\w*)\b", re.I)),
    ("white_powder", re.compile(r"\b(?:powder\w*|white\s+coating)\b", re.I)),
    ("mould", re.compile(r"\b(?:mou?ld\w*|fung\w*\s+growth|fuzz\w*)\b", re.I)),
    ("insects_visible", re.compile(r"\b(?:insects?|aphids?|caterpillars?|larva\w*|mites?|bugs?)\b", re.I)),
    ("rot", re.compile(r"\b(?:rot|rots|rotting|rotten|decay\w*|ooz\w*)\b", re.I)),
    ("cracking", re.compile(r"\b(?:crack\w*|split(?:s|ting)?)\b", re.I)),
    ("sunken_spots", re.compile(r"\b(?:sunken|water[- ]soaked)\b", re.I)),
)
NEGATION = re.compile(r"\b(?:no|not|without|free\s+of|absence\s+of|lack\s+of)\b", re.I)
CLAUSE_BREAK = re.compile(r"[.!?;]|\b(?:but|however|although|though|while)\b", re.I)
# advice the app must not pass on from a general model: treatments, chemicals and doses
UNSAFE = re.compile(
    r"\b(spray\w*|fungicid\w*|pesticid\w*|insecticid\w*|herbicid\w*|chemical\w*|dose|dosage|apply\w*|treat\w*|"
    r"\d+\s*(?:ml|g|kg|l|litres?|liters?|%))\b",
    re.IGNORECASE,
)
# Signs -> category, using the same definitions the model is given in PROMPT. Holes and insects are not mapped:
# they point to pests, which none of the categories describe.
DISEASE_SIGNS = frozenset({"spots", "brown_spots", "dark_spots", "mould", "white_powder", "rot", "sunken_spots"})
STRESS_SIGNS = frozenset({"wilting", "dry_edges", "curling", "browning", "cracking"})
# The model's doubts about the photo itself. On real phone photos (2026-10-12) these discarded what it had clearly
# seen ("markings", "yellowing and browning"), so they now lower confidence and add a retake tip instead.
# crop_mismatch: the model named a different crop than the farmer chose; it may be the wrong photo or a wrong
# guess, so it only lowers confidence and asks to check
SOFT_FLAGS = frozenset({"not_close_up", "poor_photo", "crop_mismatch"})
RETAKE_TIP = {
    "en": {
        "not_close_up": "Tip: move closer so one or two affected leaves fill the photo.",
        "poor_photo": "Tip: retake in daylight, hold the phone steady and focus on the affected leaf.",
        "not_a_plant": "The photo does not seem to show a crop plant. Take a photo of the leaves.",
        "too_dark": "Tip: the photo is almost black. Retake it in daylight.",
        "blurry": "Tip: the photo is very blurred. Hold the phone steady, tap the leaf to focus, then take it again.",
        "crop_mismatch": "Note: the AI thinks this may not be {crop}. Check the crop you picked, or retake the photo.",
        "part_not_leaves": "Note: this photo mainly shows the {part}, so only the {part} was judged. For leaf health, "
        "take a close photo of the leaves.",
    },
    "kn": {
        "not_close_up": "ಸಲಹೆ: ಒಂದು ಅಥವಾ ಎರಡು ಬಾಧಿತ ಎಲೆಗಳು ಫೋಟೋವನ್ನು ತುಂಬುವಂತೆ ಹತ್ತಿರದಿಂದ ತೆಗೆಯಿರಿ.",
        "poor_photo": "ಸಲಹೆ: ಹಗಲು ಬೆಳಕಿನಲ್ಲಿ, ಫೋನ್ ಅಲುಗಾಡದಂತೆ ಹಿಡಿದು, ಬಾಧಿತ ಎಲೆಯ ಮೇಲೆ ಫೋಕಸ್ ಮಾಡಿ ಮತ್ತೆ ತೆಗೆಯಿರಿ.",
        "not_a_plant": "ಈ ಫೋಟೋದಲ್ಲಿ ಬೆಳೆ ಗಿಡ ಕಾಣುತ್ತಿಲ್ಲ. ಎಲೆಗಳ ಫೋಟೋ ತೆಗೆಯಿರಿ.",
        "too_dark": "ಸಲಹೆ: ಫೋಟೋ ತುಂಬಾ ಕತ್ತಲಾಗಿದೆ. ಹಗಲು ಬೆಳಕಿನಲ್ಲಿ ಮತ್ತೆ ತೆಗೆಯಿರಿ.",
        "blurry": "ಸಲಹೆ: ಫೋಟೋ ತುಂಬಾ ಮಸುಕಾಗಿದೆ. ಫೋನ್ ಅಲುಗಾಡದಂತೆ ಹಿಡಿದು, ಎಲೆಯ ಮೇಲೆ ಫೋಕಸ್ ಮಾಡಿ ಮತ್ತೆ ತೆಗೆಯಿರಿ.",
        "crop_mismatch": "ಗಮನಿಸಿ: ಇದು {crop} ಅಲ್ಲದಿರಬಹುದು ಎಂದು AI ಭಾವಿಸುತ್ತದೆ. ಆಯ್ಕೆ ಮಾಡಿದ ಬೆಳೆ ಪರಿಶೀಲಿಸಿ ಅಥವಾ ಮತ್ತೆ ಫೋಟೋ ತೆಗೆಯಿರಿ.",
        "part_not_leaves": "ಗಮನಿಸಿ: ಈ ಫೋಟೋದಲ್ಲಿ ಹೆಚ್ಚಾಗಿ {part} ಕಾಣುತ್ತಿದೆ, ಆದ್ದರಿಂದ {part} ಅನ್ನು ಮಾತ್ರ ಪರಿಶೀಲಿಸಲಾಗಿದೆ. ಎಲೆಗಳ "
        "ಆರೋಗ್ಯಕ್ಕಾಗಿ ಎಲೆಗಳ ಹತ್ತಿರದ ಫೋಟೋ ತೆಗೆಯಿರಿ.",
    },
}
AI_NOTE = {"en": "What the AI sees (may be wrong)", "kn": "AI ಕಾಣುವುದು (ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ, ತಪ್ಪಾಗಿರಬಹುದು)"}
FALLBACK_NOTE = {
    "en": "The AI vision model was not available, so only a simple colour check was done (no health label).",
    "kn": "AI ದೃಷ್ಟಿ ಮಾದರಿ ಲಭ್ಯವಿರಲಿಲ್ಲ; ಸರಳ ಬಣ್ಣ ಪರಿಶೀಲನೆ ಮಾತ್ರ ಮಾಡಲಾಗಿದೆ (ಆರೋಗ್ಯ ಸ್ಥಿತಿ ನೀಡಿಲ್ಲ).",
}


def failure_kind(exc: Exception) -> str:
    """Why the model gave no usable answer, stored as `ai_error` and shown to the farmer: timeout (too slow),
    busy (rate limited or overloaded), unavailable (not running, unreachable, model missing, key refused) or
    invalid_response (an answer that failed validation)."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return "busy" if exc.response.status_code in (429, 503) else "unavailable"
    if isinstance(exc, httpx.HTTPError):
        return "unavailable"
    return "invalid_response"


def clean_description(text: str) -> str:
    """Keep the model's plain description but drop any sentence about treatments, chemicals or doses."""
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(str(text).split()))
    kept = [s for s in sentences if s and not UNSAFE.search(s)]
    return " ".join(kept)[:300].strip()


def signs_in(description: str) -> set[str]:
    """Symptom ids mentioned (not negated) in a free-text description."""
    found: set[str] = set()
    for sign, pattern in DESCRIPTION_SIGNS:
        for m in pattern.finditer(description):
            clause = CLAUSE_BREAK.split(description[: m.start()])[-1]  # text before the match, same clause
            if not NEGATION.search(clause):  # "no visible spots, holes or yellowing" negates all three
                found.add(sign)
                break
    return found


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _observations(value: Any) -> list[dict[str, str | None]]:
    """Valid v2 observations (sign, colour, extent); unknown values are dropped, a repeated sign is kept once."""
    out: dict[str, dict[str, str | None]] = {}
    for o in _list(value):
        if isinstance(o, dict) and o.get("sign") in SYMPTOMS and o["sign"] not in out:
            out[o["sign"]] = {
                "sign": o["sign"],
                "colour": o.get("colour") if o.get("colour") in COLOURS else None,
                "extent": o.get("extent") if o.get("extent") in EXTENT_FACTOR else None,
            }
    return list(out.values())


def category_from_signs(symptoms: list[str]) -> CropHealthClass:
    signs = set(symptoms)
    if signs & DISEASE_SIGNS:
        return CropHealthClass.POSSIBLE_DISEASE
    if signs & STRESS_SIGNS:
        return CropHealthClass.STRESS
    if "yellowing" in signs:
        return CropHealthClass.POSSIBLE_DEFICIENCY
    return CropHealthClass.UNKNOWN


def interpret(raw: dict[str, Any], language: str, crop: CropContext | None = None) -> HealthAssessment:
    """Turn the model's JSON into a capped, labelled assessment. Raises ValueError on an unusable answer. With the
    farmer's crop known, a different crop named by the model is flagged (it never replaces the farmer's crop)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("shows_plant"), bool):
        raise ValueError("missing shows_plant")
    description = clean_description(raw.get("description") or "")
    observations = _observations(raw.get("observations"))  # prompt v2 only
    listed = {s for s in _list(raw.get("symptoms")) if s in SYMPTOMS} | {str(o["sign"]) for o in observations}
    merged = listed | signs_in(description)
    if merged & {"brown_spots", "dark_spots"}:
        merged.discard("spots")  # the specific kind of spot is enough
    symptoms = sorted(merged)
    overall = OVERALL.get(str(raw.get("overall")), CropHealthClass.UNKNOWN)
    confidence = str(raw.get("confidence")) if raw.get("confidence") in CONFIDENCE else "low"
    # the model's own verdict before the checks below, kept so later errors can be traced to the model or to us
    raw_verdict = {
        "ai_raw_overall": str(raw.get("overall")) if raw.get("overall") in OVERALL else None,
        "ai_raw_confidence": str(raw.get("confidence")) if raw.get("confidence") in CONFIDENCE else None,
    }
    flags: list[str] = []
    if not raw["shows_plant"]:
        flags.append("not_a_plant")
    elif raw.get("close_up") is False:
        flags.append("not_close_up")
    elif raw.get("photo_quality") == "poor":
        flags.append("poor_photo")
    crop_seen = clean_description(str(raw.get("crop_seen") or ""))[:40] or None
    part = str(raw.get("plant_part")) if raw.get("plant_part") in SEEN_PARTS else "unknown"
    match = crop_matches(crop_seen, crop) if crop is not None else None
    if match is False and "not_a_plant" not in flags:
        flags.append("crop_mismatch")
    # a fruit, tuber, bulb... photo in a check that asks for leaves: say that only that part was judged
    if part in PRODUCE_PARTS and "not_a_plant" not in flags and (crop is None or crop.part != part):
        flags.append("part_not_leaves")
    if symptoms and overall in (CropHealthClass.HEALTHY, CropHealthClass.UNKNOWN):
        # "healthy" or "unclear" while describing spots, yellowing or drying: go by the signs it described, low
        overall, confidence = category_from_signs(symptoms), "low"
    elif overall is not CropHealthClass.UNKNOWN and overall is not CropHealthClass.HEALTHY and not symptoms:
        confidence = "low"  # a problem category with no visible sign named is not trusted beyond "low"
    # colour change alone on fruit, tubers, grain... is usually ripening or the variety's colour: no health claim
    produce_colour_only = (
        part in PRODUCE_PARTS
        and bool(symptoms)
        and set(symptoms) <= {"yellowing", "browning"}
        and overall is not CropHealthClass.HEALTHY
    )
    if produce_colour_only:
        overall = CropHealthClass.UNKNOWN
    soft = bool(set(flags) & SOFT_FLAGS)
    if soft:
        confidence = "low"
    features: dict[str, Any] = {
        "symptoms": symptoms,
        "ai_overall": overall.value,
        "ai_confidence": confidence,
        "ai_description": description,
        "crop_seen": crop_seen,  # the model's guess: unverified
        "plant_part": part,
        **raw_verdict,
    }
    if observations:
        features["observations"] = [o for o in observations if o["sign"] in symptoms]
    if raw.get("healthy_tissue") in TISSUE:
        features["healthy_tissue"] = raw["healthy_tissue"]
    if produce_colour_only:
        features["produce_colour_only"] = True
    if crop is not None:
        features |= {"expected_crop": crop.name, "crop_match": match, "crop_part": crop.part}
    classes = [c.value for c in CropHealthClass]
    # no health claim: not a plant, nothing usable, or a doubtful photo with no visible sign (cannot call it healthy)
    if "not_a_plant" in flags or overall is CropHealthClass.UNKNOWN or (soft and not symptoms):
        probs = dict.fromkeys(classes, 0.0)
        probs[CropHealthClass.UNKNOWN.value] = 1.0
        label = CropHealthClass.UNKNOWN
    else:
        top = CONFIDENCE[confidence]
        rest = 1.0 - top
        probs = dict.fromkeys(classes, rest * 0.4 / (len(classes) - 2))
        probs[CropHealthClass.UNKNOWN.value] = rest * 0.6
        probs[overall.value] = top
        label = overall if top >= MIN_LABEL_PROBABILITY else CropHealthClass.UNKNOWN
    probs = _cap(probs)
    assert max(probs.values()) <= MAX_PROBABILITY + 1e-9
    explanation, advice = TEXT.get(language, TEXT["en"])[label]
    if description:
        explanation = f"{explanation}\n{AI_NOTE.get(language, AI_NOTE['en'])}: {description}"
    crop_label = crop.name if crop is not None else ""
    part_label = PART_NAME.get(language, PART_NAME["en"]).get(part, part)
    tips = [
        RETAKE_TIP.get(language, RETAKE_TIP["en"])[f].format(crop=crop_label, part=part_label)
        for f in flags
        if f in RETAKE_TIP["en"]
    ]
    if tips:
        advice = " ".join([advice, *tips])
    return HealthAssessment(label, probs, features, flags, explanation, advice)


# Measured on real leaf photos (8 public photos, 2026-10-14): originals had sharpness >= 2.18 and brightness >= 0.39;
# heavily blurred copies 0.02-0.16, near-black copies 0.02-0.03. Only photos far below every real one are refused;
# anything in between still goes to the model. The blur check needs light: darkness also lowers the sharpness value.
MIN_BRIGHTNESS = 0.04
MIN_SHARPNESS = 0.15
LIT_ENOUGH_FOR_BLUR_CHECK = 0.15


def _small(rgb: np.ndarray) -> np.ndarray:
    if max(rgb.shape[:2]) <= 384:
        return rgb
    img = Image.fromarray(rgb)
    img.thumbnail((384, 384))
    return np.asarray(img, dtype=np.uint8)


def unusable_photo(rgb: np.ndarray) -> str | None:
    """'too_dark' or 'blurry' for photos that cannot be judged at all, else None."""
    brightness, sharpness = photo_quality(_small(rgb))
    if brightness < MIN_BRIGHTNESS:
        return "too_dark"
    if brightness >= LIT_ENOUGH_FOR_BLUR_CHECK and sharpness < MIN_SHARPNESS:
        return "blurry"
    return None


def generic_spots_low(result: HealthAssessment) -> bool:
    """A problem answer whose only described sign is generic "spots" (not brown/dark spots, nothing else) given with low
    confidence. On PlantDoc (2026-10-14) this pattern was the main source of healthy leaves called "possible disease";
    see docs/CROP_HEALTH_EVAL_2026-10-14.md. Same definition as the evaluation's candidate rule."""
    f = result.features
    return (
        result.label in (CropHealthClass.POSSIBLE_DISEASE, CropHealthClass.STRESS, CropHealthClass.POSSIBLE_DEFICIENCY)
        and list(f.get("symptoms") or []) == ["spots"]
        and f.get("ai_confidence") == "low"
    )


def as_uncertain(result: HealthAssessment, language: str) -> HealthAssessment:
    """The same answer, reported as "unknown" (no health claim); the AI's description is kept."""
    probs = dict.fromkeys((c.value for c in CropHealthClass), 0.0)
    probs[CropHealthClass.UNKNOWN.value] = 1.0
    explanation, advice = TEXT.get(language, TEXT["en"])[CropHealthClass.UNKNOWN]
    description = result.features.get("ai_description")
    if description:
        explanation = f"{explanation}\n{AI_NOTE.get(language, AI_NOTE['en'])}: {description}"
    return HealthAssessment(
        CropHealthClass.UNKNOWN,
        _cap(probs),
        {**result.features, "uncertain_rule": "generic_spots_low"},
        result.quality_flags,
        explanation,
        advice,
        model_name=result.model_name,
        model_version=result.model_version,
    )


SPECIALIST = {
    "en": (
        "{crop} is a cultivated fungus, not a green plant, so this photo check (made for leaves, fruit and roots) "
        "does not apply.",
        "For contamination, odd colours or smells in the beds, ask your Krishi Vigyan Kendra or a mushroom-growing "
        "specialist.",
    ),
    "kn": (
        "{crop} ಬೆಳೆಸಿದ ಶಿಲೀಂಧ್ರ, ಹಸಿರು ಗಿಡವಲ್ಲ; ಆದ್ದರಿಂದ ಈ ಫೋಟೋ ಪರಿಶೀಲನೆ (ಎಲೆ, ಹಣ್ಣು, ಬೇರುಗಳಿಗಾಗಿ) ಅನ್ವಯಿಸುವುದಿಲ್ಲ.",
        "ಹಾಸಿಗೆಯಲ್ಲಿ ಕಲುಷಿತತೆ, ವಿಚಿತ್ರ ಬಣ್ಣ ಅಥವಾ ವಾಸನೆ ಕಂಡರೆ ಕೃಷಿ ವಿಜ್ಞಾನ ಕೇಂದ್ರ ಅಥವಾ ಅಣಬೆ ಬೆಳೆ ತಜ್ಞರನ್ನು ಸಂಪರ್ಕಿಸಿ.",
    ),
}


def specialist_result(crop: CropContext, language: str, model_name: str, model_version: str) -> HealthAssessment:
    probs = dict.fromkeys((c.value for c in CropHealthClass), 0.0)
    probs[CropHealthClass.UNKNOWN.value] = 1.0
    explanation, advice = SPECIALIST.get(language, SPECIALIST["en"])
    return HealthAssessment(
        CropHealthClass.UNKNOWN,
        _cap(probs),
        {"expected_crop": crop.name, "crop_part": crop.part, "assessment": "specialist_needed"},
        ["specialist_needed"],
        explanation.format(crop=crop.name),
        advice,
        model_name=model_name,
        model_version=model_version,
    )


def jpeg_base64(rgb: np.ndarray) -> str:
    img = Image.fromarray(rgb)
    img.thumbnail((SIDE, SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class OllamaVisionClassifier:
    name = "ollama-vision"

    def __init__(
        self,
        *,
        client: httpx.Client,
        base_url: str,
        model: str,
        fallback: CropHealthClassifier,
        generic_spots_uncertain: bool = False,
        prompt_version: str = "v1",
    ) -> None:
        self._generic_spots_uncertain = generic_spots_uncertain  # off unless CROP_HEALTH_GENERIC_SPOTS_UNCERTAIN=true
        if prompt_version not in PROMPTS:
            raise ValueError(f"unknown crop-health prompt version {prompt_version!r}")
        self._prompt_version = prompt_version  # CROP_HEALTH_PROMPT_VERSION
        self._client = client
        self._base = base_url.rstrip("/")
        self._model = model
        self._fallback = fallback
        self.version = model[:16]  # stored with each result (column is 16 characters)
        self._available: bool | None = None
        self._checked_at = 0.0

    def is_available(self) -> bool:
        """Is the vision model listed by the Ollama server? Cached for 30 s (readiness is polled). Listed is not the
        same as answering: a hosted key that is wrong or out of allowance still fails per photo, and falls back."""
        now = time.monotonic()
        if self._available is None or now - self._checked_at >= 30.0:
            try:
                resp = self._client.get(f"{self._base}/api/tags", timeout=2.0)
                names = {m.get("name") for m in resp.json().get("models", [])} if resp.status_code == 200 else set()
                self._available = self._model in names or f"{self._model}:latest" in names
            except (httpx.HTTPError, ValueError, AttributeError):
                self._available = False
            self._checked_at = now
        return self._available

    def assess(self, rgb: np.ndarray, language: str, crop: CropContext | None = None) -> HealthAssessment:
        if crop is not None and crop.specialist_only:  # mushrooms: no green-plant rules, no model call
            return specialist_result(crop, language, self.name, self.version)
        problem = unusable_photo(rgb)
        if problem is not None:  # no point spending a minute of model time on a black or very blurred photo
            return self._retake(problem, rgb, language)
        try:
            raw = self._ask(rgb, crop)
            result = interpret(raw, language, crop)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            kind = failure_kind(exc)
            # the cause, never the photo, the answer text or any credential
            logger.warning("crop-health vision model gave no usable answer: %s (%s)", kind, type(exc).__name__)
            return self._use_fallback(rgb, language, kind)
        if self._generic_spots_uncertain and generic_spots_low(result):
            result = as_uncertain(result, language)
        return HealthAssessment(
            result.label,
            result.probabilities,
            {**result.features, "prompt": self._prompt_version},
            result.quality_flags,
            result.explanation,
            result.advice,
            model_name=self.name,
            model_version=self.version,
        )

    def _retake(self, problem: str, rgb: np.ndarray, language: str) -> HealthAssessment:
        brightness, sharpness = photo_quality(_small(rgb))
        probs = dict.fromkeys((c.value for c in CropHealthClass), 0.0)
        probs[CropHealthClass.UNKNOWN.value] = 1.0
        explanation, advice = TEXT.get(language, TEXT["en"])[CropHealthClass.UNKNOWN]
        tip = RETAKE_TIP.get(language, RETAKE_TIP["en"])[problem]
        return HealthAssessment(
            CropHealthClass.UNKNOWN,
            _cap(probs),
            {"precheck": problem, "brightness": round(brightness, 3), "sharpness": round(sharpness, 2)},
            [problem],
            explanation,
            f"{advice} {tip}",
            model_name=self.name,
            model_version=self.version,
        )

    def _ask(self, rgb: np.ndarray, crop: CropContext | None = None) -> dict[str, Any]:
        schema, base, max_tokens = PROMPTS[self._prompt_version]
        prompt = base if crop is None else f"{base} {crop.prompt_note()}"
        body = {
            "model": self._model,
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "format": schema,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt, "images": [jpeg_base64(rgb)]},
            ],
            "options": {"temperature": 0.1, "num_predict": max_tokens},
        }
        resp = self._client.post(f"{self._base}/api/chat", json=body)
        resp.raise_for_status()
        parsed = json.loads(resp.json()["message"]["content"])
        if not isinstance(parsed, dict):
            raise ValueError("not an object")
        return parsed

    def _use_fallback(self, rgb: np.ndarray, language: str, kind: str = "unavailable") -> HealthAssessment:
        r = self._fallback.assess(rgb, language)  # colour measurements: no crop-specific judgement
        note = FALLBACK_NOTE.get(language, FALLBACK_NOTE["en"])
        return HealthAssessment(
            r.label,
            r.probabilities,
            {**r.features, "ai_unavailable": True, "ai_error": kind},
            r.quality_flags,
            f"{note}\n{r.explanation}",
            r.advice,
            model_name=r.model_name or self._fallback.name,
            model_version=r.model_version or self._fallback.version,
        )
