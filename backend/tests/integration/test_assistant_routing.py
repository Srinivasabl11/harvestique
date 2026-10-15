"""The assistant's routing for the 12 request types, in English AND Kannada (typed transcripts; device speech is not
tested here). The local model is a scripted double, so routing, tool choice, authorization and the final answer are
checked exactly; the live model is measured separately (docs/ASSISTANT_EVAL_2026-10-14.md)."""

from __future__ import annotations

import pytest

from app.core.errors import ProviderUnavailableError
from app.providers.llm.base import LLMRequest, LLMResponse
from app.providers.llm.fake import DisabledLLMProvider
from tests.conftest import FailingWeather, days_from_today

pytestmark = pytest.mark.integration
API = "/api/v1"


class ScriptedLLM:
    name = "scripted"
    model = "scripted-model"

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.requests: list[LLMRequest] = []

    def is_available(self) -> bool:
        return True

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMResponse(text=reply, model=self.model, provider=self.name)


@pytest.fixture(autouse=True)
def no_llm(db_container):
    db_container.llm = DisabledLLMProvider()


def ask(client, actor, message, **kw):
    r = client.post(f"{API}/assistant/chat", headers=actor.headers, json={"message": message, **kw})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def cucumber(api, admin):
    return api.crop(
        admin,
        name="Cucumber",
        local_name="ಸೌತೆಕಾಯಿ",
        category="vegetable",
        typical_duration_days=75,
        reference_yield_kg_per_acre=6000,
        reference_yield_cv=0.3,
        water_need_mm=400,
    )


@pytest.fixture
def carrot(api, admin):
    return api.crop(admin, name="Carrot", local_name="ಕ್ಯಾರೆಟ್", category="vegetable", typical_duration_days=100)


# 1-2: general questions need no record and use no tool, in both languages
@pytest.mark.parametrize(
    ("question", "lang"),
    [
        ("What is crop rotation?", "en"),
        ("What is photosynthesis?", "en"),
        ("ಬೆಳೆ ಸರದಿ ಎಂದರೇನು", "kn"),
        ("ದ್ಯುತಿಸಂಶ್ಲೇಷಣೆ ಎಂದರೇನು", "kn"),
    ],
)
def test_general_questions_are_answered_without_records(db_container, db_client, farmer, question, lang):
    llm = ScriptedLLM('{"tool": "general"}', "Growing different crops in turn keeps the soil healthy.")
    if lang == "kn":
        llm = ScriptedLLM("Growing different crops in turn keeps the soil healthy.")  # no routing call for Kannada
    db_container.llm = llm
    r = ask(db_client, farmer, question, language=lang)
    assert r["answer_kind"] == "general_ai" and r["tool_calls"] == [] and "Growing different" in r["answer"]
    assert r["language"] == "en"  # read with the English voice: the answer IS English
    if lang == "kn":
        # glossary term + "ಎಂದರೇನು": an English question without a translation call, shown to the user
        sent = llm.requests[-1].messages[-1].content
        assert len(llm.requests) == 1 and sent in ("What is crop rotation?", "What is photosynthesis?")
        assert r["answer"].startswith(f'ನಾನು ಅರ್ಥಮಾಡಿಕೊಂಡ ಪ್ರಶ್ನೆ / Understood as: "{sent}"')
        assert "ಇಂಗ್ಲಿಷ್" in r["disclaimer"]


def test_a_kannada_answer_in_the_wrong_language_is_retried_then_dropped(db_container, db_client, farmer):
    # the model wrote (garbled) Kannada although asked for English: asked again, the English answer is used
    db_container.llm = ScriptedLLM("ಬೆಳೆ ಸರದಿ ಎಂದರೆ ಬೀಜ ಬಿಡುಗಡೆ", "Crop rotation means changing crops each season.")
    r = ask(db_client, farmer, "ಬೆಳೆ ಸರದಿ ಎಂದರೇನು", language="kn")
    assert "Crop rotation means" in r["answer"] and r["language"] == "en"
    # still Kannada, or text drifting into other scripts: never read out with the wrong voice
    for replies in (("ಕನ್ನಡ ಉತ್ತರ", "ಮತ್ತೆ ಕನ್ನಡ"), ("Photosynthesis uses वाणिज्य light.",)):
        db_container.llm = ScriptedLLM(*replies)
        r = ask(db_client, farmer, "ದ್ಯುತಿಸಂಶ್ಲೇಷಣೆ ಎಂದರೇನು", language="kn")
        assert r["answer_kind"] == "guidance" and r["tool_calls"] == [], replies


