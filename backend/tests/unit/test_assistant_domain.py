"""Assistant core: language detection, limited intents (English/Kannada), reminder slots, grounding, templates."""

from datetime import date
from decimal import Decimal

import pytest

from app.core.enums import ReminderType
from app.domain.assistant.grounding import grounded, numbers_in
from app.domain.assistant.intents import Intent, detect_language, local_due, recognise, reminder_slots
from app.domain.assistant.templates import DISCLAIMER, T, render

TODAY = date(2026, 10, 8)


@pytest.mark.parametrize(
    ("text", "intent", "lang"),
    [
        ("What is the weather this week?", Intent.WEATHER, "en"),
        ("ನಾಳೆ ಮಳೆ ಬರುತ್ತದೆಯೇ?", Intent.WEATHER, "kn"),
        ("How much will I harvest?", Intent.HARVEST_PREDICTION, "en"),
        ("ನನ್ನ ಟೊಮೆಟೊ ಇಳುವರಿ ಎಷ್ಟು?", Intent.HARVEST_PREDICTION, "kn"),
        ("what is my farm risk", Intent.FARM_RISK, "en"),
        ("ಅಪಾಯ ಎಷ್ಟು", Intent.FARM_RISK, "kn"),
        ("show my reminders", Intent.REMINDERS_LIST, "en"),
        ("remind me to water the plot tomorrow", Intent.REMINDER_CREATE, "en"),
        ("ನಾಳೆ ನೀರು ಹಾಕಲು ನೆನಪಿಸು", Intent.REMINDER_CREATE, "kn"),
        ("how much stock is available", Intent.INVENTORY, "en"),
        ("are there buyers for tomato", Intent.BUYER_OPPORTUNITIES, "en"),
        ("ಖರೀದಿದಾರರು ಇದ್ದಾರೆಯೇ", Intent.BUYER_OPPORTUNITIES, "kn"),
        ("do I have supply requests", Intent.SUPPLY_REQUESTS, "en"),
        ("leaves are turning yellow", Intent.CROP_HEALTH_HELP, "en"),
        ("ಎಲೆಗಳಲ್ಲಿ ಕಲೆ ಮತ್ತು ರೋಗ", Intent.CROP_HEALTH_HELP, "kn"),
        ("allocate 500 kg of my tomato to the buyer", Intent.ALLOCATION_REQUEST, "en"),
        ("please reallocate the pool", Intent.ALLOCATION_REQUEST, "en"),
        ("ಹಂಚಿಕೆ ಬದಲಿಸು", Intent.ALLOCATION_REQUEST, "kn"),
        ("help", Intent.HELP, "en"),
        ("qwerty zxcv", Intent.UNKNOWN, "en"),
        ("", Intent.UNKNOWN, "en"),
    ],
)
def test_intents(text, intent, lang):
    r = recognise(text, today=TODAY)
    assert (r.intent, r.language) == (intent, lang)
    assert 0 <= r.confidence <= 1


def test_preferred_language_is_used_for_latin_text_and_kannada_script_always_wins():
    assert detect_language("weather", "kn") == "kn"
    assert detect_language("ಹವಾಮಾನ", "en") == "kn"
    assert detect_language("weather", "fr") == "en"


@pytest.mark.parametrize(
    ("text", "when", "hour", "kind"),
    [
        ("remind me to irrigate the plot tomorrow at 6 am", date(2026, 10, 9), 6, ReminderType.IRRIGATION),
        ("remind me to spray in 3 days at 5 pm", date(2026, 10, 11), 17, ReminderType.CROP_HEALTH),
        ("remind me to harvest on 2026-11-02", date(2026, 11, 2), 9, ReminderType.HARVEST),
        ("remind me to call the hub today", TODAY, 9, ReminderType.COLLECTION),
        ("ನಾಡಿದ್ದು ಗೊಬ್ಬರ ಹಾಕಲು ನೆನಪಿಸು", date(2026, 10, 10), 9, ReminderType.ACTIVITY),
        ("remind me about something", None, 9, ReminderType.CUSTOM),  # no date: ask, never guess
    ],
)
def test_reminder_slots(text, when, hour, kind):
    s = reminder_slots(text, TODAY)
    assert (s["date"], s["hour"], s["reminder_type"]) == (when, hour, kind)
    assert s["title"] and len(str(s["title"])) <= 160


