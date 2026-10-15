"""Local vision-model crop check: answer validation, capped probabilities, unsafe-text removal and fallback."""

from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

from app.core.enums import CropHealthClass as C
from app.domain.vision import MAX_PROBABILITY, assess
from app.providers.vision.base import ColourHeuristicClassifier
from app.providers.vision.ollama import OllamaVisionClassifier, clean_description, interpret

_NOISE = np.random.default_rng(1).normal(0, 25, (900, 600, 3))
LEAF = np.clip(np.full((900, 600, 3), (50, 140, 40), dtype=np.float64) + _NOISE, 0, 255).astype(np.uint8)


def answer(**kw):
    base = {
        "shows_plant": True,
        "close_up": True,
        "photo_quality": "good",
        "symptoms": ["brown_spots"],
        "overall": "possible_disease",
        "confidence": "high",
        "description": "Round brown spots on a green leaf.",
    }
    return {**base, **kw}


def test_a_clear_answer_becomes_a_capped_label_with_the_description():
    r = interpret(answer(), "en")
    assert r.label is C.POSSIBLE_DISEASE
    assert max(r.probabilities.values()) <= MAX_PROBABILITY + 1e-9
    assert abs(sum(r.probabilities.values()) - 1) < 0.01
    assert r.features["symptoms"] == ["brown_spots"]
    assert "What the AI sees (may be wrong): Round brown spots" in r.explanation


def test_not_a_plant_is_always_unknown():
    r = interpret(answer(shows_plant=False), "en")
    assert r.label is C.UNKNOWN and r.quality_flags == ["not_a_plant"]
    assert "does not seem to show a crop plant" in r.advice


@pytest.mark.parametrize(
    ("kw", "flag", "tip"),
    [
        ({"close_up": False}, "not_close_up", "move closer"),
        ({"photo_quality": "poor"}, "poor_photo", "daylight"),
    ],
)
def test_a_doubtful_photo_keeps_visible_signs_at_low_confidence_with_a_retake_tip(kw, flag, tip):
    r = interpret(answer(**kw), "en")
    assert r.label is C.POSSIBLE_DISEASE and r.features["ai_confidence"] == "low"
    assert r.quality_flags == [flag] and tip in r.advice
    assert max(r.probabilities.values()) <= 0.45


@pytest.mark.parametrize("kw", [{"close_up": False}, {"photo_quality": "poor"}])
def test_a_doubtful_photo_with_no_visible_sign_is_never_called_healthy(kw):
    r = interpret(answer(overall="healthy", symptoms=[], description="Green leaves.", **kw), "en")
    assert r.label is C.UNKNOWN


@pytest.mark.parametrize(
    ("raw", "label", "flag"),
    [
        # the two real phone photos of 2026-10-12, which both used to come back "unknown" with generic advice
        (
            {
                "overall": "unclear",
                "close_up": False,
                "symptoms": [],
                "description": "The leaves are green in color. There are some markings visible on the leaves.",
            },
            C.POSSIBLE_DISEASE,
            "not_close_up",
        ),
        (
            {
                "overall": "possible_disease",
                "photo_quality": "poor",
                "symptoms": [],
                "description": "Several leaves are green, with one leaf showing yellowing and browning.",
            },
            C.POSSIBLE_DISEASE,
            "poor_photo",
        ),
    ],
)
def test_real_phone_photos_now_report_what_was_seen(raw, label, flag):
    r = interpret(answer(**raw), "en")
    assert r.label is label and r.features["ai_confidence"] == "low"
    assert r.quality_flags == [flag] and "Tip:" in r.advice


def test_unclear_is_unknown():
    assert interpret(answer(overall="unclear", symptoms=[], description="A leaf."), "en").label is C.UNKNOWN


def test_healthy_while_describing_markings_goes_by_the_signs_at_low_confidence():
    # seen with a real Septoria-spotted tomato leaf: "healthy, high" with "small, light-colored markings"
    r = interpret(
        answer(
            overall="healthy",
            symptoms=[],
            description="Green leaves with some small, light-colored markings on several of the leaves.",
        ),
        "en",
    )
    assert r.label is C.POSSIBLE_DISEASE and r.features["symptoms"] == ["spots"]
    assert r.features["ai_confidence"] == "low"
    # holes point to pests, which no category describes: no health claim
    r = interpret(answer(overall="healthy", symptoms=["holes"], description="Green leaves."), "en")
    assert r.label is C.UNKNOWN