def test_other_kannada_general_questions_are_translated_then_answered(db_container, db_client, farmer):
    llm = ScriptedLLM("What is the capital of India?", "New Delhi is the capital of India.")
    db_container.llm = llm
    r = ask(db_client, farmer, "ಭಾರತದ ರಾಜಧಾನಿ ಯಾವುದು", language="kn")
    assert r["answer_kind"] == "general_ai" and "New Delhi" in r["answer"]
    assert 'Understood as: "What is the capital of India?"' in r["answer"]
    assert "Translate" in llm.requests[0].messages[0].content and llm.requests[1].messages[-1].content == (
        "What is the capital of India?"
    )
    # glossary terms are replaced before translation (the models misread them)
    db_container.llm = llm = ScriptedLLM("How to stop leaf curl disease in tomato?", "Remove infected plants.")
    ask(db_client, farmer, "ಟೊಮೆಟೊ ಎಲೆ ಮುರುಟು ರೋಗ ತಡೆಯುವುದು ಹೇಗೆ", language="kn")
    assert "leaf curl disease" in llm.requests[0].messages[-1].content
    # a translation that is still Kannada (or empty) is not answered
    db_container.llm = ScriptedLLM("ಭಾರತದ ರಾಜಧಾನಿ")
    r = ask(db_client, farmer, "ಭಾರತದ ರಾಜಧಾನಿ ಯಾವುದು", language="kn")
    assert r["answer_kind"] == "guidance" and r["tool_calls"] == []


# 3: own farms and crops
def test_farm_and_crop_questions_use_the_farmers_records(db_client, farmer, other_farmer, api, admin):
    f = api.farm(farmer, name="Green Acres", total_area_acres=4)
    api.cycle(farmer, api.plot(farmer, f["id"])["id"], api.crop(admin, name="Ragi")["id"])
    api.farm(other_farmer, name="Not Mine")
    for q in ("How many farms do I have and what crops?", "ನನ್ನ ಜಮೀನುಗಳು ಮತ್ತು ಬೆಳೆಗಳು ಯಾವುವು"):
        r = ask(db_client, farmer, q)
        assert r["intent"] == "farm_summary" and r["tool_calls"][0]["tool"] == "farm_summary", q
        assert "Ragi" in r["answer"] and "Not Mine" not in r["answer"], q


# 4: saved income plans
def test_income_plan_retrieval(db_client, farmer):
    for q in ("Show my income plans", "ನನ್ನ ಆದಾಯ ಯೋಜನೆಗಳನ್ನು ತೋರಿಸು"):
        r = ask(db_client, farmer, q)
        assert r["intent"] == "income_plans" and r["tool_calls"][0]["tool"] == "income_plans", q


# 5: one-acre estimate: never the saved-plan list; asks for price and cost; computes with the real calculator
def test_one_acre_estimate_asks_for_missing_inputs_instead_of_guessing(db_client, farmer, cucumber):
    for q, lang in (
        ("What is the cost and profit of growing cucumber on one acre?", "en"),
        ("ಒಂದು ಎಕರೆ ಸೌತೆಕಾಯಿ ಬೆಳೆಯಲು ಖರ್ಚು ಮತ್ತು ಲಾಭ ಎಷ್ಟು", "kn"),
    ):
        r = ask(db_client, farmer, q, language=lang)
        assert r["intent"] == "crop_estimate" and r["tool_calls"] == [], q
        assert "4,200" in r["answer"] and "7,800" in r["answer"], r["answer"]  # catalogue 6000 kg ±30 %, labelled
        assert ("selling price" in r["answer"]) if lang == "en" else ("ಮಾರಾಟ ಬೆಲೆ" in r["answer"])
        assert "₹" not in r["answer"]  # no money figure without the farmer's price and cost