def test_reminder_title_strips_command_and_time_words():
    assert (
        reminder_slots("Remind me to irrigate the tomato plot tomorrow at 6 am", TODAY)["title"]
        == "irrigate the tomato plot"
    )


def test_local_due_is_india_time():
    due = local_due(date(2026, 10, 9), 6)
    assert due.utcoffset().total_seconds() == 5.5 * 3600 and due.hour == 6


def test_grounding_accepts_only_numbers_present_in_facts():
    facts = [Decimal("432.5"), 12, "2026-10-09", "Farm A"]
    assert grounded("Expected about 432.5 kg, roughly 433, starting 2026-10-09.", facts)
    assert not grounded("Expected 450 kg.", facts)  # invented number
    assert not grounded("Price will be 30 rupees per kg.", facts)  # invented price
    assert grounded("ಸುಮಾರು ೪೩೨.೫ ಕೆ.ಜಿ.", facts)  # Kannada digits are checked too
    assert not grounded("", facts) and not grounded("x" * 2000, facts)


def test_numbers_in_parses_commas_and_kannada_digits():
    assert numbers_in("1,250 kg and ೧೨ days") == {Decimal(1250), Decimal(12)}


def test_every_template_exists_in_both_languages_and_renders():
    sample = {
        "farm": "F",
        "rain": "1",
        "days": 7,
        "tmax": "30",
        "source": "s",
        "reason": "r",
        "crop": "c",
        "p10": "1",
        "p50": "2",
        "p90": "3",
        "conf": "50",
        "level": "low",
        "start": "2026-10-10",
        "score": "10",
        "assessed": 3,
        "n": 1,
        "items": "",
        "title": "t",
        "when": "w",
        "available": "1",
        "farms": "1",
        "plots": "1",
        "acres": "1",
        "screen": "Market",
        "crop_list": "",
        "committed": "1",
        "plan": "p",
        "crops": 2,
        "expected": "3",
        "low": "1",
        "high": "5",
        "total": "100",
        "entries": "1 entry",
        "what": "",
        "amount": "500",
        "category": "seed",
        "date": "2026-10-09",
        "tmin": "20",
        "fetched": "14 Oct 10:00",
        "status": "latest forecast",
        "missing": "price",
        "ref": "",
        "basis": "catalogue",
        "cost": "30000",
        "ylow": "4200",
        "yhigh": "7800",
        "rlow": "1",
        "rhigh": "2",
        "mlow": "1",
        "mhigh": "2",
        "mexp": "1",
        "y_basis": "a",
        "p_basis": "b",
        "c_basis": "c",
        "season": "rabi",
        "water": "350",
        "place": "Mysuru",
        "soils": "red",
        "irrigation": "drip",
    }
    for key, table in T.items():
        assert set(table) == {"en", "kn"}, key
        for lang in ("en", "kn"):
            assert render(key, lang, **sample)
    assert set(DISCLAIMER) == {"en", "kn"}


def test_kannada_templates_are_written_in_kannada_script():
    import re

    for key, table in T.items():
        assert re.search(r"[ಀ-೿]", table["kn"]), key


def test_allocation_refusal_says_the_assistant_does_not_decide():
    assert "can't decide or change allocation" in render("allocation_refused", "en")


# ------------------------------------------------------------------ expenses and follow-ups
def test_spoken_expenses_are_parsed_without_guessing():
    from datetime import date

    from app.core.enums import ExpenseCategory
    from app.domain.assistant.intents import expense_record_slots

    today = date(2026, 10, 9)
    s = expense_record_slots("I spent 1,500 rupees on urea yesterday", today)
    assert s is not None and (s["amount"], s["category"], s["date"]) == (
        "1500",
        ExpenseCategory.FERTILIZER,
        date(2026, 10, 8),
    )
    s = expense_record_slots("paid 250.50 for the tractor", today)
    assert s is not None and (s["amount"], s["category"]) == ("250.50", ExpenseCategory.MACHINERY)
    s = expense_record_slots("ಮೊನ್ನೆ ಬೀಜಕ್ಕೆ ೪೦೦ ರೂಪಾಯಿ ಖರ್ಚು ಮಾಡಿದೆ", today)  # Kannada digits
    assert s is not None and (s["amount"], s["category"], s["date"]) == ("400", ExpenseCategory.SEED, date(2026, 10, 7))
    s = expense_record_slots("I spent money on labour", today)
    assert s is not None and s["amount"] is None  # asked, never invented
    assert expense_record_slots("how much did I spend on seeds?", today) is None  # a question, not a recording
    assert expense_record_slots("ಎಷ್ಟು ಖರ್ಚು ಮಾಡಿದೆ", today) is None
    assert expense_record_slots("what is the weather", today) is None


