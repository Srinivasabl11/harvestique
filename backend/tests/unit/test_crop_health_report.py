"""Structured crop-photo report: suitability, identity, observations, explanations, the visual condition score (and
when it is withheld), limitations, Kannada, percentages that add up, prompt v2 parsing and malformed answers."""

from __future__ import annotations

import json
import re

import httpx
import numpy as np
import pytest

from app.core.enums import CropHealthClass as C
from app.domain.crop_health_report import (
    EXPLAIN,
    PART_NAME,
    SIGN_NAME,
    SIGN_WEIGHT,
    T,
    build_report,
    condition_score,
)
from app.domain.crop_profiles import context_for
from app.domain.vision import MAX_PROBABILITY, HealthAssessment, percent_shares
from app.providers.vision.base import ColourHeuristicClassifier
from app.providers.vision.ollama import (
    PROMPT_V2,
    SCHEMA,
    SCHEMA_V2,
    SEEN_PARTS,
    SYMPTOMS,
    OllamaVisionClassifier,
    interpret,
)

_NOISE = np.random.default_rng(1).normal(0, 25, (900, 600, 3))
LEAF = np.clip(np.full((900, 600, 3), (50, 140, 40), dtype=np.float64) + _NOISE, 0, 255).astype(np.uint8)
KANNADA = re.compile("[ಀ-೿]")


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
    return answer(description="Smooth green leaves.", symptoms=["none"], overall="healthy", confidence="high", **kw)


def report(raw, language="en", crop=None, validation=None):
    r = interpret(raw, language, crop)
    return r, build_report(r, language, validation, crop.name if crop else None)


def section(rep, sid):
    return next((s["items"] for s in rep["sections"] if s["id"] == sid), None)


def classifier(handler, version="v1"):
    return OllamaVisionClassifier(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="http://ollama",
        model="gemma3:4b",
        fallback=ColourHeuristicClassifier(),
        prompt_version=version,
    )


def replying(content):
    return lambda request: httpx.Response(200, json={"message": {"content": json.dumps(content)}})


TOMATO = context_for("Tomato", category="vegetable", group="vegetables", scientific="Solanum lycopersicum")


# ------------------------------------------------------------------------------- percentages
@pytest.mark.parametrize("confidence", ["high", "medium", "low"])
def test_category_percentages_add_up_to_exactly_100(confidence):
    """Rounding each share on its own showed 65 + 21 + 5 + 5 + 5 = 101 % for a 'high' answer."""
    r = interpret(answer(confidence=confidence), "en")
    assert sum(round(100 * p) for p in r.probabilities.values()) == 100
    assert max(r.probabilities.values()) <= MAX_PROBABILITY + 1e-9
    assert all(abs(100 * p - round(100 * p)) < 1e-9 for p in r.probabilities.values())  # whole percentages


def test_percent_shares_largest_remainder():
    assert percent_shares({"a": 1, "b": 1, "c": 1}) == {"a": 34, "b": 33, "c": 33}
    assert percent_shares({"a": 0.65, "b": 0.21, "c": 0.0467, "d": 0.0467, "e": 0.0466}) == {
        "a": 65,
        "b": 21,
        "c": 5,
        "d": 5,
        "e": 4,
    }
    assert percent_shares({"a": 0, "b": 0}) == {"a": 0, "b": 0}
    assert sum(percent_shares({"x": 0.42, "y": 0.348, "z": 0.0773, "w": 0.0773, "v": 0.0774}).values()) == 100


# ---------------------------------------------------------------------- condition score rubric
def obs(*signs, extent=None):
    return [{"sign": s, "colour": None, "extent": extent} for s in signs]


@pytest.mark.parametrize(
    ("observations", "tissue", "score"),
    [
        ([], None, 10),
        (obs("spots"), None, 9),  # generic spots: weakest sign
        (obs("brown_spots"), None, 8),
        (obs("brown_spots", "yellowing", extent="several"), None, 5),  # 10 - 3 - 2.25 = 4.75 -> 5
        (obs("rot", "mould", extent="many"), None, 1),  # never below 1
        (obs("spots"), "little", 3),  # little normal tissue caps the score
        (obs("spots"), "some", 6),
        ([], "most", 10),
    ],
)
def test_condition_score_rubric(observations, tissue, score):
    assert condition_score(observations, tissue) == score


