"""What each number in an estimate message means: stated meanings are used, anything else is 'unclear' (asked)."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.domain.assistant.estimate import conversation_inputs, has_numbers, inr, parse


def test_the_phone_example_numbers_are_unclear_not_guessed():
    for text in ("For example 20 kg and ₹50,000", "ಉದಾಹರಣೆಗೆ 20 ಕೆಜಿ ಮತ್ತು 50,000 ರೂಪಾಯಿ"):
        p = parse(text)
        assert [(u.kind, u.text) for u in p.unclear] == [
            ("mass", "20 " + ("kg" if "kg" in text else "ಕೆಜಿ")),
            ("money", "₹50,000"),
        ]
        assert p.harvest_kg is p.cost is p.income is p.price_per_kg is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "price 10 rupees per kg, cost 30000 per acre",
            {"price_per_kg": D(10), "cost": D(30000), "cost_scope": "acre"},
        ),
        ("ಕೆಜಿಗೆ 10 ರೂಪಾಯಿ, ಎಕರೆಗೆ 30000 ಖರ್ಚು", {"price_per_kg": D(10), "cost": D(30000), "cost_scope": "acre"}),
        ("₹2000 per quintal", {"price_per_kg": D(20)}),
        ("yield 20 quintal per acre", {"harvest_kg": D(2000), "harvest_scope": "acre"}),
        ("ಇಳುವರಿ ೮೦೦೦ ಕೆಜಿ, ಖರ್ಚು 50 ಸಾವಿರ", {"harvest_kg": D(8000), "cost": D(50000)}),
        (
            "2 acres, total cost 1.5 lakh, income 3 lakh",
            {"acres": D(2), "cost": D(150000), "cost_scope": "total", "income": D(300000)},
        ),
        ("Rs 1,20,000 income per acre", {"income": D(120000), "income_scope": "acre"}),
        ("harvest 2 tonnes", {"harvest_kg": D(2000)}),
        ("10 guntas", {"acres": D("0.25")}),
        ("one acre of tomato", {"acres": D(1)}),
        ("ಒಂದು ಎಕರೆ ಟೊಮೆಟೊ", {"acres": D(1)}),
        ("20 kg is the harvest and 50000 is the cost", {"harvest_kg": D(20), "cost": D(50000)}),
    ],
)
def test_stated_meanings_units_and_number_formats(text, expected):
    p = parse(text)
    assert p.unclear == []
    for name, value in expected.items():
        assert getattr(p, name) == value, (text, name, getattr(p, name))


@pytest.mark.parametrize("text", ["price 20 rupees", "50000", "₹50,000", "20 kg"])
def test_a_number_without_its_meaning_or_unit_is_unclear(text):
    assert parse(text).unclear  # "price 20 rupees": per kg or per quintal? asked, not assumed


def test_follow_ups_merge_and_the_latest_correction_wins():
    merged = conversation_inputs(["one acre of tomato, price 20 rupees per kg", "cost 40000", "no, the cost is 45000"])
    assert (merged.acres, merged.price_per_kg, merged.cost) == (D(1), D(20), D(45000))
    resolved = conversation_inputs(["For example 20 kg and ₹50,000", "20 kg is the harvest and 50000 is the cost"])
    assert resolved.unclear == [] and (resolved.harvest_kg, resolved.cost) == (D(20), D(50000))


def test_helpers():
    assert inr(D(120000)) == "1,20,000" and inr(D("12.50")) == "12.5" and inr(D(-5000)) == "-5,000"
    assert has_numbers("ಖರ್ಚು ೫೦೦೦") and not has_numbers("what is crop rotation")
