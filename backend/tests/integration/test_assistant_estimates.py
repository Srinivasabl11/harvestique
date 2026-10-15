# ruff: noqa: RUF001  (the answers use the real multiplication and minus signs)
"""Income-estimate conversations, English and Kannada (typed transcripts): the phone example, follow-ups, corrections,
ambiguous numbers, missing inputs, units, the calculator's result, context reset and routing."""

from __future__ import annotations

import pytest

from app.providers.llm.fake import DisabledLLMProvider

pytestmark = pytest.mark.integration
API = "/api/v1"


class NoModel:
    """Any model call fails the test: estimates must never be answered by the language model."""

    name = model = "none"

    def is_available(self) -> bool:
        return True

    def generate(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError(f"the model was asked: {request.messages[-1].content}")


@pytest.fixture(autouse=True)
def no_llm(db_container):
    db_container.llm = NoModel()


@pytest.fixture
def tomato(api, admin):
    return api.crop(
        admin,
        name="Tomato",
        local_name="ಟೊಮೆಟೊ",
        category="vegetable",
        typical_duration_days=120,
        reference_yield_kg_per_acre=10000,
        reference_yield_cv=0.35,
    )


class Chat:
    """One conversation, keeping history the way the app does (text + intent of each reply)."""

    def __init__(self, client, actor, lang):
        self.client, self.actor, self.lang, self.history = client, actor, lang, []

    def say(self, text):
        r = self.client.post(
            f"{API}/assistant/chat",
            headers=self.actor.headers,
            json={"message": text, "language": self.lang, "history": self.history[-8:]},
        )
        assert r.status_code == 200, r.text
        out = r.json()
        self.history += [
            {"role": "user", "text": text},
            {"role": "assistant", "text": out["answer"][:1200], "intent": out["intent"]},
        ]
        return out


def test_phone_example_english_asks_what_the_numbers_mean_then_calculates(db_client, farmer, tomato):
    c = Chat(db_client, farmer, "en")
    first = c.say("How much income can I get from one acre of tomato?")
    assert first["intent"] == "crop_estimate" and "selling price per kg" in first["answer"]
    second = c.say("For example 20 kg and ₹50,000")
    assert second["intent"] == "crop_estimate" and second["understood_by"] == "context"
    assert second["answer"] != first["answer"]  # never the previous reply again
    assert "20 kg" in second["answer"] and "₹50,000" in second["answer"] and "?" in second["answer"]
    assert second["tool_calls"] == [] and "Typical income" not in second["answer"]
    third = c.say("20 kg is the harvest per acre, 50000 is the total cost, price 30 rupees per kg")
    assert third["tool_calls"][0]["tool"] == "income_calculator" and third["tool_calls"][0]["ok"]
    a = third["answer"]
    assert "20 kg × ₹30 per kg (you said) = ₹600" in a and "₹600 − ₹50,000 = −₹49,400 (a loss)" in a
    assert "Please check: 20 kg per acre is far from the usual" in a  # 20 kg for an acre of tomato: unit warning
    assert "not a guarantee" in a


def test_phone_example_kannada(db_client, farmer, tomato):
    c = Chat(db_client, farmer, "kn")
    first = c.say("ಒಂದು ಎಕರೆ ಟೊಮೆಟೊ ಆದಾಯ ಎಷ್ಟು")
    assert first["intent"] == "crop_estimate" and first["language"] == "kn"
    second = c.say("ಉದಾಹರಣೆಗೆ 20 ಕೆಜಿ ಮತ್ತು 50,000 ರೂಪಾಯಿ")
    assert second["intent"] == "crop_estimate" and second["answer"] != first["answer"] and second["language"] == "kn"
    assert "ಸಂಖ್ಯೆಗಳ ಅರ್ಥ" in second["answer"] and "₹50,000" in second["answer"]
    third = c.say("ಕೆಜಿಗೆ 20 ರೂಪಾಯಿ, ಖರ್ಚು 50000")  # "ಖರ್ಚು" here is part of the estimate, not past expenses
    assert third["intent"] == "crop_estimate" and third["tool_calls"][0]["tool"] == "income_calculator"
    # catalogue harvest 6,500-13,500 (expected 10,000) kg x Rs 20 = Rs 2,00,000 expected; profit 2,00,000 - 50,000
    assert "₹2,00,000 − ₹50,000 = ₹1,50,000" in third["answer"] and "ಕ್ಯಾಟಲಾಗ್ ಅಂದಾಜು" in third["answer"]
    assert "ಖಾತರಿ ಅಲ್ಲ" in third["answer"]


def test_missing_inputs_are_asked_in_one_question(db_client, farmer, tomato):
    for lang, text, words in (
        ("en", "What would be the profit from tomato?", ("how many acres", "selling price per kg", "your cost")),
        ("kn", "ಟೊಮೆಟೊ ಲಾಭ ಎಷ್ಟು ಆಗಬಹುದು", ("ಎಷ್ಟು ಎಕರೆ", "ಕೆಜಿಗೆ ಮಾರಾಟ ಬೆಲೆ", "ನಿಮ್ಮ ಖರ್ಚು")),
    ):
        r = Chat(db_client, farmer, lang).say(text)
        assert r["intent"] == "crop_estimate" and r["tool_calls"] == [], text
        assert all(w in r["answer"] for w in words), r["answer"]
        assert "₹" not in r["answer"].split("Harvest I would use")[0]


def test_income_and_cost_given_directly(db_client, farmer):
    r = Chat(db_client, farmer, "en").say("one acre, income 1,20,000 and cost 45000, what is my profit?")
    assert r["intent"] == "crop_estimate" and "₹1,20,000 − ₹45,000 = ₹75,000" in r["answer"]


def test_corrections_and_units_change_the_result(db_client, farmer, tomato):
    c = Chat(db_client, farmer, "en")
    c.say("profit from 2 acres of tomato?")
    first = c.say("harvest 80 quintal per acre, price ₹1500 per quintal, cost 40000 per acre")
    # 8000 kg x 2 acres = 16,000 kg x Rs 15 = Rs 2,40,000; cost 80,000
    assert "16,000 kg × ₹15 per kg (you said) = ₹2,40,000" in first["answer"]
    assert "₹2,40,000 − ₹80,000 = ₹1,60,000" in first["answer"]
    corrected = c.say("sorry, the price is 20 rupees per kg")
    assert "₹3,20,000 − ₹80,000 = ₹2,40,000" in corrected["answer"] and corrected["answer"] != first["answer"]


def test_scope_is_asked_when_more_than_one_acre(db_client, farmer, tomato):
    c = Chat(db_client, farmer, "en")
    c.say("profit from 2 acres of tomato, price 20 rupees per kg")
    r = c.say("cost 60000")
    assert "whether ₹60,000 is the cost per acre or for all 2 acres" in r["answer"] and r["tool_calls"] == []


def test_a_new_crop_starts_a_fresh_estimate(db_client, farmer, tomato, api, admin):
    api.crop(admin, name="Onion", local_name="ಈರುಳ್ಳಿ", category="vegetable", typical_duration_days=110)
    c = Chat(db_client, farmer, "en")
    c.say("one acre of tomato, price 20 rupees per kg, cost 50000")
    r = c.say("what about onion?")
    assert r["intent"] == "crop_estimate" and "Onion" in r["answer"]
    assert "selling price per kg" in r["answer"]  # tomato's price is not reused for onion


def test_other_questions_after_an_estimate_are_routed_normally(db_container, db_client, farmer, tomato):
    c = Chat(db_client, farmer, "en")
    c.say("one acre of tomato, price 20 rupees per kg")
    assert c.say("show my reminders")["intent"] == "reminders_list"
    assert c.say("Open Market")["navigate_to"] == "market"
    db_container.llm = DisabledLLMProvider()
    general = c.say("what is crop rotation?")
    assert general["intent"] == "unknown" and general["tool_calls"] == []  # no number, no crop: not the estimate
    # a new conversation (empty history) does not inherit the old numbers
    fresh = Chat(db_client, farmer, "en").say("cost 50000")
    assert fresh["intent"] != "crop_estimate" or "acres" in fresh["answer"]


def test_estimates_are_not_saved_plans_and_buyers_cannot_use_them(db_client, farmer, buyer, tomato):
    r = Chat(db_client, farmer, "en").say("income from one acre of tomato")
    assert r["intent"] == "crop_estimate" and "income_plans" not in str(r["tool_calls"])
    assert Chat(db_client, farmer, "en").say("show my income plans")["intent"] == "income_plans"
    b = Chat(db_client, buyer, "en").say("income from one acre of tomato")
    assert "not available for your account type" in b["answer"]
