"""Choosing a mandi price (district -> state -> nearby states; latest day; median over markets; max age) and reading
data.gov.in records. Pure functions, no network."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

from app.domain.assistant.estimate import parse
from app.domain.market import MAX_AGE_DAYS, choose_quote, commodity_names
from app.providers.market.base import MandiPrice
from app.providers.market.data_gov_in import parse_record

TODAY = date(2026, 10, 14)


def rec(state, district, market, day, low, modal, high, commodity="Tomato"):
    return MandiPrice(state, district, market, commodity, "Local", "FAQ", day, D(low), D(modal), D(high))


def test_the_farms_district_wins_and_the_latest_day_is_used():
    rows = [
        rec("Karnataka", "Kolar", "Kolar APMC", TODAY - timedelta(days=2), 1000, 1200, 1500),
        rec("Karnataka", "Kolar", "Kolar APMC", TODAY - timedelta(days=5), 800, 900, 1000),
        rec("Karnataka", "Mysuru", "Mysuru APMC", TODAY, 2000, 2200, 2400),
    ]
    q = choose_quote(rows, state="Karnataka", district="Kolar", today=TODAY)
    assert q is not None and q.scope == "district" and q.markets == ("Kolar APMC",)
    assert (q.arrival_date, q.age_days, q.fresh) == (TODAY - timedelta(days=2), 2, True)
    assert q.per_kg() == (D(10), D(12), D(15))  # INR per quintal / 100


def test_state_median_then_nearby_states_and_no_stale_reports():
    rows = [
        rec("Karnataka", "Mysuru", "A", TODAY, 1000, 1000, 1000),
        rec("Karnataka", "Hassan", "B", TODAY, 2000, 3000, 4000),
        rec("Karnataka", "Tumakuru", "C", TODAY, 1500, 2000, 2500),
    ]
    q = choose_quote(rows, state="Karnataka", district="Kolar", today=TODAY)
    assert q is not None and q.scope == "state" and q.modal_per_quintal == 2000 and len(q.markets) == 3
    nearby = [rec("Tamil Nadu", "Krishnagiri", "Hosur", TODAY - timedelta(days=10), 900, 1100, 1300)]
    q = choose_quote(nearby, state="Karnataka", district="Kolar", today=TODAY)
    assert q is not None and q.scope == "nearby" and q.place == "Tamil Nadu" and not q.fresh and q.age_days == 10
    old = [rec("Karnataka", "Kolar", "Kolar APMC", TODAY - timedelta(days=MAX_AGE_DAYS + 1), 1, 1, 1)]
    assert choose_quote(old, state="Karnataka", district="Kolar", today=TODAY) is None
    far = [rec("Punjab", "Moga", "Moga APMC", TODAY, 2500, 3000, 3200)]
    assert choose_quote(far, state="Karnataka", district=None, today=TODAY) is None  # not a nearby market


def test_api_records_are_read_or_skipped_never_guessed():
    good = {
        "state": "Karnataka",
        "district": "Bagalkot",
        "market": "Hungund APMC",
        "commodity": "Maize",
        "variety": "Local",
        "grade": "FAQ",
        "arrival_date": "14/10/2026",
        "min_price": 2450,
        "max_price": 2500,
        "modal_price": 2450,
    }
    p = parse_record(good)
    assert p is not None and p.arrival_date == TODAY and (p.min_price, p.modal_price, p.max_price) == (2450, 2450, 2500)
    assert parse_record({**good, "arrival_date": "2026-10-14"}) is None
    assert parse_record({**good, "modal_price": "NA"}) is None
    assert parse_record({**good, "min_price": 3000}) is None  # min above modal: malformed
    assert commodity_names("Ragi") == ("Ragi (Finger Millet)",) and commodity_names("Tomato") == ("Tomato",)


def test_an_actual_harvest_is_not_a_yield_and_inputs_are_not_harvests():
    p = parse("I harvested only 50 kg of tomatoes from one acre")
    assert p.harvest_kg == 50 and p.harvest_actual and p.harvest_scope == "total" and p.acres == 1
    k = parse("ಒಂದು ಎಕರೆಯಲ್ಲಿ 50 ಕೆಜಿ ಟೊಮೆಟೊ ಮಾತ್ರ ಸಿಕ್ಕಿತು")
    assert k.harvest_kg == 50 and k.harvest_actual
    for text in ("I used 50 kg of seed", "50 kg fertilizer", "50 ಕೆಜಿ ಬೀಜ"):
        assert [u.kind for u in parse(text).unclear] == ["input"], text


def test_one_variety_is_priced_never_a_mix_of_specialty_and_ordinary_produce():
    rows = [
        MandiPrice("Karnataka", "Bagalkot", "Hungund APMC", "Maize", "Local", "FAQ", TODAY, D(2450), D(2450), D(2500)),
        MandiPrice(
            "Karnataka", "Bagalkot", "Hungund APMC", "Maize", "Popcorn", "FAQ", TODAY, D(4700), D(4700), D(4700)
        ),
    ]
    q = choose_quote(rows, state="Karnataka", district=None, today=TODAY)
    assert q is not None and q.variety == "Local" and q.modal_per_quintal == 2450  # not the 3,575 median of both
    q = choose_quote(rows[1:], state="Karnataka", district=None, today=TODAY)
    assert q is not None and q.variety == "Popcorn"  # the only report: used, and named