def test_expense_question_periods():
    from datetime import date

    from app.domain.assistant.intents import expense_summary_slots

    today = date(2026, 10, 9)
    assert expense_summary_slots("spent this month", today)["from"] == date(2026, 10, 1)
    last = expense_summary_slots("expenses last month", today)
    assert (last["from"], last["to"]) == (date(2026, 9, 1), date(2026, 9, 30))
    assert expense_summary_slots("expenses in the last 10 days", today)["from"] == date(2026, 9, 30)
    assert expense_summary_slots("ಈ ವರ್ಷ ಖರ್ಚು", today)["from"] == date(2026, 1, 1)
    assert expense_summary_slots("all my expenses", today)["from"] is None


def test_expense_intents_are_recognised_in_both_languages():
    assert recognise("I spent 500 on pesticide").intent.value == "expense_record"
    assert recognise("how much did I spend on pesticide").intent.value == "expense_summary"
    assert recognise("ಈ ತಿಂಗಳ ಖರ್ಚು ಎಷ್ಟು").intent.value == "expense_summary"
    assert recognise("remind me to record expenses tomorrow").intent.value == "reminder_create"


def test_follow_up_markers():
    from app.domain.assistant.intents import is_follow_up

    for text in ("and tomorrow?", "what about ragi?", "ಮತ್ತೆ ನಾಳೆ?", "for my other farm", "ragi?"):
        assert is_follow_up(text), text
    for text in ("tell me a story about farming in the old days", "show my reminders"):
        assert not is_follow_up(text), text


def test_general_answer_checker():
    from app.services.assistant import CAUTION, checked_general_answer

    assert checked_general_answer("Water early in the morning.") == "Water early in the morning."
    out = checked_general_answer("Apply 20 kg of urea per acre. Your crop yield is 400 kg this year.")
    assert out is not None and "Your crop yield" not in out and out.endswith(CAUTION)
    assert checked_general_answer("Usually about 2 sprays are enough; check the label.") == (
        "Usually about 2 sprays are enough; check the label."
    )
    assert checked_general_answer("Your farm has 3 plots.") is None  # nothing usable left
    assert len(checked_general_answer("word " * 1000) or "") == 1500


def test_question_scope():
    from app.domain.assistant.intents import question_scope

    assert question_scope("how much did I spend this month") == "personal"
    assert question_scope("what is the weather") == "personal"
    assert question_scope("what is a rain shadow") == "general"
    assert question_scope("why do leaves turn yellow") == "general"
    assert question_scope("how can I reduce my fertilizer expenses") == "mixed"
    assert question_scope("ಬಿತ್ತನೆಗೆ ಮೊದಲು ಮಣ್ಣನ್ನು ಹೇಗೆ ಸುಧಾರಿಸಬಹುದು") == "general"
    assert question_scope("ನನ್ನ ಖರ್ಚು ಹೇಗೆ ಕಡಿಮೆ ಮಾಡಬಹುದು") == "mixed"


def test_general_answers_drop_i_cannot_see_your_records_sentences():
    from app.services.assistant import checked_general_answer

    text = (
        "I'm not able to see your farm records, so I don't know the exact number of farms you have. "
        "I'm not aware of your farm details. To improve soil health, add compost and rotate crops."
    )
    assert checked_general_answer(text) == "To improve soil health, add compost and rotate crops."
    assert checked_general_answer("I cannot see your records.") is None


def test_a_general_answer_does_not_start_with_a_dangling_connective():
    from app.services.assistant import checked_general_answer

    text = "I'm not able to see your farm records. However, I can share general tips: add compost and rotate crops."
    assert checked_general_answer(text) == "I can share general tips: add compost and rotate crops."