def test_every_symptom_the_model_can_report_has_a_weight_a_name_and_kannada():
    for sign in [*SYMPTOMS, "spots", "browning"]:
        assert sign in SIGN_WEIGHT and SIGN_NAME["en"][sign] and KANNADA.search(SIGN_NAME["kn"][sign])
    for part in [*SEEN_PARTS, "unknown"]:
        assert PART_NAME["en"][part] and KANNADA.search(PART_NAME["kn"][part])
    assert set(T["en"]) == set(T["kn"])


# ---------------------------------------------------------------- healthy, problem, deficiency, stress
def test_a_healthy_leaf_gets_a_score_but_no_claim_of_proven_health():
    r, rep = report(healthy())
    assert r.label is C.HEALTHY
    assert rep["condition"]["score"] == 10 and rep["condition"]["band"] == "none_visible"
    assert "not the chance of a disease" in rep["condition"]["method"]
    assert any("does not prove the plant is healthy" in x for x in section(rep, "limitations"))
    assert section(rep, "observations") == [T["en"]["none_seen"]]
    assert "Keep checking" in section(rep, "next")[0]


def test_a_problem_leaf_lists_signs_possible_causes_and_what_to_check():
    r, rep = report(answer(symptoms=["brown_spots", "yellowing"], description="Brown spots and yellowing."))
    assert r.label is C.POSSIBLE_DISEASE
    assert section(rep, "observations") == ["Brown spots", "Yellowing"]
    causes = " ".join(section(rep, "explanations"))
    assert "fungal or bacterial infection" in causes and "nutrient shortage" in causes
    assert rep["condition"]["score"] == 7 and rep["condition"]["band"] == "moderate"  # 10 - 2 - 1.5 = 6.5 -> 7
    assert rep["assessment_confidence"] == "medium"
    assert any("called" in x or "reported problems on healthy leaves" in x for x in section(rep, "limitations"))
    assert any("agriculture officer" in x for x in section(rep, "next"))


@pytest.mark.parametrize(
    ("symptoms", "overall", "label", "cause"),
    [
        (["yellowing"], "possible_deficiency", C.POSSIBLE_DEFICIENCY, "nutrient shortage"),
        (["wilting", "dry_edges"], "stress", C.STRESS, "lack of water"),
        (["holes"], "possible_disease", C.POSSIBLE_DISEASE, "pests feeding"),
    ],
)
def test_deficiency_stress_and_pest_signs(symptoms, overall, label, cause):
    r, rep = report(answer(symptoms=symptoms, overall=overall, description="Leaf."))
    assert r.label is label and cause in " ".join(section(rep, "explanations"))
    assert rep["condition"]["score"] is not None


def test_score_and_confidence_are_separate():
    """The same visible signs give the same condition score whatever the AI's confidence."""
    _, high = report(answer(confidence="high"))
    _, low = report(answer(confidence="low"))
    assert high["condition"]["score"] == low["condition"]["score"] == 8
    assert (high["assessment_confidence"], low["assessment_confidence"]) == ("high", "low")


# ------------------------------------------------------------------- when no score is given
@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (answer(shows_plant=False, description="A tractor."), "not_a_plant"),
        (answer(photo_quality="poor"), "photo"),
        (answer(close_up=False), "photo"),
        (answer(overall="unclear", symptoms=[], description="Hard to say."), "unclear"),
        (answer(crop_seen="maize"), "crop_mismatch"),
    ],
)
def test_no_score_without_enough_evidence(raw, reason):
    crop = TOMATO if reason == "crop_mismatch" else None
    _, rep = report(raw, crop=crop)
    assert rep["condition"]["score"] is None and rep["condition"]["withheld_reason"] == reason
    assert rep["condition"]["text"].startswith("No score")
    _, kn = report(raw, "kn", crop)
    assert KANNADA.search(kn["condition"]["text"]) and all(KANNADA.search(s["title"]) for s in kn["sections"])


def test_an_unrelated_object_says_so_and_guesses_nothing():
    _, rep = report(answer(shows_plant=False, description="A red tractor in a yard.", symptoms=[]))
    assert section(rep, "photo") == [T["en"]["not_a_plant"]]
    assert section(rep, "identity") is None  # no crop or part guess for a non-plant
    assert "sharp close-up" in section(rep, "next")[0]


