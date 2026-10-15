# ruff: noqa: RUF001  (the answers use the real multiplication and minus signs)
"""Profit estimates with mandi prices (a scripted AGMARKNET feed), recorded expenses, actual harvests and break-even,
in English and Kannada. No network: the price provider is a test double."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.core.errors import ProviderUnavailableError
from app.providers.market.base import FakeMarketPrices, MandiPrice
from tests.conftest import days_from_today

pytestmark = pytest.mark.integration
API = "/api/v1"
TODAY = (datetime.now(UTC) + timedelta(hours=5, minutes=30)).date()


class NoModel:
    name = model = "none"

    def is_available(self) -> bool:
        return True

    def generate(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError(f"the model was asked: {request.messages[-1].content}")


class FailingPrices(FakeMarketPrices):
    def fetch(self, commodity, state):  # type: ignore[no-untyped-def]
        raise ProviderUnavailableError("down")


def mandi(district, market, days_ago, low, modal, high, state="Karnataka"):
    return MandiPrice(
        state, district, market, "Tomato", "Local", "FAQ", TODAY - timedelta(days=days_ago), D(low), D(modal), D(high)
    )


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


@pytest.fixture
def kolar_farm(api, farmer):
    return api.farm(farmer, name="Kolar Farm", district="Kolar", state="Karnataka", total_area_acres=3)


def ask(client, actor, text, lang="en", history=None):
    r = client.post(
        f"{API}/assistant/chat",
        headers=actor.headers,
        json={"message": text, "language": lang, "history": history or []},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_estimate_uses_the_latest_price_from_the_farms_district(db_container, db_client, farmer, tomato, kolar_farm):
    db_container.market_prices = FakeMarketPrices(
        [mandi("Kolar", "Kolar APMC", 0, 1000, 1500, 2000), mandi("Mysuru", "Mysuru APMC", 0, 3000, 3500, 4000)]
    )
    r = ask(db_client, farmer, "Estimate my profit from growing tomatoes on one acre, cost 60000")
    a = r["answer"]
    assert r["intent"] == "crop_estimate" and r["tool_calls"][0]["tool"] == "income_calculator", a
    assert "₹1,500 per quintal (modal; range ₹1,000–₹2,000) at Kolar APMC (Local), Kolar district" in a
    assert f"reported {TODAY.strftime('%d %b %Y')} (latest)" in a and "AGMARKNET (data.gov.in)" in a
    # catalogue harvest 6,500-13,500 kg (expected 10,000) x Rs 15/kg = Rs 1,50,000 expected; cost 60,000
    assert "₹1,50,000 − ₹60,000 = ₹90,000" in a
    assert "Break-even price: ₹6 per kg (₹600 per quintal)" in a and "Risks and assumptions" in a
    assert {s["name"] for s in r["sources"]} >= {
        "AGMARKNET mandi prices (data.gov.in)",
        "Catalogue reference yield (not your farm)",
    }
    again = ask(db_client, farmer, "Estimate my profit from growing tomatoes on one acre, cost 60000")
    assert again["answer"] == a and len(db_container.market_prices.calls) == 1  # stored; not fetched again


def test_kannada_answer_and_an_older_price_is_labelled(db_container, db_client, farmer, tomato, kolar_farm):
    db_container.market_prices = FakeMarketPrices([mandi("Kolar", "Kolar APMC", 9, 800, 1000, 1200)])
    r = ask(db_client, farmer, "ಒಂದು ಎಕರೆ ಟೊಮೆಟೊ ಲಾಭ ಎಷ್ಟು, ಖರ್ಚು 60000", lang="kn")
    a = r["answer"]
    assert r["language"] == "kn" and "ಕ್ವಿಂಟಾಲ್‌ಗೆ ₹1,000" in a and "9 ದಿನಗಳ ಹಿಂದಿನದು" in a
    assert "ನಷ್ಟವಿಲ್ಲದ ಕನಿಷ್ಠ ಬೆಲೆ" in a and "ಅಪಾಯಗಳು ಮತ್ತು ಊಹೆಗಳು" in a


def test_no_price_service_or_no_report_asks_for_the_price(db_container, db_client, farmer, tomato, kolar_farm):
    off = ask(db_client, farmer, "Estimate my profit from growing tomatoes on one acre, cost 60000")
    assert (
        "selling price per kg" in off["answer"]
        and "not switched on" in off["answer"]
        and "₹" not in off["answer"].split("Harvest I would use")[0].replace("₹60,000", "")
    )
    db_container.market_prices = FailingPrices()
    failed = ask(db_client, farmer, "Estimate my profit from growing tomatoes on one acre, cost 60000")
    assert "did not answer" in failed["answer"]
    db_container.market_prices = FakeMarketPrices([mandi("Moga", "Moga APMC", 0, 2500, 3000, 3200, state="Punjab")])
    none = ask(db_client, farmer, "Estimate my profit from growing tomatoes on one acre, cost 60000")
    assert "No Tomato price was reported" in none["answer"]  # a far-away state's price is not used


def test_actual_harvest_of_50_kg_is_used_as_harvested(db_container, db_client, farmer, tomato, kolar_farm):
    db_container.market_prices = FakeMarketPrices([mandi("Kolar", "Kolar APMC", 0, 1000, 1500, 2000)])
    r = ask(db_client, farmer, "I harvested only 50 kg of tomatoes from one acre, cost 20000. What is my profit?")
    a = r["answer"]
    assert "Harvest: 50 kg per acre (what you harvested)" in a and "50 kg × ₹15 per kg" in a
    assert "₹750 − ₹20,000 = −₹19,250 (a loss)" in a and "uses what you actually harvested" in a
    assert "Break-even price: ₹400 per kg" in a


def test_seed_quantity_is_clarified_not_used_as_harvest(db_client, farmer, tomato):
    for lang, text in (
        ("en", "profit from one acre of tomato, I used 50 kg of seed"),
        ("kn", "ಒಂದು ಎಕರೆ ಟೊಮೆಟೊ ಲಾಭ, 50 ಕೆಜಿ ಬೀಜ"),
    ):
        r = ask(db_client, farmer, text, lang=lang)
        assert r["intent"] == "crop_estimate" and r["tool_calls"] == [], text
        assert (
            ("seed, seedlings or fertiliser" in r["answer"]) if lang == "en" else ("ಬೀಜ, ಸಸಿ ಅಥವಾ ಗೊಬ್ಬರವೇ" in r["answer"])
        )


def test_recorded_expenses_are_used_as_the_cost(db_container, db_client, farmer, api, tomato, kolar_farm):
    plot = api.plot(farmer, kolar_farm["id"], area_acres=2)
    cycle = api.cycle(farmer, plot["id"], tomato["id"], area_acres=2)
    for amount in (30000, 50000):
        r = db_client.post(
            f"{API}/farms/{kolar_farm['id']}/expenses",
            headers=farmer.headers,
            json={
                "category": "seed",
                "amount": amount,
                "expense_date": days_from_today(-1),
                "crop_cycle_id": cycle["id"],
            },
        )
        assert r.status_code == 201, r.text
    db_container.market_prices = FakeMarketPrices([mandi("Kolar", "Kolar APMC", 0, 1000, 1500, 2000)])
    a = ask(db_client, farmer, "Estimate my profit from growing tomatoes on one acre")["answer"]
    # 80,000 recorded over 2 acres = 40,000 per acre
    assert "₹40,000 per acre × 1 acre(s) = ₹40,000 (your recorded expenses for this crop" in a and "2 entries" in a
    assert "₹1,50,000 − ₹40,000 = ₹1,10,000" in a


def test_a_failed_refresh_keeps_saying_so_until_retried(db_container, db_client, farmer, tomato, kolar_farm):
    db_container.market_prices = FailingPrices()
    for _ in range(2):  # the second question is within the retry window: still "did not answer", not "no report"
        a = ask(db_client, farmer, "Estimate my profit from growing tomatoes on one acre, cost 60000")["answer"]
        assert "did not answer" in a and "No Tomato price was reported" not in a


def test_the_client_identifies_itself():
    import httpx

    from app.providers.market.data_gov_in import USER_AGENT, DataGovInMarketPrices

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers["user-agent"]
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"records": []})

    provider = DataGovInMarketPrices(httpx.Client(transport=httpx.MockTransport(handler)), api_key="k")
    assert provider.fetch("Tomato", "Karnataka") == []
    assert seen["ua"] == USER_AGENT and seen["params"]["filters[commodity]"] == "Tomato"
    assert seen["params"]["filters[state.keyword]"] == "Karnataka"
