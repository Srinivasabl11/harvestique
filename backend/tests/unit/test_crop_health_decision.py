"""Farmer-facing crop-health decision: Healthy / Needs attention / Clearer photo needed / Photo check unavailable.

The decision is the only result farmers see. It must never call a doubtful photo healthy, never claim certainty, never
name a product, chemical or dose, and must say plainly when the AI could not run."""

from __future__ import annotations

import json
import re

import httpx
import numpy as np
import pytest

from app.core.enums import CropHealthClass as C
from app.domain.crop_health_decision import STATUSES, TEXT, decide, status_and_reason
from app.domain.crop_health_report import build_report
from app.domain.crop_profiles import context_for
from app.providers.vision.base import ColourHeuristicClassifier
from app.providers.vision.ollama import OllamaVisionClassifier, failure_kind, interpret

_NOISE = np.random.default_rng(2).normal(0, 25, (600, 600, 3))
LEAF = np.clip(np.full((600, 600, 3), (50, 140, 40), dtype=np.float64) + _NOISE, 0, 255).astype(np.uint8)
KANNADA = re.compile("[ಀ-೿]")
OLD_LABELS = re.compile(r"\b(unknown|possible disease|possible deficiency|stress(ed)?)\b", re.I)
# anything that reads like a treatment instruction: products, chemicals or amounts
UNSAFE = re.compile(r"\b(fungicid\w*|pesticid\w*|insecticid\w*|herbicid\w*|\d+\s*(ml|g|kg|l|%))\b", re.I)


def answer(**kw):
    base = {
        "description": "Round brown spots on a green leaf.",
        "shows_plant": True,
        "close_up": True,
        "photo_quality": "good",
        "symptoms": ["brown_spots"],
        "overall": "possible_disease",
        "confidence": "medium",
        "crop_seen": "unknown",
        "plant_part": "leaf",
    }
    return {**base, **kw}


def healthy(**kw):
    return answer(description="Smooth green leaves.", symptoms=["none"], overall="healthy", **kw)


def decision(raw, language="en", crop=None):
    r = interpret(raw, language, crop)
    return build_report(r, language, None, crop.name if crop else None)["decision"]


def classifier(handler):
    return OllamaVisionClassifier(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="http://ollama",
        model="gemma3:4b",
        fallback=ColourHeuristicClassifier(),
    )


def all_text(d):
    return " ".join([d["title"], d["summary"], d["confidence_text"] or "", *d["signs"], *d["next_steps"]])


# ------------------------------------------------------------------------------------ healthy
@pytest.mark.parametrize("confidence", ["medium", "high"])
def test_a_confident_clean_leaf_is_healthy(confidence):
    d = decision(healthy(confidence=confidence))
    assert (d["status"], d["title"], d["confidence"]) == ("healthy", "Healthy", confidence)
    assert "No spots, yellowing" in d["summary"] and d["signs"] == []
    assert "not a measured accuracy" in d["confidence_text"]
    assert d["is_diagnosis"] is False


def test_low_confidence_is_never_enough_for_healthy():
    d = decision(healthy(confidence="low"))
    assert d["status"] == "retake_photo" and d["reason"] == "low_confidence"
    assert d["confidence"] is None and "not sure enough" in d["summary"]


@pytest.mark.parametrize(
    "raw",
    [
        healthy(confidence="high", photo_quality="poor"),
        healthy(confidence="high", close_up=False),
        healthy(confidence="high", shows_plant=False),
        answer(overall="unclear", symptoms=[], description="Hard to say.", confidence="high"),
    ],
)
def test_doubtful_photos_are_never_called_healthy(raw):
    d = decision(raw)
    assert d["status"] == "retake_photo" and d["title"] == "Clearer photo needed"
    assert any("close-up" in s for s in d["next_steps"])


def test_a_photo_of_another_crop_asks_to_check_the_crop():
    tomato = context_for("Tomato", category="vegetable", group="vegetables")
    d = decision(healthy(confidence="high", crop_seen="maize"), crop=tomato)
    assert (d["status"], d["reason"]) == ("retake_photo", "crop_mismatch")
    assert "crop you chose" in d["next_steps"][0]


# ------------------------------------------------------------------------------ needs attention
@pytest.mark.parametrize(
    ("symptoms", "overall", "step"),
    [
        (["brown_spots"], "possible_disease", "Remove badly affected leaves"),
        (["wilting", "dry_edges"], "stress", "soil at root depth"),
        (["yellowing"], "possible_deficiency", "soil test"),
        (["holes"], "possible_disease", "under the leaves"),
    ],
)
def test_visible_signs_need_attention_with_matching_checks(symptoms, overall, step):
    d = decision(answer(symptoms=symptoms, overall=overall, description="Leaf."))
    assert (d["status"], d["title"]) == ("needs_attention", "Needs attention")
    assert d["signs"] and all(s in d["summary"] for s in d["signs"])
    assert any(step in s for s in d["next_steps"])
    assert any("agriculture officer" in s for s in d["next_steps"])  # every problem is referred before any spray


def test_low_confidence_problem_still_needs_attention_but_says_to_look_first():
    d = decision(answer(confidence="low"))
    assert d["status"] == "needs_attention" and d["confidence"] == "low"
    assert "look at the plant yourself" in d["confidence_text"]


