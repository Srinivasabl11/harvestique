"""Regression tests for the two reported examples, through the real request paths (/assistant/chat and the voice path
/voice/intent), in Kannada and English, with authenticated farm records:

A. "ನಾನು ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಮಾವು ಬೆಳೆಯುತ್ತಿದ್ದೇನೆ." / "I am growing mango on my farm." (a statement, used as context)
B. "What crops are best to grow on my farm?" (a crop recommendation, not just a farm-record summary)
"""

from __future__ import annotations

import pytest

from app.providers.llm.fake import DisabledLLMProvider

pytestmark = pytest.mark.integration
API = "/api/v1"
MANGO_KN = "ನಾನು ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಮಾವು ಬೆಳೆಯುತ್ತಿದ್ದೇನೆ."
MANGO_EN = "I am growing mango on my farm."
BEST_EN = "What crops are best to grow on my farm?"
BEST_KN = "ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಯಾವ ಬೆಳೆ ಬೆಳೆಯುವುದು ಉತ್ತಮ"
APOLOGY_KN = "ಕ್ಷಮಿಸಿ, ನನಗೆ ಅರ್ಥವಾಗಲಿಲ್ಲ"


class NoModel:
    """These workflows are deterministic: any language-model call fails the test."""

    name = model = "none"

    def is_available(self) -> bool:
        return True

    def generate(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError(f"the model was asked: {request.messages[-1].content}")


@pytest.fixture(autouse=True)
def no_llm(db_container):
    db_container.llm = NoModel()


@pytest.fixture
def mango(api, admin):
    return api.crop(
        admin,
        name="Mango",
        local_name="ಮಾವು",
        category="fruit",
        typical_duration_days=365,
        season="year_round",
        aliases=["aam"],
        scientific_name="Mangifera indica",
        crop_group="fruits",
        water_need_mm=900,
    )


@pytest.fixture
def catalogue(api, admin, mango):
    """A few crops with seasons and water needs, as in the real catalogue."""
    api.crop(
        admin,
        name="Bengal Gram",
        local_name="ಕಡಲೆ",
        category="pulse",
        typical_duration_days=100,
        season="rabi",
        water_need_mm=300,
        crop_group="pulses",
    )
    api.crop(
        admin,
        name="Ragi",
        local_name="ರಾಗಿ",
        category="cereal",
        typical_duration_days=120,
        season="kharif",
        water_need_mm=350,
        crop_group="millets",
    )
    api.crop(
        admin,
        name="Tomato",
        local_name="ಟೊಮೆಟೊ",
        category="vegetable",
        typical_duration_days=120,
        season="year_round",
        water_need_mm=500,
        crop_group="vegetables",
    )
    api.crop(
        admin,
        name="Sugarcane",
        local_name="ಕಬ್ಬು",
        category="cash_crop",
        typical_duration_days=365,
        season="year_round",
        water_need_mm=1800,
        crop_group="sugar_starch",
    )


@pytest.fixture
def farm(api, farmer):
    return api.farm(
        farmer,
        name="Mysuru Farm",
        district="Mysuru",
        state="Karnataka",
        latitude=12.3,
        longitude=76.6,
        total_area_acres=10,
    )


class Chat:
    def __init__(self, client, actor, lang, path="/assistant/chat"):
        self.client, self.actor, self.lang, self.path, self.history = client, actor, lang, path, []

    def say(self, text):
        key = "transcript" if self.path.startswith("/voice") else "message"
        r = self.client.post(
            f"{API}{self.path}",
            headers=self.actor.headers,
            json={key: text, "language": self.lang, "history": self.history[-8:]},
        )
        assert r.status_code == 200, r.text
        out = r.json()
        self.history += [
            {"role": "user", "text": text},
            {"role": "assistant", "text": out["answer"][:1200], "intent": out["intent"]},
        ]
        return out


# ------------------------------------------------------------------------------------------- A: the mango statement
@pytest.mark.parametrize(("lang", "text", "crop_word"), [("kn", MANGO_KN, "ಮಾವು"), ("en", MANGO_EN, "Mango")])
@pytest.mark.parametrize("path", ["/assistant/chat", "/voice/intent"])
def test_the_mango_statement_is_understood_and_checked_against_the_farm_records(
    db_client, farmer, farm, mango, lang, text, crop_word, path
):
    r = Chat(db_client, farmer, lang, path).say(text)
    assert r["intent"] == "crop_statement", r
    assert crop_word in r["answer"] and APOLOGY_KN not in r["answer"]
    assert r["language"] == lang and r["tool_calls"][0]["tool"] == "farm_crops" and r["tool_calls"][0]["ok"]
    # the farmer's records have no mango crop yet: said so, never claimed as recorded
    assert ("not in your records" in r["answer"]) if lang == "en" else ("ದಾಖಲೆಗಳಲ್ಲಿ ಇಲ್ಲ" in r["answer"])


def test_a_recorded_mango_crop_is_recognised(db_client, farmer, farm, mango, api):
    api.cycle(farmer, api.plot(farmer, farm["id"], name="Mango orchard")["id"], mango["id"], status="growing")
    for lang, text in (("en", MANGO_EN), ("kn", MANGO_KN)):
        r = Chat(db_client, farmer, lang).say(text)
        assert r["intent"] == "crop_statement" and "Mango orchard" in r["answer"], (lang, r["answer"])


def test_the_statement_answers_the_previous_question_instead_of_repeating_it(db_client, farmer, farm, mango):
    for lang, question, statement in (
        ("en", "What would be my profit per acre?", MANGO_EN),
        ("kn", "ಒಂದು ಎಕರೆಗೆ ಲಾಭ ಎಷ್ಟು ಆಗಬಹುದು", MANGO_KN),
    ):
        c = Chat(db_client, farmer, lang)
        first = c.say(question)
        assert first["intent"] == "crop_estimate"  # asks which crop
        second = c.say(statement)
        assert second["intent"] == "crop_estimate" and second["answer"] != first["answer"], second
        assert ("Mango" in second["answer"]) if lang == "en" else ("ಮಾವು" in second["answer"])
        assert APOLOGY_KN not in second["answer"]


def test_the_crop_stated_earlier_is_used_by_later_questions(db_container, db_client, farmer, farm, mango):
    db_container.llm = DisabledLLMProvider()  # suitability may add labelled general advice; the records part is checked
    for lang, statement, follow_up, word in (
        ("en", MANGO_EN, "Is it suitable for my farm?", "Mango"),
        ("kn", MANGO_KN, "ನನ್ನ ಜಮೀನಿಗೆ ಅದು ಸೂಕ್ತವೇ", "ಮಾವು"),
    ):
        c = Chat(db_client, farmer, lang)
        c.say(statement)
        r = c.say(follow_up)
        assert r["intent"] == "crop_suitability" and word in r["answer"], (lang, r["answer"])


# ------------------------------------------------------------------------------------ B: which crops are best
@pytest.mark.parametrize(("lang", "text"), [("en", BEST_EN), ("kn", BEST_KN)])
def test_best_crops_question_gives_a_records_based_shortlist_and_asks_what_is_missing(
    db_client, farmer, farm, catalogue, lang, text
):
    r = Chat(db_client, farmer, lang).say(text)
    assert r["intent"] == "crop_recommendation", r
    tools = [c["tool"] for c in r["tool_calls"]]
    assert tools == ["crop_recommendation"] and r["tool_calls"][0]["ok"]
    a = r["answer"]
    assert "Mysuru" in a  # the authenticated farm record
    assert ("soil" in a and "water source" in a) if lang == "en" else ("ಮಣ್ಣು" in a and "ನೀರಿನ ಮೂಲ" in a)
    assert "₹" not in a and " kg" not in a  # no invented prices or yields
    assert ("Sugarcane" not in a) if lang == "en" else ("ಕಬ್ಬು" not in a)  # not suggested with no known water source


def test_recommendation_uses_recorded_soil_and_water_and_the_answer_given_later(
    db_client, farmer, farm, catalogue, api
):
    c = Chat(db_client, farmer, "en")
    first = c.say(BEST_EN)
    assert "water source" in first["answer"]
    second = c.say("red soil, borewell irrigation")
    assert second["intent"] == "crop_recommendation" and second["answer"] != first["answer"]
    assert "red" in second["answer"] and "borewell" in second["answer"] and "water source" not in second["answer"]
    api.plot(farmer, farm["id"], soil_type="black", irrigation_type="rainfed")
    rainfed = Chat(db_client, farmer, "en").say(BEST_EN)["answer"]
    assert "black" in rainfed and "rainfed" in rainfed and "Sugarcane" not in rainfed and "Tomato" not in rainfed


def test_the_mango_statement_after_the_best_crops_question_is_context_not_a_new_apology(
    db_client, farmer, farm, catalogue
):
    for lang, question, statement, word in (("en", BEST_EN, MANGO_EN, "Mango"), ("kn", BEST_KN, MANGO_KN, "ಮಾವು")):
        c = Chat(db_client, farmer, lang)
        first = c.say(question)
        second = c.say(statement)
        assert second["intent"] == "crop_recommendation" and second["answer"] != first["answer"], second
        assert word in second["answer"] and APOLOGY_KN not in second["answer"]


def test_english_and_kannada_use_the_same_records_and_logic(db_client, farmer, farm, catalogue):
    en = Chat(db_client, farmer, "en").say(BEST_EN)
    kn = Chat(db_client, farmer, "kn").say(BEST_KN)
    assert en["intent"] == kn["intent"] == "crop_recommendation"
    assert en["tool_calls"][0]["args"] == kn["tool_calls"][0]["args"]
    en_crops = {c for c in ("Bengal Gram", "Tomato", "Ragi") if c in en["answer"]}
    kn_crops = {c for c, k in (("Bengal Gram", "ಕಡಲೆ"), ("Tomato", "ಟೊಮೆಟೊ"), ("Ragi", "ರಾಗಿ")) if k in kn["answer"]}
    assert en_crops == kn_crops and en_crops


def test_other_farmers_records_are_never_used(db_client, farmer, other_farmer, api, catalogue):
    api.farm(other_farmer, name="Not Mine", district="Belagavi")
    r = Chat(db_client, farmer, "en").say(BEST_EN)
    assert "Belagavi" not in r["answer"] and "add your farm" in r["answer"]


def test_voice_replies_include_the_text_the_server_actually_read(db_client, farmer, farm, mango):
    raw = "ನಾನು ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಮಾವು\u200c ಬೆಳೆಯುತ್ತಿದ್ದೇನೆ. ೨ ಎಕರೆ"
    voice = Chat(db_client, farmer, "kn", "/voice/intent").say(raw)
    assert voice["normalised"] == "ನಾನು ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಮಾವು ಬೆಳೆಯುತ್ತಿದ್ದೇನೆ 2 ಎಕರೆ"  # joiners, punctuation, digits
    assert Chat(db_client, farmer, "kn").say(raw)["normalised"] is None  # typed chat: not a speech transcript
