"""Transcript -> intent regression on the voice corpora (English, Kannada as the kn-IN recogniser writes it, mixed)."""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.assistant.intents import NAV_TARGETS, Intent, navigation_target, normalise, recognise
from tests.unit.voice_corpus import CORPUS, Case
from tests.unit.voice_corpus_heldout import HELDOUT

TODAY = date(2026, 10, 14)


def understood(case: Case) -> str:
    r = recognise(case.text, case.lang, today=TODAY)
    return f"navigate:{r.slots['target']}" if r.intent is Intent.NAVIGATE else r.intent.value


@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c.text or "<silence>")
def test_development_corpus(case):
    assert understood(case) in case.expected


def test_held_out_phrasings_are_mostly_understood_and_never_sent_to_a_wrong_tool():
    results = [(case, understood(case)) for case in HELDOUT]
    correct = sum(got in case.expected for case, got in results)
    wrong_tool = [(case.text, got) for case, got in results if got not in case.expected and got != "unknown"]
    assert correct / len(HELDOUT) >= 0.95
    assert wrong_tool == []  # a misunderstood question must be asked back, not answered from another tool


def test_navigation_targets_are_an_allowlist():
    for case in CORPUS + HELDOUT:
        r = recognise(case.text, case.lang, today=TODAY)
        if r.intent is Intent.NAVIGATE:
            assert r.slots["target"] in NAV_TARGETS


def test_navigation_needs_an_explicit_command_and_reminders_win():
    assert navigation_target(normalise("market")) is None  # a bare word is not a command
    assert navigation_target(normalise("what is the market price of ragi today in mysore")) is None
    assert recognise("remind me to go to the field tomorrow").intent is Intent.REMINDER_CREATE
    assert recognise("ನಾಳೆ ಹೊಲಕ್ಕೆ ಹೋಗಲು ನೆನಪಿಸು").intent is Intent.REMINDER_CREATE
    assert navigation_target(normalise("ನಾನು ನಿನ್ನೆ ಮಾರುಕಟ್ಟೆಗೆ ಹೋಗಿದ್ದೆ")) is None  # "I went to the market yesterday"


def test_normalise_removes_joiners_punctuation_and_kannada_digits():
    assert normalise("ನನ್ನ ಆರ್ಡರ್‌ಗಳು? ೧೨೩!") == "ನನ್ನ ಆರ್ಡರ್ಗಳು 123"
    assert normalise("  Open   MARKET. ") == "open market"
