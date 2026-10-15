"""Crop Health Check: reading the model's real answers, identifying the item in the photo against the real catalogue,
and the 0-100 % health score with its A/B/C category (three equal, non-overlapping bands)."""

from __future__ import annotations

import json
import math

import httpx
import numpy as np
import pytest

from app.cli.seed_crops import seed_payloads
from app.core.enums import CropHealthClass
from app.domain.agri_taxonomy import (
    CATEGORY_TEXT,
    PARENT,
    CatalogueItem,
    health_category,
    identify,
    normalize_score,
    parent_of,
)
from app.domain.crop_health_decision import decide
from app.domain.crop_health_report import build_report, health_percent
from app.domain.vision import HealthAssessment
from app.providers.vision.base import ColourHeuristicClassifier
from app.providers.vision.model_json import parse_model_json
from app.providers.vision.ollama import OllamaVisionClassifier, interpret

# The exact answer Ollama Cloud (gemma4:31b) gave for the project's seedling photo on 2026-10-16: valid JSON in a
# Markdown fence. Before the fix every such answer was rejected as "invalid_response".
CLOUD_ANSWER = """```json
{
  "description": "The leaves are bright green and smooth. There are no spots, holes, or yellowing visible.",
  "shows_plant": true,
  "close_up": true,
  "photo_quality": "good",
  "symptoms": [
    "none"
  ],
  "overall": "healthy",
  "confidence": "high",
  "crop_seen": "unknown",
  "plant_part": "leaves"
}
```"""
_NOISE = np.random.default_rng(4).normal(0, 25, (500, 500, 3))
LEAF = np.clip(np.full((500, 500, 3), (50, 140, 40), dtype=np.float64) + _NOISE, 0, 255).astype(np.uint8)


def catalogue() -> list[CatalogueItem]:
    """The real standard catalogue (the same 213 items as production on 2026-10-16)."""
    return [
        CatalogueItem(p.name, p.local_name, tuple(p.aliases or []), p.crop_group.value if p.crop_group else None)
        for p in seed_payloads()
    ]


# ----------------------------------------------------------------------------------------- reading the answer
@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        '```\n{"a": 1}\n```',
        '  ```JSON\n{"a": 1}```  ',
        'Here is the result:\n{"a": 1}\nHope this helps.',
        '{"a": {"nested": [1, 2]}}',
    ],
)
def test_the_answer_is_read_bare_fenced_or_in_text(text):
    assert parse_model_json(text)["a"] in (1, {"nested": [1, 2]})


@pytest.mark.parametrize(
    "text",
    ["", "no json here", "[1, 2]", '{"a": 1} and {"b": 2}', '```json\n{"a": 1,\n```', "```json\n[1]\n```", None],
)
def test_unusable_answers_are_refused(text):
    with pytest.raises(ValueError):
        parse_model_json(text)


def test_the_real_cloud_answer_is_now_understood():
    raw = parse_model_json(CLOUD_ANSWER)
    result = interpret(raw, "en", None)
    assert result.label is CropHealthClass.HEALTHY and result.features["ai_confidence"] == "high"
    assert result.features["plant_part"] == "leaf"  # "leaves" is read as the leaf part


def _classifier(content: str) -> OllamaVisionClassifier:
    def handler(request):
        return httpx.Response(200, json={"message": {"content": content}})

    return OllamaVisionClassifier(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://ollama.com",
        model="gemma4:31b",
        fallback=ColourHeuristicClassifier(),
    )


def test_a_fenced_cloud_answer_gives_a_real_result_not_unavailable():
    r = _classifier(CLOUD_ANSWER).assess(LEAF, "en")
    assert r.model_name == "ollama-vision" and not r.features.get("ai_unavailable")
    d = build_report(r, "en")["decision"]
    assert d["status"] == "healthy" and d["health_score"] == 100.0 and d["health_category"] == "A"


@pytest.mark.parametrize("content", ["Sorry, I cannot help with that.", '```json\n{"shows_plant": "yes"}\n```'])
def test_a_broken_answer_is_still_reported_as_unavailable_never_faked(content):
    r = _classifier(content).assess(LEAF, "en")
    assert r.features["ai_unavailable"] is True and r.features["ai_error"] == "invalid_response"
    d = build_report(r, "en")["decision"]
    assert (d["status"], d["health_score"], d["health_category"]) == ("unavailable", None, None)
    assert d["category_text"] == "Unable to classify"


