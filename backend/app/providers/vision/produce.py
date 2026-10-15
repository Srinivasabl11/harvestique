"""AI-proposed produce quality ratings from one photo of HARVESTED produce (Ollama, same server as the crop-health
check). It proposes; the farmer reviews and confirms (app.services.grading). Nothing here assigns a final grade.

Safety rules applied to the model's answer before anything is shown:
* not produce, a poor or far-away photo, or (when the crop is known) clearly another crop -> no ratings, retake;
* low confidence -> no ratings at all (a guess is not evidence);
* a rating the model could not tell, or an attribute a photo cannot show (dryness) -> left open for the farmer;
* malformed / missing / unknown fields -> the answer is not used ("invalid_response");
* the free-text description loses any sentence about sprays, chemicals or doses.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx
import numpy as np

from app.domain.crop_profiles import CropContext, crop_matches
from app.domain.produce_grading import attributes
from app.providers.vision.ollama import KEEP_ALIVE, clean_description, failure_kind, jpeg_base64, unusable_photo

logger = logging.getLogger(__name__)
ProposalStatus = Literal["proposed", "needs_more_evidence", "retake_photo", "unavailable"]
RATING = {"best": 0, "middle": 1, "worst": 2}
CONFIDENCES = ("low", "medium", "high")

SYSTEM = (
    "You look at one photo of harvested farm produce (vegetables, fruit, grain, seed or other crop produce) and rate "
    "only what is clearly visible. Do not guess what cannot be seen. Do not name diseases or chemicals and do not "
    "recommend treatments. Reply with JSON only."
)


@dataclass
class ProduceProposal:
    status: ProposalStatus
    reason: str  # why: rated / partial / low_confidence / not_produce / too_dark / blurry / poor_photo / ...
    levels: dict[str, int] = field(default_factory=dict)  # attribute id -> 0 best .. 2 worst, only what was seen
    confidence: str | None = None
    description: str = ""
    produce_seen: str | None = None
    model_name: str = "none"
    model_version: str = "none"


class ProduceGrader(Protocol):
    name: str

    def propose(self, rgb: np.ndarray, profile: str, crop: CropContext | None) -> ProduceProposal: ...


class DisabledProduceGrader:
    """No AI configured (or no key for a hosted one): the farmer grades with the checklist."""

    name = "none"

    def propose(self, rgb: np.ndarray, profile: str, crop: CropContext | None) -> ProduceProposal:
        return ProduceProposal("unavailable", "no_ai")


def schema(profile: str) -> dict[str, Any]:
    visible = [a.id for a in attributes(profile) if a.photo_visible]
    return {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "shows_produce": {"type": "boolean"},
            "close_enough": {"type": "boolean"},
            "photo_quality": {"type": "string", "enum": ["good", "poor"]},
            "produce_seen": {"type": "string"},
            "ratings": {
                "type": "object",
                "properties": {a: {"type": "string", "enum": [*RATING, "cannot_tell"]} for a in visible},
                "required": visible,
            },
            "confidence": {"type": "string", "enum": list(CONFIDENCES)},
        },
        "required": [
            "description",
            "shows_produce",
            "close_enough",
            "photo_quality",
            "produce_seen",
            "ratings",
            "confidence",
        ],
    }


def prompt(profile: str, crop: CropContext | None) -> str:
    lines = []
    for a in attributes(profile):
        if a.photo_visible:
            best, middle, worst = (lv["en"] for lv in a.levels)
            lines.append(f"{a.id} ({a.title['en']}): best = {best}; middle = {middle}; worst = {worst}")
    text = (
        "Fill the fields in order: description (one or two short plain sentences about the produce: size, colour, "
        "any damage, rot, cracks, insects, dirt or wilting), shows_produce (is harvested produce the main subject, "
        "not a plant in the field or something else?), close_enough (can individual pieces or grains be seen?), "
        "photo_quality (good or poor), produce_seen (what produce this is, in one or two words, or 'unknown'), "
        "ratings (for each check: best, middle, worst, or cannot_tell when the photo does not show it clearly), "
        "confidence (low, medium, high). Checks: " + " | ".join(lines)
    )
    return text if crop is None else f"{text} The farmer says this is {crop.name}."


def interpret(raw: dict[str, Any], profile: str, crop: CropContext | None) -> ProduceProposal:
    """Validate the model's answer and turn it into a proposal (raises ValueError when it is malformed)."""
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    for key in ("shows_produce", "close_enough"):
        if not isinstance(raw.get(key), bool):
            raise ValueError(f"{key} missing")
    quality, confidence, ratings = raw.get("photo_quality"), raw.get("confidence"), raw.get("ratings")
    if quality not in ("good", "poor") or confidence not in CONFIDENCES or not isinstance(ratings, dict):
        raise ValueError("bad field")
    description = clean_description(str(raw.get("description") or ""))
    seen = str(raw.get("produce_seen") or "").strip()[:60] or None
    base = {"confidence": confidence, "description": description, "produce_seen": seen}
    if not raw["shows_produce"]:
        return ProduceProposal("retake_photo", "not_produce", **base)
    if quality == "poor":
        return ProduceProposal("retake_photo", "poor_photo", **base)
    if not raw["close_enough"]:
        return ProduceProposal("retake_photo", "not_close_up", **base)
    if crop is not None and crop_matches(seen, crop) is False:
        return ProduceProposal("retake_photo", "crop_mismatch", **base)
    if confidence == "low":
        return ProduceProposal("needs_more_evidence", "low_confidence", **base)
    visible = {a.id for a in attributes(profile) if a.photo_visible}
    levels = {k: RATING[v] for k, v in ratings.items() if k in visible and v in RATING}
    if not levels:
        return ProduceProposal("needs_more_evidence", "nothing_rated", **base)
    complete = len(levels) == len(attributes(profile))
    return ProduceProposal(
        "proposed" if complete else "needs_more_evidence", "rated" if complete else "partial", levels, **base
    )


class OllamaProduceGrader:
    name = "ollama-vision"

    def __init__(self, *, client: httpx.Client, base_url: str, model: str) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._model = model
        self.version = model[:16]

    def propose(self, rgb: np.ndarray, profile: str, crop: CropContext | None) -> ProduceProposal:
        problem = unusable_photo(rgb)
        if problem is not None:  # a black or very blurred photo: no point spending model time
            return self._tag(ProduceProposal("retake_photo", problem))
        try:
            raw = self._ask(rgb, profile, crop)
            return self._tag(interpret(raw, profile, crop))
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            kind = failure_kind(exc)
            logger.warning("produce-grading vision model gave no usable answer: %s (%s)", kind, type(exc).__name__)
            return self._tag(ProduceProposal("unavailable", kind))

    def _tag(self, p: ProduceProposal) -> ProduceProposal:
        p.model_name, p.model_version = self.name, self.version
        return p

    def _ask(self, rgb: np.ndarray, profile: str, crop: CropContext | None) -> dict[str, Any]:
        body = {
            "model": self._model,
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "format": schema(profile),
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt(profile, crop), "images": [jpeg_base64(rgb)]},
            ],
            "options": {"temperature": 0.1, "num_predict": 300},
        }
        resp = self._client.post(f"{self._base}/api/chat", json=body)
        resp.raise_for_status()
        parsed = json.loads(resp.json()["message"]["content"])
        if not isinstance(parsed, dict):
            raise ValueError("not an object")
        return parsed