@pytest.mark.parametrize(
    ("signs", "label"),
    [
        (["yellowing"], C.POSSIBLE_DEFICIENCY),
        (["wilting"], C.STRESS),
        (["browning", "yellowing"], C.STRESS),
        (["spots", "yellowing"], C.POSSIBLE_DISEASE),
        (["insects_visible"], C.UNKNOWN),
    ],
)
def test_category_from_signs(signs, label):
    from app.providers.vision.ollama import category_from_signs

    assert category_from_signs(signs) is label


def test_a_problem_with_no_visible_sign_is_low_confidence():
    r = interpret(answer(symptoms=["none"], description="A green leaf."), "en")
    assert r.label is C.POSSIBLE_DISEASE and r.features["ai_confidence"] == "low"


@pytest.mark.parametrize(
    ("text", "signs"),
    [
        ("The image shows a green leaf with several dark, circular spots.", {"dark_spots", "spots"}),
        ("The leaf shows areas of yellowing and mottling.", {"yellowing"}),
        ("The leaf has a somewhat crumpled appearance.", {"curling"}),
        ("Healthy green leaves with no spots and without yellowing.", set()),
        ("The leaves are a vibrant green color with smooth edges. There are no visible spots or markings.", set()),
        ("Brown patches near the edges, which look dry.", {"brown_spots", "dry_edges"}),
        ("One leaf showing yellowing and browning.", {"yellowing", "browning"}),
        ("Green leaves. There are no visible spots, markings, holes, yellowing, drying, or curling.", set()),
        ("No wilting, but there are dark spots on two leaves.", {"dark_spots", "spots"}),
    ],
)
def test_signs_are_read_from_the_description(text, signs):
    from app.providers.vision.ollama import signs_in

    assert signs_in(text) == signs


def test_unknown_values_are_dropped():
    r = interpret(answer(symptoms=["late_blight", "brown_spots"], confidence="certain", description="Spots."), "en")
    assert r.features["symptoms"] == ["brown_spots"]
    assert r.features["ai_confidence"] == "low"


def test_garbage_is_rejected():
    with pytest.raises(ValueError):
        interpret({"overall": "healthy"}, "en")


def test_treatment_and_dose_sentences_are_removed():
    text = "Brown spots on leaves. Spray mancozeb at 2 g per litre. Apply fungicide weekly. Edges look dry."
    assert clean_description(text) == "Brown spots on leaves. Edges look dry."


def test_kannada_keeps_kannada_text_and_labels_the_english_ai_note():
    r = interpret(answer(), "kn")
    assert any("ಀ" <= ch <= "೿" for ch in r.explanation)
    assert "AI" in r.explanation


def _classifier(handler):
    return OllamaVisionClassifier(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="http://ollama",
        model="gemma3:4b",
        fallback=ColourHeuristicClassifier(),
    )


def test_the_model_is_asked_with_an_image_and_a_schema():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(answer(overall="healthy", symptoms=[], description="Smooth green leaves."))
                }
            },
        )

    r = _classifier(handler).assess(LEAF, "en")
    assert r.label is C.HEALTHY
    assert r.model_name == "ollama-vision" and r.model_version == "gemma3:4b"
    msg = seen["messages"][1]
    assert len(msg["images"]) == 1 and seen["format"]["required"]
    assert "Do not name any specific disease" in seen["messages"][0]["content"]


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(404, json={"error": "model not found"}),
        lambda r: httpx.Response(200, json={"message": {"content": "not json"}}),
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
    ],
)
def test_falls_back_to_the_colour_check_and_says_so(handler):
    r = _classifier(handler).assess(LEAF, "en")
    assert r.model_name == "colour-heuristic"
    assert r.features["ai_unavailable"] is True
    assert r.explanation.startswith("The local AI vision model was not available")


def test_dim_leaf_photo_is_not_rejected_any_more():
    dim = (LEAF.astype(np.float64) * 0.22).astype(np.uint8)  # a shaded, under-exposed leaf
    r = assess(dim[:384, :384])
    assert "little_plant_visible" not in r.quality_flags
    assert "too_dark" not in r.quality_flags
    assert r.label is C.HEALTHY  # the domain heuristic still runs; the classifier only reports its measurements


def test_the_colour_check_reports_measurements_but_no_health_label():
    r = ColourHeuristicClassifier().assess(LEAF, "en")
    assert r.label is C.UNKNOWN and r.features["mode"] == "measurements_only"
    assert "no health label" in r.explanation and "% is green" in r.explanation
    kn = ColourHeuristicClassifier().assess(LEAF, "kn")
    assert any("ಀ" <= ch <= "೿" for ch in kn.explanation)