# ------------------------------------------------------------------------------------------ A / B / C bands
@pytest.mark.parametrize(
    ("score", "category"),
    [
        (100, "A"),
        (66.67, "A"),
        (66.661, "A"),
        (66.66, "B"),  # 66.66 itself is the top of B: "above 66.66" is A
        (50, "B"),
        (33.34, "B"),
        (33.331, "B"),
        (33.33, "C"),  # 33.33 itself is the top of C
        (10, "C"),
        (0, "C"),
        (-5, "C"),  # clamped to 0
        (150, "A"),  # clamped to 100
    ],
)
def test_every_score_falls_in_exactly_one_band(score, category):
    assert health_category(score) == category


@pytest.mark.parametrize("bad", [None, math.nan, math.inf, -math.inf, "80", True, [80]])
def test_an_unusable_score_gets_no_category(bad):
    assert normalize_score(bad) is None and health_category(bad) is None


def test_bands_cover_the_whole_range_without_gaps_or_overlaps():
    seen = {health_category(x / 100) for x in range(0, 10001)}  # 0.00 ... 100.00 in steps of 0.01
    assert seen == {"A", "B", "C"}
    assert health_category(33.33) == "C" and health_category(33.33 + 1e-9) == "B"
    assert health_category(66.66) == "B" and health_category(66.66 + 1e-9) == "A"


def test_category_texts_in_both_languages():
    assert CATEGORY_TEXT["en"]["A"] == "Very good" and CATEGORY_TEXT["en"]["C"] == "Moderate"
    assert CATEGORY_TEXT["kn"][None] and all(CATEGORY_TEXT["kn"][c] for c in "ABC")


# ------------------------------------------------------------------------------------------- health score
def test_the_health_score_comes_from_visible_signs_not_confidence():
    clean = {"symptoms": [], "ai_confidence": "low"}
    assert health_percent(clean) == 100.0
    one = {"symptoms": ["brown_spots"], "observations": [{"sign": "brown_spots", "extent": "one_or_few"}]}
    many = {"symptoms": ["brown_spots"], "observations": [{"sign": "brown_spots", "extent": "many"}]}
    assert 0 < health_percent(many) < health_percent(one) < 100
    # the same signs with a different confidence give the same score
    assert health_percent({**one, "ai_confidence": "high"}) == health_percent({**one, "ai_confidence": "low"})


def test_little_healthy_tissue_caps_the_score_into_c():
    f = {"symptoms": ["yellowing"], "healthy_tissue": "little"}
    assert health_percent(f) <= 30 and health_category(health_percent(f)) == "C"


def test_severe_damage_is_clamped_at_zero():
    signs = ["rot", "mould", "wilting", "holes", "dark_spots", "dry_edges"]
    f = {"symptoms": signs, "observations": [{"sign": s, "extent": "many"} for s in signs]}
    assert health_percent(f) == 0.0 and health_category(health_percent(f)) == "C"


# ------------------------------------------------------------------------------------ identification (real data)
@pytest.mark.parametrize(
    ("seen", "name", "parent"),
    [
        ("tomato leaf", "Tomato", "vegetables"),
        ("Brinjal", "Brinjal", "vegetables"),
        ("mango", "Mango", "fruits"),
        ("banana plant", "Banana", "fruits"),
        ("finger millet", "Ragi", "cereals_grains"),
        ("ರಾಗಿ", "Ragi", "cereals_grains"),  # Kannada name
        ("paddy", "Paddy", "cereals_grains"),
        ("wheat", "Wheat", "cereals_grains"),
        ("green gram", "Green Gram", "pulses"),
        ("ಹೆಸರು", "Green Gram", "pulses"),
        ("groundnut", "Groundnut", "oilseeds"),
        ("ಶೇಂಗಾ", "Groundnut", "oilseeds"),
        ("turmeric", "Turmeric", "spices"),
        ("black pepper", "Black Pepper", "spices"),
        ("arecanut", "Arecanut", "plantation_commercial"),
        ("coffee", "Coffee", "plantation_commercial"),
        ("marigold flowers", "Marigold", "flowers_ornamental"),
        ("ಮಲ್ಲಿಗೆ", "Jasmine", "flowers_ornamental"),
        ("napier grass", "Napier Grass", "fodder"),
        ("potato", "Potato", "roots_tubers"),
        ("cashew", "Cashew", "plantation_commercial"),
    ],
)
def test_representative_items_are_identified_with_their_parent_category(seen, name, parent):
    found = identify(seen, catalogue())
    assert found is not None, seen
    assert (found.item.name, found.item.parent) == (name, parent)