def test_one_acre_estimate_uses_the_income_calculator(db_client, farmer, cucumber):
    r = ask(db_client, farmer, "cost and profit of cucumber on 1 acre, price 10 rupees per kg, cost 30000 per acre")
    assert r["intent"] == "crop_estimate" and r["tool_calls"][0] == {
        "tool": "income_calculator",
        "args": {"crop": "Cucumber", "acres": "1"},
        "ok": True,
        "error_code": None,
    }
    calc = db_client.post(
        f"{API}/planning/calculate",
        headers=farmer.headers,
        json={
            "available_land_acres": 1,
            "items": [
                {
                    "crop_name": "Cucumber",
                    "sowing_date": days_from_today(0),
                    "duration_days": 75,
                    "area_acres": 1,
                    "yield_per_acre_kg": {"low": 4200, "expected": 6000, "high": 7800},
                    "price_per_kg": {"low": 10, "expected": 10, "high": 10},
                    "cost": {"other_per_acre": 30000},
                    "estimate_basis": "assumption",
                }
            ],
        },
    ).json()["totals"]
    m = calc["margin"]
    assert m["expected"] == 30000  # expected revenue 6,000 kg x Rs 10 = 60,000, minus 30,000 cost
    assert "₹60,000 \u2212 ₹30,000 = ₹30,000" in r["answer"], r["answer"]
    assert "not a guarantee" in r["answer"] and "catalogue estimate" in r["answer"]
    kn = ask(db_client, farmer, "ಒಂದು ಎಕರೆ ಸೌತೆಕಾಯಿ, ಕೆಜಿಗೆ 10 ರೂಪಾಯಿ, ಎಕರೆಗೆ 30000 ಖರ್ಚು, ಲಾಭ ಎಷ್ಟು")
    assert kn["intent"] == "crop_estimate" and kn["tool_calls"][0]["ok"] and "ಖಾತರಿ ಅಲ್ಲ" in kn["answer"]


def test_estimates_are_for_farmers_only(db_client, buyer, cucumber):
    r = ask(db_client, buyer, "cost and profit of cucumber on one acre")
    assert r["tool_calls"] == [] and "not available for your account type" in r["answer"]


# 6: suitability: farm facts + labelled advice, missing details asked, never a verdict
def test_crop_suitability_combines_farm_records_and_general_advice(db_container, db_client, farmer, api, carrot):
    farm = api.farm(farmer, name="Hill Farm", district="Mysuru", latitude=12.3, longitude=76.6)
    api.plot(farmer, farm["id"], soil_type="red")
    db_container.llm = ScriptedLLM("Carrots like loose, well-drained soil and cool weather.")
    r = ask(db_client, farmer, "Can I grow carrots on my farm?")
    assert r["intent"] == "crop_suitability" and r["answer_kind"] == "mixed"
    assert "red" in r["answer"] and "Mysuru" in r["answer"] and "General advice (AI" in r["answer"]
    assert "irrigation" in r["answer"] and "definite yes or no" in r["answer"]  # missing water source is asked
    db_container.llm = DisabledLLMProvider()
    kn = ask(db_client, farmer, "ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಕ್ಯಾರೆಟ್ ಬೆಳೆಯಬಹುದೇ")
    assert kn["intent"] == "crop_suitability" and kn["answer_kind"] == "records" and kn["language"] == "kn"
    assert kn["answer"].startswith("ಕ್ಯಾರೆಟ್") and "ಹೌದು ಅಥವಾ ಇಲ್ಲ" in kn["answer"]


def test_suitability_without_a_farm_asks_for_it(db_client, farmer, carrot):
    r = ask(db_client, farmer, "Can I grow carrots here?")
    assert r["intent"] == "crop_suitability" and "add it in My Farm" in r["answer"]


# 7: weather, available (day-specific with freshness) and unavailable
def test_weather_tomorrow_says_the_day_and_how_fresh_the_forecast_is(db_client, farmer, api):
    api.farm(farmer, name="Green Acres", latitude=12.3, longitude=76.64)
    r = ask(db_client, farmer, "What will the weather be tomorrow on my farm?")
    assert r["intent"] == "weather" and "tomorrow" in r["answer"] and "fetched" in r["answer"]
    assert "latest forecast" in r["answer"]
    kn = ask(db_client, farmer, "ನಾಳೆ ನನ್ನ ಹೊಲದಲ್ಲಿ ಹವಾಮಾನ ಹೇಗಿರುತ್ತದೆ")
    assert kn["intent"] == "weather" and "ನಾಳೆ" in kn["answer"] and "ಮುನ್ಸೂಚನೆ ಪಡೆದದ್ದು" in kn["answer"]