def test_the_registry_builds_the_configured_classifier():
    from app.core.config import Settings
    from app.providers.registry import build_crop_health_classifier

    vision = build_crop_health_classifier(Settings(_env_file=None, crop_health_classifier="ollama_vision"))  # type: ignore[call-arg]
    assert isinstance(vision, OllamaVisionClassifier) and vision.version == "gemma3:4b"
    plain = build_crop_health_classifier(Settings(_env_file=None))  # type: ignore[call-arg]
    assert isinstance(plain, ColourHeuristicClassifier)


# ---------------------------------------------------------------- fast photo-quality pre-check
def _counting_classifier():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"message": {"content": json.dumps(answer())}})

    return _classifier(handler), calls


def _blurred(rgb, radius):
    from PIL import Image, ImageFilter

    return np.asarray(Image.fromarray(rgb).filter(ImageFilter.GaussianBlur(radius)), dtype=np.uint8)


def test_a_black_photo_is_answered_at_once_without_the_model():
    clf, calls = _counting_classifier()
    r = clf.assess((LEAF.astype(np.float64) * 0.03).astype(np.uint8), "en")
    assert calls == [] and r.label is C.UNKNOWN and r.quality_flags == ["too_dark"]
    assert "daylight" in r.advice and r.model_name == "ollama-vision"


def test_a_very_blurred_photo_is_answered_at_once_without_the_model():
    clf, calls = _counting_classifier()
    r = clf.assess(_blurred(LEAF, 12), "en")
    assert calls == [] and r.quality_flags == ["blurry"] and "focus" in r.advice
    assert max(r.probabilities.values()) <= MAX_PROBABILITY + 1e-9


def test_normal_and_dim_but_usable_photos_still_go_to_the_model():
    from app.providers.vision.ollama import unusable_photo

    assert unusable_photo(LEAF) is None
    dim = (LEAF.astype(np.float64) * 0.15).astype(np.uint8)  # dark: low sharpness reading, must not count as blur
    assert unusable_photo(dim) is None
    clf, calls = _counting_classifier()
    clf.assess(LEAF, "en")
    assert calls == [1]


def test_kannada_retake_tip():
    clf, _ = _counting_classifier()
    r = clf.assess(_blurred(LEAF, 12), "kn")
    assert any("ಀ" <= ch <= "೿" for ch in r.advice)


# ---------------------------------------------------------------- optional "generic spots, low confidence" rule
def test_generic_spots_rule_is_off_by_default_and_changes_only_that_pattern_when_on():
    weak = {
        "description": "Green leaves with some small markings.",
        "symptoms": [],
        "overall": "possible_disease",
        "confidence": "low",
    }

    def classifier(on, content):
        def handler(request):
            return httpx.Response(200, json={"message": {"content": json.dumps(answer(**content))}})

        return OllamaVisionClassifier(
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            base_url="http://ollama",
            model="gemma3:4b",
            fallback=ColourHeuristicClassifier(),
            generic_spots_uncertain=on,
        )

    assert classifier(False, weak).assess(LEAF, "en").label is C.POSSIBLE_DISEASE  # default: unchanged
    on = classifier(True, weak).assess(LEAF, "en")
    assert on.label is C.UNKNOWN and on.features["uncertain_rule"] == "generic_spots_low"
    assert "may be wrong" in on.explanation and max(on.probabilities.values()) <= MAX_PROBABILITY + 1e-9
    strong = {"description": "Round brown spots on a green leaf.", "symptoms": ["brown_spots"], "confidence": "low"}
    assert classifier(True, strong).assess(LEAF, "en").label is C.POSSIBLE_DISEASE  # specific sign: kept


def test_production_rule_matches_the_evaluated_candidate_rule():
    from app.cli.eval_crop_health import candidate_label
    from app.domain.vision import HealthAssessment as HA
    from app.providers.vision.ollama import generic_spots_low

    cases = [
        ("possible_disease", ["spots"], "low"),
        ("possible_disease", ["spots"], "medium"),
        ("possible_deficiency", ["spots"], "low"),
        ("possible_disease", ["spots", "yellowing"], "low"),
        ("healthy", [], "high"),
        ("possible_disease", ["dark_spots"], "low"),
    ]
    for label, symptoms, conf in cases:
        row = {"label": label, "features": {"symptoms": symptoms, "ai_confidence": conf}}
        result = HA(C(label), {}, {"symptoms": symptoms, "ai_confidence": conf})
        assert (candidate_label(row) == "unknown") == generic_spots_low(result), (label, symptoms, conf)