def test_dark_and_blurred_photos_get_no_score_and_no_model_call():
    from PIL import Image, ImageFilter

    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"message": {"content": json.dumps(answer())}})

    dark = (LEAF.astype(np.float64) * 0.03).astype(np.uint8)
    blurred = np.asarray(Image.fromarray(LEAF).filter(ImageFilter.GaussianBlur(12)), dtype=np.uint8)
    for photo, flag in ((dark, "too_dark"), (blurred, "blurry")):
        r = classifier(handler).assess(photo, "en")
        rep = build_report(r, "en")
        assert rep["condition"]["withheld_reason"] == "photo" and T["en"][flag] in section(rep, "photo")
        assert section(rep, "identity") is None
    assert calls == []


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(500, text="boom"),
        lambda r: httpx.Response(200, json={"message": {"content": "{not json"}}),
        lambda r: httpx.Response(200, json={"message": {"content": json.dumps(["a", "list"])}}),
        lambda r: httpx.Response(200, json={"message": {"content": json.dumps({"description": "no fields"})}}),
        lambda r: httpx.Response(200, json={"unexpected": True}),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("Ollama is not running")),
    ],
)
def test_malformed_answers_and_ollama_failures_never_produce_a_score(handler):
    r = classifier(handler).assess(LEAF, "kn")
    assert r.features["ai_unavailable"] is True and r.label is C.UNKNOWN
    rep = build_report(r, "kn")
    assert rep["condition"]["score"] is None and rep["condition"]["withheld_reason"] == "no_ai"
    assert rep["assessment_confidence"] is None and KANNADA.search(rep["condition"]["text"])


def test_mushroom_specialist_answer_has_no_score():
    mushroom = context_for("Mushroom", category="other", group="mushrooms")
    r = classifier(lambda request: pytest.fail("no model call")).assess(LEAF, "en", mushroom)
    rep = build_report(r, "en", None, "Mushroom")
    assert rep["condition"]["withheld_reason"] == "specialist"


# ---------------------------------------------------------------------- fruit and other parts
def test_a_fruit_photo_in_the_leaf_check_judges_only_the_fruit_and_asks_for_leaves():
    r, rep = report(answer(plant_part="fruit", symptoms=["rot"], description="The fruit has a soft rotten patch."))
    assert "part_not_leaves" in r.quality_flags and r.label is C.POSSIBLE_DISEASE
    assert "only the fruit was judged" in r.advice and "photo of the leaves" in r.advice
    assert any("not the leaves" in x for x in section(rep, "photo"))
    assert rep["condition"]["score"] is not None  # the visible fruit damage is still rated
    assert any("photo of the leaves" in x for x in section(rep, "next"))
    kn, _ = report(answer(plant_part="fruit", symptoms=["rot"], description="Rot."), "kn")
    assert "ಹಣ್ಣು/ಕಾಯಿ" in kn.advice


def test_colour_change_alone_on_fruit_is_not_called_a_problem():
    r, rep = report(
        answer(plant_part="fruit", symptoms=["yellowing"], overall="possible_deficiency", description="Yellow fruit.")
    )
    assert r.label is C.UNKNOWN and r.features["produce_colour_only"] is True
    assert rep["condition"]["withheld_reason"] == "produce_colour"
    assert "ripening" in section(rep, "explanations")[0]


def test_a_tomato_fruit_photo_for_tomato_is_not_flagged_as_the_wrong_part():
    r, _ = report(
        answer(plant_part="fruit", crop_seen="tomato", symptoms=["cracking"], description="Cracked."), crop=TOMATO
    )
    assert "part_not_leaves" not in r.quality_flags and r.features["crop_match"] is True


# --------------------------------------------------------------------------- crop identity
def test_crop_guess_is_labelled_unverified_with_the_measured_rate():
    _, rep = report(answer(crop_seen="tomato"), crop=TOMATO, validation={"verdict": "insufficient_evidence"})
    identity = section(rep, "identity")
    assert identity[0] == "Your crop: Tomato." and "about 1 in 4" in identity[1] and identity[2].startswith("That fits")
    assert any("Tomato has not been validated" in x for x in section(rep, "limitations"))
    _, unknown = report(answer(crop_seen="unknown"))
    assert section(unknown, "identity")[0] == T["en"]["not_seen"]
    _, groundnut = report(healthy(), validation={"verdict": "not_reliable"}, crop=None)
    assert not any("NOT reliable" in x for x in section(groundnut, "limitations"))  # no crop named: no crop line
    rep2 = build_report(interpret(healthy(), "en"), "en", {"verdict": "not_reliable"}, "Groundnut")
    assert any("Groundnut, this check was measured as NOT reliable" in x for x in section(rep2, "limitations"))