def test_unavailable_weather_is_never_presented_as_live(db_container, db_client, farmer, api):
    api.farm(farmer, name="Green Acres", latitude=12.3, longitude=76.64)
    db_container.weather = FailingWeather()
    for q in ("What will the weather be tomorrow on my farm?", "ನಾಳೆ ನನ್ನ ಹೊಲದಲ್ಲಿ ಹವಾಮಾನ ಹೇಗಿರುತ್ತದೆ"):
        r = ask(db_client, farmer, q)
        assert r["intent"] == "weather" and "mm of rain" not in r["answer"] and "°C" not in r["answer"], r["answer"]
    no_location = api.farm(farmer, name="No GPS")
    r = ask(db_client, farmer, "weather tomorrow", farm_id=no_location["id"])
    assert "no location" in r["answer"]


# 8-10: demand vs harvest, reminders, navigation
def test_harvest_vs_demand_reminders_and_navigation_in_both_languages(db_client, farmer):
    pairs = [
        (
            "Compare my predicted harvest with buyer demand",
            "ನನ್ನ ಅಂದಾಜು ಇಳುವರಿಯನ್ನು ಖರೀದಿದಾರರ ಬೇಡಿಕೆಯೊಂದಿಗೆ ಹೋಲಿಸಿ",
            "buyer_opportunities",
        ),
        ("What reminders are due today?", "ಇವತ್ತು ಯಾವ ಜ್ಞಾಪನೆಗಳಿವೆ", "list_reminders"),
    ]
    for en, kn, tool in pairs:
        for q in (en, kn):
            r = ask(db_client, farmer, q)
            assert r["tool_calls"][0]["tool"] == tool, q
    for q in ("Open income planning", "ಆದಾಯ ಯೋಜನೆ ತೆರೆಯಿರಿ"):
        assert ask(db_client, farmer, q)["navigate_to"] == "planning", q


# 11: ambiguous / poorly transcribed
def test_garbled_requests_get_a_clarifying_question_in_the_right_language(db_container, db_client, farmer):
    db_container.llm = ScriptedLLM('{"tool": "none"}', "UNCLEAR")
    en = ask(db_client, farmer, "the thing over there")
    assert en["intent"] == "unknown" and en["tool_calls"] == [] and en["answer"].startswith("Sorry, I could not make")
    db_container.llm = ScriptedLLM("That which was there", "UNCLEAR.")  # translated, then judged unclear
    kn = ask(db_client, farmer, "ಅದು ಅಲ್ಲಿ ಇದ್ದದ್ದು", language="kn")
    assert kn["language"] == "kn" and kn["answer"].startswith("ಕ್ಷಮಿಸಿ, ಅದು ಸ್ಪಷ್ಟವಾಗಿ") and kn["tool_calls"] == []


def test_a_model_failure_gives_a_safe_answer(db_container, db_client, farmer):
    db_container.llm = ScriptedLLM(ProviderUnavailableError("down"))
    r = ask(db_client, farmer, "ಬೆಳೆ ಸರದಿ ಎಂದರೇನು", language="kn")
    assert r["tool_calls"] == [] and r["answer_kind"] == "guidance"


# 12: follow-ups use the conversation
def test_general_follow_ups_use_the_conversation_in_both_languages(db_container, db_client, farmer):
    for lang, q1, a1, q2 in (
        ("en", "What is crop rotation?", "Crop rotation means changing crops.", "And why is it useful?"),
        ("kn", "ಬೆಳೆ ಸರದಿ ಎಂದರೇನು", "Crop rotation means changing crops.", "ಅದರಿಂದ ಏನು ಪ್ರಯೋಜನ"),
    ):
        llm = ScriptedLLM("What is the benefit of it?", "It keeps the soil fertile and breaks pest cycles.")
        if lang == "en":
            llm = ScriptedLLM('{"tool": "general"}', "It keeps the soil fertile and breaks pest cycles.")
        db_container.llm = llm
        history = [{"role": "user", "text": q1}, {"role": "assistant", "text": a1}]
        r = ask(db_client, farmer, q2, language=lang, history=history)
        assert "It keeps the soil fertile" in r["answer"], lang
        sent = [m.content for m in llm.requests[-1].messages]
        assert q1 in sent and a1 in sent, lang