@pytest.mark.parametrize("seen", [None, "", "unknown", "plant", "a green leaf", "spaceship", "gram"])
def test_no_guess_an_unknown_item_or_an_ambiguous_one_is_not_identified(seen):
    assert identify(seen, catalogue()) is None


def test_every_catalogue_group_has_a_parent_category_with_both_languages():
    groups = {i.group for i in catalogue()}
    for g in groups:
        p = parent_of(g)
        assert p in PARENT and PARENT[p]["en"] and PARENT[p]["kn"], g


def test_every_catalogue_item_identifies_itself_by_its_own_name():
    items = catalogue()
    misses = [i.name for i in items if (f := identify(i.name, items)) is None or f.item.name != i.name]
    assert misses == [], misses


# --------------------------------------------------------------------------------------------- the decision
def _decide(label, features, flags=(), language="en", crop_name=""):
    return decide(label, features, list(flags), language, crop_name=crop_name)


def test_a_healthy_identified_item_gets_name_parent_score_and_category():
    f = {
        "ai_confidence": "high",
        "symptoms": [],
        "identified": {"name": "Ragi", "local_name": "ರಾಗಿ", "group": "millets", "source": "photo"},
    }
    d = _decide(CropHealthClass.HEALTHY, f)
    assert d["item"]["name"] == "Ragi" and d["item"]["parent_name"] == "Cereals and grains"
    assert (d["health_score"], d["health_category"], d["category_text"]) == (100.0, "A", "Very good")
    kn = _decide(CropHealthClass.HEALTHY, f, language="kn")
    assert kn["item"]["display_name"] == "ರಾಗಿ" and kn["item"]["parent_name"] == "ಧಾನ್ಯಗಳು"


def test_visible_problems_lower_the_category_but_confidence_is_reported_separately():
    f = {
        "ai_confidence": "low",
        "symptoms": ["brown_spots", "yellowing"],
        "observations": [{"sign": "brown_spots", "extent": "many"}, {"sign": "yellowing", "extent": "many"}],
        "identified": {"name": "Tomato", "local_name": "ಟೊಮೆಟೊ", "group": "vegetables", "source": "your_crop"},
    }
    d = _decide(CropHealthClass.POSSIBLE_DISEASE, f)
    assert d["status"] == "needs_attention" and d["confidence"] == "low"
    assert d["health_score"] is not None and d["health_category"] in ("B", "C")


@pytest.mark.parametrize(
    ("features", "flags", "reason"),
    [
        ({"identification": "none", "ai_confidence": "high", "symptoms": []}, [], "unidentified"),
        ({"ai_confidence": "high", "symptoms": []}, ["several_items"], "several_items"),
        ({"ai_confidence": "low", "symptoms": []}, [], "low_confidence"),
        ({"precheck": "blurry"}, ["blurry"], "blurry"),
    ],
)
def test_uncertain_photos_are_unable_to_classify_and_ask_for_a_better_photo(features, flags, reason):
    d = _decide(CropHealthClass.HEALTHY, features, flags)
    assert (d["status"], d["reason"]) == ("retake_photo", reason)
    assert (d["health_score"], d["health_category"], d["category_text"]) == (None, None, "Unable to classify")


def test_several_items_in_one_photo_are_flagged_from_the_model_answer():
    raw = parse_model_json(CLOUD_ANSWER) | {"items_in_photo": "several", "crop_seen": "tomato and onion"}
    r = interpret(raw, "en", None)
    assert "several_items" in r.quality_flags and r.features["ai_confidence"] == "low"


def test_old_results_without_identification_still_show_the_chosen_crop():
    d = _decide(CropHealthClass.HEALTHY, {"ai_confidence": "high", "symptoms": [], "expected_crop": "Banana"})
    assert d["item"]["name"] == "Banana" and d["health_category"] == "A"
    assert _decide(CropHealthClass.HEALTHY, {"ai_confidence": "high", "symptoms": []})["item"] is None


def test_the_report_keeps_the_decision_and_score_consistent():
    r = HealthAssessment(
        CropHealthClass.HEALTHY,
        {"healthy": 0.65},
        {
            "ai_confidence": "high",
            "symptoms": [],
            "identified": {"name": "Mango", "group": "fruits", "source": "photo"},
        },
        [],
    )
    rep = build_report(r, "en")
    assert rep["version"] == 3 and rep["decision"]["health_category"] == "A"
    assert rep["condition"]["score"] == 10  # the 0-10 condition score and the 100 % health score agree
    assert json.dumps(rep, ensure_ascii=False)  # serialisable for storage