# ---------------------------------------------------------------------- safety of the wording
def test_report_texts_name_no_disease_product_or_dose():
    texts = [v for lang in T.values() for v in lang.values()] + [x for _, en, kn in EXPLAIN.values() for x in (en, kn)]
    banned = re.compile(
        r"\d+\s*(?:ml|g|kg|l|litres?|%)\b.*(?:per|/)|fungicid|pesticid|insecticid|herbicid|blight|rust|mildew|"
        r"mosaic|scab|anthracnose|canker|smut|leaf spot",
        re.I,
    )
    assert not [t for t in texts if banned.search(t)]


def test_model_text_is_never_copied_into_the_report_unchecked():
    raw = answer(description="Brown spots. Spray 2 ml/l of fungicide.", crop_seen="tomato")
    _, rep = report(raw)
    flat = json.dumps(rep)
    assert "fungicide" not in flat and "2 ml" not in flat


# --------------------------------------------------------------------- raw verdict and prompt v2
def test_the_models_own_verdict_is_kept_next_to_the_checked_one():
    r = interpret(answer(overall="healthy", confidence="high", symptoms=[], description="Green, with markings."), "en")
    assert (r.features["ai_raw_overall"], r.features["ai_raw_confidence"]) == ("healthy", "high")
    assert (r.features["ai_overall"], r.features["ai_confidence"]) == ("possible_disease", "low")


def test_v1_is_the_default_request_and_v2_asks_for_colour_and_extent():
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(healthy())}})

    r = classifier(handler).assess(LEAF, "en")
    assert sent["format"] == SCHEMA and sent["options"]["num_predict"] == 240 and r.features["prompt"] == "v1"
    v2 = {
        **healthy(),
        "observations": [],
        "healthy_tissue": "most",
    }
    r2 = classifier(lambda req: (sent.update(json.loads(req.content)), replying(v2)(req))[1], "v2").assess(LEAF, "en")
    assert sent["format"] == SCHEMA_V2 and sent["options"]["num_predict"] == 360
    assert sent["messages"][1]["content"] == PROMPT_V2 and "veins" in PROMPT_V2
    assert r2.features["prompt"] == "v2" and r2.features["healthy_tissue"] == "most" and r2.label is C.HEALTHY
    with pytest.raises(ValueError, match="prompt version"):
        classifier(handler, "v9")


def test_v2_observations_feed_the_report_and_bad_entries_are_dropped():
    raw = {
        **answer(symptoms=None, description="Leaf with spots."),
        "observations": [
            {"sign": "brown_spots", "colour": "brown", "extent": "several"},
            {"sign": "brown_spots", "colour": "dark_or_black", "extent": "many"},  # repeated sign: first kept
            {"sign": "yellowing", "colour": "purple", "extent": "lots"},  # unknown colour/extent: dropped values
            {"sign": "lightning", "colour": "brown", "extent": "many"},  # unknown sign: dropped
            "not an object",
        ],
        "healthy_tissue": "some",
    }
    r, rep = report(raw)
    assert r.features["observations"] == [
        {"sign": "brown_spots", "colour": "brown", "extent": "several"},
        {"sign": "yellowing", "colour": None, "extent": None},
    ]
    assert section(rep, "observations") == ["Brown spots, brown, several", "Yellowing"]
    assert rep["condition"]["score"] == 6  # 10 - 2*1.5 - 1.5 = 5.5 -> 6, within the 'some' cap of 6
    for junk in ("text", 7, [1, 2], {"sign": "rot"}):
        assert interpret({**answer(), "observations": junk}, "en").label is C.POSSIBLE_DISEASE


def test_the_registry_passes_the_prompt_version():
    from app.core.config import Settings
    from app.providers.registry import build_crop_health_classifier

    default = build_crop_health_classifier(Settings(_env_file=None, crop_health_classifier="ollama_vision"))  # type: ignore[call-arg]
    v2 = build_crop_health_classifier(
        Settings(_env_file=None, crop_health_classifier="ollama_vision", crop_health_prompt_version="v2")  # type: ignore[call-arg]
    )
    assert default._prompt_version == "v1" and v2._prompt_version == "v2"


def test_the_colour_heuristic_result_gets_a_report_without_a_score():
    r = ColourHeuristicClassifier().assess(LEAF, "en")
    rep = build_report(r, "en")
    assert rep["condition"]["withheld_reason"] == "no_ai" and section(rep, "identity") is None


def test_an_older_stored_result_without_new_fields_still_builds():
    old = HealthAssessment(C.POSSIBLE_DISEASE, {}, {"symptoms": ["spots"], "ai_confidence": "low"})
    rep = build_report(old, "fr")  # unknown language falls back to English
    assert rep["language"] == "en" and rep["condition"]["score"] == 9
