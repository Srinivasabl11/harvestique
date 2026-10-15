"""Produce quality grading rules (A/B/C) and the validation of AI photo proposals.

A grade needs evidence for every check; the AI's answer is used only when it is well-formed, about produce, from a
usable photo and given with at least medium confidence; nothing a photo cannot show is ever filled in."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pytest

from app.core.enums import QualityGrade as G
from app.core.errors import TooManyRequestsError
from app.core.ratelimit import HourlyLimit
from app.domain import produce_grading as pg
from app.domain.crop_profiles import context_for
from app.providers.vision.produce import DisabledProduceGrader, OllamaProduceGrader, interpret, schema

_NOISE = np.random.default_rng(3).normal(0, 30, (500, 500, 3))
PRODUCE = np.clip(np.full((500, 500, 3), (190, 60, 40), dtype=np.float64) + _NOISE, 0, 255).astype(np.uint8)
KANNADA = re.compile("[ಀ-೿]")
TOMATO = context_for("Tomato", category="vegetable", group="vegetables")


def fresh(**levels):
    return {"size": 0, "maturity": 0, "damage": 0, "freshness": 0, **levels}


# --------------------------------------------------------------------------------------------- rules
def test_all_best_is_a_any_middle_is_b_any_worst_is_c():
    assert pg.grade_for("fresh", fresh()) == (G.A, [])
    assert pg.grade_for("fresh", fresh(maturity=1)) == (G.B, [])
    assert pg.grade_for("fresh", fresh(maturity=1, damage=2)) == (G.C, [])


def test_no_grade_without_every_check():
    grade, missing = pg.grade_for("dry", {"size": 0, "colour": 0, "damage": 0, "foreign_matter": 0})
    assert grade is None and missing == ["dryness"]
    assert pg.grade_for("fresh", {})[0] is None


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        ({"weight": 0}, "unknown check"),
        ({"size": 3}, "0, 1 or 2"),
        ({"size": True}, "0, 1 or 2"),
        ({"size": "0"}, "0, 1"),
    ],
)
def test_bad_ratings_are_refused(raw, error):
    with pytest.raises(ValueError, match=error):
        pg.clean_levels("fresh", raw)


def test_profiles_follow_the_crop_group():
    assert pg.profile_for("vegetables") == "fresh" and pg.profile_for("fruits") == "fresh"
    assert pg.profile_for("cereals") == "dry" and pg.profile_for("pulses") == "dry"
    assert pg.profile_for(None) == "fresh" and pg.profile_for("something_new") == "fresh"


@pytest.mark.parametrize("profile", list(pg.PROFILES))
@pytest.mark.parametrize("language", ["en", "kn"])
def test_criteria_are_complete_in_both_languages(profile, language):
    c = pg.criteria(profile, language)
    assert {g for g in c["grades"]} == {"A", "B", "C"}
    assert all(len(a["levels"]) == 3 and all(lv["text"] for lv in a["levels"]) for a in c["attributes"])
    assert "AGMARK" in c["note"]  # never presented as an official grade
    if language == "kn":
        assert all(KANNADA.search(a["title"]) for a in c["attributes"])


def test_dryness_is_never_asked_from_a_photo():
    dry = {a.id: a for a in pg.attributes("dry")}
    assert dry["dryness"].photo_visible is False
    assert "dryness" not in schema("dry")["properties"]["ratings"]["properties"]


# ---------------------------------------------------------------------------------- AI proposals
def answer(**kw):
    base = {
        "description": "Red, round tomatoes with smooth skin; two have small cracks.",
        "shows_produce": True,
        "close_enough": True,
        "photo_quality": "good",
        "produce_seen": "tomato",
        "ratings": {"size": "best", "maturity": "middle", "damage": "middle", "freshness": "best"},
        "confidence": "medium",
    }
    return {**base, **kw}


def test_a_complete_confident_answer_is_proposed():
    p = interpret(answer(), "fresh", TOMATO)
    assert (p.status, p.reason) == ("proposed", "rated")
    assert p.levels == {"size": 0, "maturity": 1, "damage": 1, "freshness": 0}
    assert pg.grade_for("fresh", p.levels)[0] is G.B


@pytest.mark.parametrize(
    ("kw", "status", "reason"),
    [
        ({"shows_produce": False}, "retake_photo", "not_produce"),
        ({"photo_quality": "poor"}, "retake_photo", "poor_photo"),
        ({"close_enough": False}, "retake_photo", "not_close_up"),
        ({"produce_seen": "onion"}, "retake_photo", "crop_mismatch"),
        ({"confidence": "low"}, "needs_more_evidence", "low_confidence"),
        ({"ratings": {"size": "cannot_tell", "maturity": "cannot_tell"}}, "needs_more_evidence", "nothing_rated"),
    ],
)
def test_doubtful_answers_give_no_ratings(kw, status, reason):
    p = interpret(answer(**kw), "fresh", TOMATO)
    assert (p.status, p.reason, p.levels) == (status, reason, {})


def test_what_the_photo_cannot_show_stays_open():
    p = interpret(answer(ratings={"size": "best", "maturity": "cannot_tell", "damage": "best"}), "fresh", TOMATO)
    assert (p.status, p.reason) == ("needs_more_evidence", "partial")
    assert p.levels == {"size": 0, "damage": 0}


def test_dry_produce_is_never_fully_rated_from_a_photo():
    ratings = {"size": "best", "colour": "best", "damage": "best", "foreign_matter": "best", "dryness": "best"}
    p = interpret(answer(produce_seen="ragi", ratings=ratings), "dry", None)
    assert p.status == "needs_more_evidence" and "dryness" not in p.levels


def test_unknown_or_invalid_ratings_are_ignored():
    p = interpret(answer(ratings={"size": "excellent", "weight": "best", "damage": "best"}), "fresh", None)
    assert p.levels == {"damage": 0}


@pytest.mark.parametrize(
    "raw",
    [
        {**answer(), "confidence": "very high"},
        {**answer(), "ratings": "all good"},
        {k: v for k, v in answer().items() if k != "shows_produce"},
        ["not", "an", "object"],
    ],
)
def test_malformed_answers_raise(raw):
    with pytest.raises(ValueError):
        interpret(raw, "fresh", None)


def test_treatment_sentences_are_dropped_from_the_description():
    p = interpret(answer(description="Firm red tomatoes. Spray 2 ml fungicide per litre."), "fresh", None)
    assert p.description == "Firm red tomatoes."


def _grader(handler):
    return OllamaProduceGrader(
        client=httpx.Client(transport=httpx.MockTransport(handler)), base_url="http://ollama", model="gemma3:4b"
    )


def test_the_grader_sends_the_profile_schema_and_reads_the_answer():
    seen = {}

    def handler(request):
        body = json.loads(request.content)
        seen["format"] = body["format"]
        seen["prompt"] = body["messages"][1]["content"]
        return httpx.Response(200, json={"message": {"content": json.dumps(answer())}})

    p = _grader(handler).propose(PRODUCE, "fresh", TOMATO)
    assert p.status == "proposed" and p.model_name == "ollama-vision" and p.model_version == "gemma3:4b"
    assert set(seen["format"]["properties"]["ratings"]["required"]) == {"size", "maturity", "damage", "freshness"}
    assert "Tomato" in seen["prompt"]


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), "timeout"),
        (lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")), "unavailable"),
        (lambda r: httpx.Response(429, json={}), "busy"),
        (lambda r: httpx.Response(401, json={}), "unavailable"),
        (lambda r: httpx.Response(200, json={"message": {"content": "not json"}}), "invalid_response"),
        (
            lambda r: httpx.Response(200, json={"message": {"content": json.dumps({"confidence": "x"})}}),
            "invalid_response",
        ),
    ],
)
def test_ai_failures_become_unavailable_with_the_cause(handler, reason, caplog):
    p = _grader(handler).propose(PRODUCE, "fresh", None)
    assert (p.status, p.reason, p.levels) == ("unavailable", reason, {})
    assert reason in caplog.text


def test_unusable_photos_skip_the_model():
    def handler(request):
        raise AssertionError("the model must not be called for a black photo")

    p = _grader(handler).propose(np.zeros((300, 300, 3), dtype=np.uint8), "fresh", None)
    assert (p.status, p.reason) == ("retake_photo", "too_dark")


def test_without_ai_the_proposal_is_unavailable():
    assert DisabledProduceGrader().propose(PRODUCE, "fresh", None).reason == "no_ai"


# ------------------------------------------------------------------------------------- rate limit
class _Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 15, 8, tzinfo=UTC)

    def now(self):
        return self.t


def test_the_hourly_limit_counts_per_user_and_slides():
    import uuid

    clock = _Clock()
    limit = HourlyLimit(limit=2, clock=clock, what="AI photo checks")
    a, b = uuid.uuid4(), uuid.uuid4()
    limit.check(a)
    limit.check(a)
    limit.check(b)  # other users are not affected
    with pytest.raises(TooManyRequestsError) as exc:
        limit.check(a)
    assert exc.value.code == "ai_photo_limit" and int(exc.value.headers["Retry-After"]) > 0
    clock.t += timedelta(hours=1, seconds=1)
    limit.check(a)  # the window moved on


def test_a_fenced_cloud_answer_is_read_for_grading_too():
    fenced = "```json\n" + json.dumps(answer()) + "\n```"
    grader = _grader(lambda request: httpx.Response(200, json={"message": {"content": fenced}}))
    p = grader.propose(PRODUCE, "fresh", TOMATO)
    assert p.status == "proposed" and p.levels == {"size": 0, "maturity": 1, "damage": 1, "freshness": 0}