def test_the_registry_passes_the_setting():
    from app.core.config import Settings
    from app.providers.registry import build_crop_health_classifier

    off = build_crop_health_classifier(Settings(_env_file=None, crop_health_classifier="ollama_vision"))  # type: ignore[call-arg]
    on = build_crop_health_classifier(
        Settings(_env_file=None, crop_health_classifier="ollama_vision", crop_health_generic_spots_uncertain=True)  # type: ignore[call-arg]
    )
    assert off._generic_spots_uncertain is False and on._generic_spots_uncertain is True


# ------------------------------------------------------------------ crop- and part-aware check (section 12)
def _crop(name="Ragi", category="cereal", group="millets", aliases=("finger millet",), scientific="Eleusine coracana"):
    from app.domain.crop_profiles import context_for

    return context_for(name, category=category, group=group, aliases=list(aliases), scientific=scientific)


def _answer(**over):
    base = {
        "description": "The leaves are green with no spots.",
        "shows_plant": True,
        "close_up": True,
        "photo_quality": "good",
        "symptoms": ["none"],
        "overall": "healthy",
        "confidence": "medium",
        "crop_seen": "finger millet",
        "plant_part": "leaf",
    }
    return {**base, **over}


def test_the_expected_crop_and_its_part_guidance_go_to_the_model():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(_answer())}})

    potato = _crop("Potato", "vegetable", None, (), "Solanum tuberosum")
    r = _classifier(handler).assess(LEAF, "en", potato)
    prompt = seen["messages"][1]["content"]
    assert "The farmer says this is Potato (Solanum tuberosum), grown for its tuber" in prompt
    assert "Soil on the surface" in prompt and "crop_seen" in seen["format"]["properties"]
    assert r.features["expected_crop"] == "Potato" and r.features["plant_part"] == "leaf"
    _classifier(handler).assess(LEAF, "en")  # no crop known: the plain prompt, unchanged
    assert "The farmer says" not in seen["messages"][1]["content"]


def test_a_different_crop_named_by_the_model_lowers_confidence_and_asks_to_check():
    r = interpret(
        _answer(
            crop_seen="tomato",
            overall="possible_disease",
            symptoms=["brown_spots"],
            description="Brown spots on the leaves.",
            confidence="high",
        ),
        "en",
        _crop(),
    )
    assert "crop_mismatch" in r.quality_flags and r.features["crop_match"] is False
    assert r.features["ai_confidence"] == "low" and "may not be Ragi" in r.advice
    kn = interpret(_answer(crop_seen="tomato"), "kn", _crop())
    assert "Ragi ಅಲ್ಲದಿರಬಹುದು" in kn.advice
    same = interpret(_answer(crop_seen="ragi plant"), "en", _crop("Ragi", aliases=("finger millet",)))
    assert same.features["crop_match"] is True and "crop_mismatch" not in same.quality_flags
    no_guess = interpret(_answer(crop_seen="unknown"), "en", _crop())
    assert no_guess.features["crop_match"] is None and "crop_mismatch" not in no_guess.quality_flags


def test_fruit_tuber_and_bulb_signs_are_read():
    r = interpret(
        _answer(
            description="The tuber has a soft rotten patch and a deep crack.",
            plant_part="tuber",
            overall="unclear",
            symptoms=["none"],
        ),
        "en",
        _crop("Potato", "vegetable", None, (), None),
    )
    assert {"rot", "cracking"} <= set(r.features["symptoms"]) and r.label is C.POSSIBLE_DISEASE
    assert r.features["plant_part"] == "tuber"
    assert interpret(_answer(plant_part="banana peel"), "en").features["plant_part"] == "unknown"  # not a known part


def test_mushrooms_get_a_specialist_answer_without_a_model_call():
    def handler(request):
        raise AssertionError("the model must not be asked about a mushroom")

    r = _classifier(handler).assess(LEAF, "kn", _crop("Mushroom", "other", "mushrooms", (), None))
    assert r.label is C.UNKNOWN and "specialist_needed" in r.quality_flags and r.features["crop_part"] == "fungus"
    assert any("ಀ" <= ch <= "೿" for ch in r.explanation)