def test_a_problem_on_a_poor_photo_keeps_the_signs_it_saw():
    """Retake doubts lowered confidence on real phone photos but did not erase clearly seen signs (2026-10-12)."""
    d = decision(answer(photo_quality="poor", symptoms=["yellowing", "dry_edges"], overall="stress"))
    assert d["status"] == "needs_attention" and d["confidence"] == "low"


def test_signs_show_their_extent_when_the_model_gave_it():
    raw = answer(observations=[{"sign": "brown_spots", "colour": "brown", "extent": "many"}], symptoms=[])
    assert decision(raw)["signs"] == ["Brown spots (many or widespread)"]


# ------------------------------------------------------------------------------- unavailable
@pytest.mark.parametrize(
    ("handler", "kind"),
    [
        (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), "timeout"),
        (lambda r: (_ for _ in ()).throw(httpx.ConnectError("Ollama is not running")), "unavailable"),
        (lambda r: httpx.Response(404, json={"error": "model not found"}), "unavailable"),
        (lambda r: httpx.Response(401, json={"error": "unauthorized"}), "unavailable"),
        (lambda r: httpx.Response(429, json={"error": "rate limited"}), "busy"),
        (lambda r: httpx.Response(200, json={"message": {"content": "{not json"}}), "invalid_response"),
        (lambda r: httpx.Response(200, json={"message": {"content": json.dumps({"a": 1})}}), "invalid_response"),
    ],
)
def test_ai_failures_are_reported_as_unavailable_with_the_cause(handler, kind, caplog):
    r = classifier(handler).assess(LEAF, "en")
    assert r.features["ai_error"] == kind and r.label is C.UNKNOWN
    d = build_report(r, "en")["decision"]
    assert (d["status"], d["reason"], d["title"]) == ("unavailable", kind, "Photo check unavailable")
    assert (d["confidence"] is None and "no health result" in d["summary"]) or "not used" in d["summary"]
    assert any("Try again" in s for s in d["next_steps"])
    assert kind in caplog.text  # the cause is logged for diagnosis


def test_failure_kinds():
    req = httpx.Request("POST", "http://x")
    assert failure_kind(httpx.ConnectTimeout("t")) == "timeout"
    assert failure_kind(httpx.HTTPStatusError("x", request=req, response=httpx.Response(503, request=req))) == "busy"
    assert failure_kind(ValueError("bad")) == "invalid_response"


def test_colour_check_only_gives_no_health_result():
    r = ColourHeuristicClassifier().assess(LEAF, "en")
    d = build_report(r, "en")["decision"]
    assert (d["status"], d["reason"]) == ("unavailable", "no_ai")


def test_mushrooms_are_not_judged_from_photos():
    mushroom = context_for("Mushroom", category="other", group="mushrooms")
    r = classifier(lambda request: pytest.fail("no model call")).assess(LEAF, "en", mushroom)
    d = build_report(r, "en", None, "Mushroom")["decision"]
    assert (d["status"], d["reason"]) == ("unavailable", "specialist") and d["summary"].startswith("Mushroom")


# --------------------------------------------------------------------------------- safety, text
@pytest.mark.parametrize("language", ["en", "kn"])
@pytest.mark.parametrize(
    "raw",
    [
        healthy(confidence="high"),
        answer(symptoms=["brown_spots", "yellowing", "holes", "wilting", "white_powder", "insects_visible"]),
        answer(shows_plant=False),
        healthy(confidence="low"),
    ],
)
def test_texts_never_use_the_old_labels_or_name_products_or_doses(raw, language):
    d = decision(raw, language)
    text = all_text(d)
    assert not UNSAFE.search(text)
    if language == "en":
        assert not OLD_LABELS.search(text.replace("unknown", ""))  # "unknown" never appears as a status
    else:
        assert KANNADA.search(d["title"]) and KANNADA.search(d["summary"])
        assert all(KANNADA.search(s) for s in d["next_steps"])


def test_every_status_has_a_title_in_both_languages_and_the_texts_match():
    assert set(TEXT["en"]) == set(TEXT["kn"])
    for status in STATUSES:
        assert TEXT["en"][f"title_{status}"] and KANNADA.search(TEXT["kn"][f"title_{status}"])


def test_old_stored_results_get_the_same_decision():
    """Rows saved before the decision existed carry only label, features and flags; the rules work from those."""
    assert status_and_reason(C.HEALTHY, {"symptoms": [], "ai_confidence": "high"}, []) == (
        "healthy",
        "no_visible_signs",
    )
    assert status_and_reason(C.POSSIBLE_DISEASE, {"symptoms": ["spots"], "ai_confidence": "low"}, [])[0] == (
        "needs_attention"
    )
    assert status_and_reason(C.UNKNOWN, {"precheck": "blurry"}, ["blurry"]) == ("retake_photo", "blurry")
    assert status_and_reason(C.UNKNOWN, {"mode": "measurements_only"}, []) == ("unavailable", "no_ai")
    d = decide(C.STRESS, {"symptoms": ["wilting"], "ai_confidence": "medium"}, [], "kn")
    assert d["status"] == "needs_attention" and KANNADA.search(d["summary"])
