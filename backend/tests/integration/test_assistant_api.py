"""AI Farm Assistant (controlled tools), voice intents and crop-health uploads, on PostgreSQL."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from app.providers.llm.fake import DisabledLLMProvider, FakeLLMProvider
from app.providers.speech.device import FakeSpeech
from tests.conftest import days_from_today, make_demand, predict

pytestmark = pytest.mark.integration
API = "/api/v1"
WRITE_TOOLS = {"create_reminder", "record_expense"}


@pytest.fixture(autouse=True)
def no_llm(db_container):
    db_container.llm = DisabledLLMProvider()  # deterministic template answers unless a test opts in


def chat(client, actor, message, **kw):
    r = client.post(f"{API}/assistant/chat", headers=actor.headers, json={"message": message, **kw})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def grown(db_client, farmer, api, crop):
    farm = api.farm(farmer, latitude=12.3, longitude=76.64)
    plot = api.plot(farmer, farm["id"])
    cycle = api.cycle(farmer, plot["id"], crop["id"], status="growing", sowing_date=days_from_today(-40))
    pred = predict(
        db_client, farmer, cycle["id"], {"farmer_estimate_per_acre": {"low": 3000, "expected": 4000, "high": 5000}}
    )
    return {"farm": farm, "cycle": cycle, "prediction": pred}


# ------------------------------------------------------------------ tool set
def test_tool_catalogue_is_role_scoped_and_only_confirmed_tools_write(db_client, farmer, buyer, admin):
    names = {
        r: {t["name"]: t for t in db_client.get(f"{API}/assistant/tools", headers=a.headers).json()}
        for r, a in (("farmer", farmer), ("buyer", buyer), ("admin", admin))
    }
    assert "weather_summary" in names["farmer"] and "weather_summary" not in names["buyer"]
    assert "my_orders" in names["buyer"] and "my_orders" not in names["farmer"]
    every = {n: t for role in names.values() for n, t in role.items()}
    assert {n for n, t in every.items() if t["writes"]} == WRITE_TOOLS
    forbidden = ("pool", "allocat", "reserv", "order_create", "accept", "decline", "fulfil", "inventory_write")
    assert not [n for n in every if any(f in n for f in forbidden)]


def test_answers_come_from_the_callers_own_data(db_client, farmer, grown):
    r = chat(db_client, farmer, "How much will I harvest?")
    q = grown["prediction"]["quantity_kg"]
    assert r["intent"] == "harvest_prediction" and r["tool_calls"] == [
        {"tool": "harvest_prediction", "args": {}, "ok": True, "error_code": None}
    ]
    assert f"{q['p10']:g}" in r["answer"].replace(",", "") and "estimate, not a guarantee" in r["answer"]
    assert r["llm_used"] is False and r["disclaimer"].startswith("Advisory")
    assert {s["kind"] for s in r["sources"]} <= {"measured", "estimate", "assumption"}


def test_another_users_ids_are_not_reachable(db_client, farmer, other_farmer, grown):
    r = chat(db_client, other_farmer, "what is the weather", farm_id=grown["farm"]["id"])
    assert r["tool_calls"][0]["ok"] is False and r["tool_calls"][0]["error_code"] == "not_found"
    assert grown["farm"]["name"] not in r["answer"]
    r = chat(db_client, other_farmer, "harvest prediction", crop_cycle_id=grown["cycle"]["id"])
    assert r["tool_calls"][0]["error_code"] == "not_found" and "4000" not in r["answer"]
    direct = db_client.post(
        f"{API}/assistant/tools/weather_summary",
        headers=other_farmer.headers,
        json={"args": {"farm_id": grown["farm"]["id"]}},
    )
    assert direct.status_code == 404


def test_weather_tool_uses_the_weather_service(db_client, farmer, grown):
    r = chat(db_client, farmer, "weather this week?")
    assert r["intent"] == "weather" and r["tool_calls"][0]["ok"] and "mm" in r["answer"]
    assert {"Open-Meteo forecast", "Open-Meteo archive (reanalysis)"} == {s["name"] for s in r["sources"]}


def test_buyers_cannot_use_farmer_tools_and_get_their_own(db_client, buyer, pool_world):
    assert db_client.post(f"{API}/assistant/tools/weather_summary", headers=buyer.headers, json={}).status_code == 403
    r = chat(db_client, buyer, "show my orders")
    assert r["tool_calls"][0]["tool"] == "my_orders" and r["tool_calls"][0]["ok"]
    r = chat(db_client, buyer, "what supply do farmers have")
    assert r["tool_calls"][0]["tool"] == "market_supply" and "2000" in r["answer"]


def test_reminder_creation_needs_explicit_confirmation(db_client, farmer, grown):
    r = chat(db_client, farmer, "remind me to irrigate the tomato plot tomorrow at 6 am")
    assert r["requires_confirmation"] and r["proposed_action"]["tool"] == "create_reminder" and r["tool_calls"] == []
    assert db_client.get(f"{API}/reminders", headers=farmer.headers).json()["total"] == 0  # nothing written yet
    action = r["proposed_action"]
    unconfirmed = db_client.post(
        f"{API}/assistant/tools/create_reminder", headers=farmer.headers, json={"args": action["args"]}
    )
    assert unconfirmed.status_code == 409 and unconfirmed.json()["error"]["code"] == "confirmation_required"
    ok = db_client.post(
        f"{API}/assistant/tools/create_reminder", headers=farmer.headers, json={"args": action["args"], "confirm": True}
    )
    assert (
        ok.status_code == 200
        and ok.json()["data"]["source"] == "assistant"
        and ok.json()["data"]["reminder_type"] == "irrigation"
    )
    bad = db_client.post(
        f"{API}/assistant/tools/create_reminder",
        headers=farmer.headers,
        json={"args": {**action["args"], "sql": "DROP TABLE"}, "confirm": True},
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_tool_args"


def test_reminder_without_a_date_asks_instead_of_guessing(db_client, farmer):
    r = chat(db_client, farmer, "remind me to call the agronomist")
    assert not r["requires_confirmation"] and "When should I remind you" in r["answer"]


def test_allocation_requests_are_refused_and_change_nothing(db_client, farmer, buyer, pool_world, db_container):
    make_demand(db_client, buyer, pool_world.crop["id"], 100)
    before = pool_world.lot("A")
    r = chat(db_client, farmer, "allocate 500 kg of my tomato to the buyer")
    assert (
        r["intent"] == "allocation_request"
        and r["tool_calls"] == []
        and "can't decide or change allocation" in r["answer"]
    )
    assert pool_world.lot("A")["committed_kg"] == before["committed_kg"]
    assert (
        db_client.post(f"{API}/assistant/tools/allocate", headers=farmer.headers, json={"confirm": True}).status_code
        == 404
    )


def test_kannada_question_gets_a_kannada_answer(db_client, farmer, grown):
    r = chat(db_client, farmer, "ನನ್ನ ಕೊಯ್ಲು ಅಂದಾಜು ಎಷ್ಟು?")
    assert r["language"] == "kn" and r["intent"] == "harvest_prediction" and "ಕೆ.ಜಿ." in r["answer"]
    assert r["disclaimer"] == "ಇದು ಸಲಹೆ ಮಾತ್ರ. ನಿರ್ಧಾರ ನಿಮ್ಮದು."
    r = chat(db_client, farmer, "weather please", language="kn")
    assert r["language"] == "kn"


def test_llm_wording_is_used_only_when_grounded(db_container, db_client, farmer, grown, monkeypatch):
    monkeypatch.setattr(db_container.settings, "assistant_llm_rewording", True)  # off by default (slow on a CPU)
    q = grown["prediction"]["quantity_kg"]
    db_container.llm = FakeLLMProvider(reply=f"Your tomato should give between {q['p10']:g} and {q['p90']:g} kg.")
    r = chat(db_client, farmer, "how much will I harvest")
    assert r["llm_used"] is True and r["answer"].startswith("Your tomato")
    db_container.llm = FakeLLMProvider(reply="You will harvest 9999 kg and earn 30 rupees per kg.")  # invented numbers
    r = chat(db_client, farmer, "how much will I harvest")
    assert r["llm_used"] is False and "9999" not in r["answer"] and "rupees" not in r["answer"]


def test_opportunities_and_requests_tools(db_client, farmer, buyer, pool_world):
    make_demand(db_client, buyer, pool_world.crop["id"], 750)
    r = chat(db_client, farmer, "are there buyers for my crop?")
    assert r["tool_calls"][0]["tool"] == "buyer_opportunities" and "750" in r["answer"]
    r = chat(db_client, farmer, "do I have any supply requests")
    assert r["tool_calls"][0]["tool"] == "my_supply_requests" and r["answer"].startswith("0 supply requests")


# ---------------------------------------------------------------------- voice
def test_voice_uses_the_full_assistant_with_the_same_safety(db_client, farmer, grown):
    def voice(transcript, **kw):
        r = db_client.post(f"{API}/voice/intent", headers=farmer.headers, json={"transcript": transcript, **kw})
        assert r.status_code == 200, r.text
        return r.json()

    ok = voice("ನಾಳೆ ಮಳೆ ಬರುತ್ತದೆಯೇ", language="kn")
    assert ok["intent"] == "weather" and ok["language"] == "kn"
    assert voice("show my income plan profit")["intent"] == "income_plans"
    # a spoken write is only proposed; nothing is saved until the confirmed tool call
    spent = voice("I spent 500 rupees on fertilizer today")
    assert spent["requires_confirmation"] and spent["proposed_action"]["tool"] == "record_expense"
    farm_id = grown["farm"]["id"]
    assert db_client.get(f"{API}/farms/{farm_id}/expenses", headers=farmer.headers).json()["total"] == 0
    assert voice("allocate 300 kg to the pool")["intent"] == "allocation_request"


def test_server_speech_is_unavailable_by_default_and_validates_audio(db_container, db_client, farmer):
    wav = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 100
    r = db_client.post(
        f"{API}/voice/transcribe",
        headers=farmer.headers,
        files={"audio": ("a.wav", wav, "audio/wav")},
        data={"language": "kn"},
    )
    assert r.status_code == 503 and r.json()["error"]["code"] == "speech_on_device"
    assert (
        db_client.post(
            f"{API}/voice/speak", headers=farmer.headers, json={"text": "ನಮಸ್ಕಾರ", "language": "kn"}
        ).status_code
        == 503
    )
    db_container.speech = FakeSpeech("ನಾಳೆ ನೀರು ಹಾಕಲು ನೆನಪಿಸು")
    r = db_client.post(
        f"{API}/voice/transcribe",
        headers=farmer.headers,
        files={"audio": ("a.wav", wav, "audio/wav")},
        data={"language": "kn"},
    )
    assert r.status_code == 200 and r.json()["text"].startswith("ನಾಳೆ")
    spoofed = db_client.post(
        f"{API}/voice/transcribe",
        headers=farmer.headers,
        files={"audio": ("a.wav", b"MZ\x90\x00 not audio", "audio/wav")},
    )
    assert spoofed.status_code == 422 and spoofed.json()["error"]["code"] == "unsupported_file_type"
    big = db_client.post(
        f"{API}/voice/transcribe",
        headers=farmer.headers,
        files={"audio": ("a.wav", wav + b"\x00" * (2 * 1024 * 1024), "audio/wav")},
    )
    assert big.status_code == 422 and big.json()["error"]["code"] == "file_too_large"
    speech = db_client.post(f"{API}/voice/speak", headers=farmer.headers, json={"text": "hello", "language": "en"})
    assert speech.status_code == 200 and speech.headers["content-type"] == "audio/wav"


# --------------------------------------------------------------- crop health
def photo(colour=(50, 140, 40), fmt="JPEG", n=256) -> bytes:
    rng = np.random.default_rng(1)
    a = np.clip(np.full((n, n, 3), colour, dtype=np.float64) + rng.normal(0, 25, (n, n, 3)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(a).save(buf, format=fmt)
    return buf.getvalue()


def test_crop_health_upload_is_advisory_and_owner_scoped(db_client, farmer, other_farmer, buyer, grown):
    files = {"image": ("leaf.jpg", photo(), "image/jpeg")}
    r = db_client.post(
        f"{API}/crop-health/analyze",
        headers=farmer.headers,
        files=files,
        data={"crop_cycle_id": grown["cycle"]["id"], "language": "kn"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # the colour check gives measurements only (its labels were wrong on real photos), never a health label
    assert body["label"] == "unknown" and max(body["probabilities"].values()) <= 0.7 and body["data_kind"] == "estimate"
    assert body["features"]["mode"] == "measurements_only" and body["features"]["green"] > 0.9
    assert "not a diagnosis" in body["disclaimer"] and "NOT been validated" in body["disclaimer"]
    assert any("ಀ" <= ch <= "೿" for ch in body["explanation"])
    # the structured report: no condition score without an AI model, said in the farmer's language
    report = body["features"]["analysis"]
    assert report["condition"]["score"] is None and report["condition"]["withheld_reason"] == "no_ai"
    assert report["language"] == "kn" and any("ಀ" <= ch <= "೿" for ch in report["condition"]["text"])
    assert sum(round(100 * v) for v in body["probabilities"].values()) == 100
    hist = db_client.get(
        f"{API}/crop-health/analyses", headers=farmer.headers, params={"crop_cycle_id": grown["cycle"]["id"]}
    ).json()
    assert len(hist) == 1 and hist[0]["id"] == body["id"]
    other = db_client.post(
        f"{API}/crop-health/analyze",
        headers=other_farmer.headers,
        files={"image": ("l.jpg", photo(), "image/jpeg")},
        data={"crop_cycle_id": grown["cycle"]["id"]},
    )
    assert other.status_code == 404
    assert db_client.post(f"{API}/crop-health/analyze", headers=buyer.headers, files=files).status_code == 403


@pytest.mark.parametrize(
    ("filename", "content", "ctype", "code"),
    [
        ("x.jpg", b"%PDF-1.7 pretending", "image/jpeg", "unsupported_file_type"),
        ("x.png", b"\x89PNG\r\n\x1a\n" + b"junk" * 50, "image/png", "invalid_image"),
        ("x.jpg", b"", "image/jpeg", "empty_file"),
        ("x.gif", b"GIF89a" + b"\x00" * 64, "image/gif", "unsupported_file_type"),
    ],
)
def test_crop_health_rejects_unsafe_files(db_client, farmer, filename, content, ctype, code):
    r = db_client.post(
        f"{API}/crop-health/analyze", headers=farmer.headers, files={"image": (filename, content, ctype)}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == code


def test_crop_health_rejects_oversized_uploads_before_decoding(db_client, farmer):
    r = db_client.post(
        f"{API}/crop-health/analyze",
        headers=farmer.headers,
        files={"image": ("x.jpg", b"\xff\xd8\xff" + b"\x00" * (6 * 1024 * 1024), "image/jpeg")},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "file_too_large"


def test_photos_are_not_stored(db_container, db_client, farmer):
    db_client.post(
        f"{API}/crop-health/analyze",
        headers=farmer.headers,
        files={"image": ("leaf.png", photo(fmt="PNG"), "image/png")},
    )
    from sqlalchemy import text

    with db_container.engine.connect() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'crop_health_analyses'")
            )
        }
    assert "image_sha256" in cols and not cols & {"image", "image_bytes", "data", "content"}


# ------------------------------------------------------- remaining tool paths
def test_empty_states_say_so_instead_of_inventing(db_client, farmer, api, crop):
    assert "not added a farm" in chat(db_client, farmer, "weather today")["answer"]
    assert "no planned or growing crop" in chat(db_client, farmer, "harvest prediction")["answer"]
    farm = api.farm(farmer)  # no coordinates
    plot = api.plot(farmer, farm["id"])
    api.cycle(farmer, plot["id"], crop["id"], status="growing")
    assert "no harvest prediction yet" in chat(db_client, farmer, "harvest prediction")["answer"]
    r = chat(db_client, farmer, "weather today")
    assert "no location set" in r["answer"]  # no coordinates: says so, no numbers
    assert "cannot be assessed yet" in chat(db_client, farmer, "what is my risk")["answer"]


def test_insufficient_data_prediction_is_reported_honestly(db_client, farmer, api, crop):
    farm = api.farm(farmer)
    plot = api.plot(farmer, farm["id"])
    cycle = api.cycle(farmer, plot["id"], crop["id"], status="growing")
    predict(db_client, farmer, cycle["id"])  # no estimate, no reference yield, no history
    assert "not enough data" in chat(db_client, farmer, "how much will I harvest")["answer"]


def test_latest_prediction_version_is_used(db_client, farmer, grown):
    predict(
        db_client,
        farmer,
        grown["cycle"]["id"],
        {"farmer_estimate_per_acre": {"low": 1000, "expected": 1200, "high": 1400}},
    )
    page = db_client.get(f"{API}/crop-cycles/{grown['cycle']['id']}/predictions", headers=farmer.headers).json()
    latest = max(page["items"], key=lambda p: p["version"])
    assert latest["version"] == 2
    r = chat(db_client, farmer, "how much will I harvest")
    assert latest["quantity_kg"]["p10"] < grown["prediction"]["quantity_kg"]["p10"]  # v2 really differs from v1
    assert f"{round(latest['quantity_kg']['p10'], 1):g}" in r["answer"]


def test_risk_inventory_reminders_and_plans_tools(db_client, farmer, grown):
    r = chat(db_client, farmer, "what is my farm risk")
    assert r["tool_calls"][0]["tool"] == "farm_risk" and "/100" in r["answer"]
    r = chat(db_client, farmer, "how much stock is available")
    assert r["tool_calls"][0]["tool"] == "inventory_summary" and "1 lots" in r["answer"]
    db_client.post(
        f"{API}/reminders",
        headers=farmer.headers,
        json={"reminder_type": "custom", "title": "Sell onions", "due_at": "2030-01-01T09:00:00+05:30"},
    )
    r = chat(db_client, farmer, "show my reminders")
    assert r["tool_calls"][0]["tool"] == "list_reminders" and "Sell onions" in r["answer"]
    db_client.post(f"{API}/crop-plans", headers=farmer.headers, json={"name": "Kharif plan", "available_land_acres": 2})
    r = chat(db_client, farmer, "show my income plans")
    assert r["tool_calls"][0]["tool"] == "income_plans" and "Kharif plan" in r["answer"]


def test_help_unknown_and_wrong_role_paths(db_client, farmer, buyer, admin):
    assert "I can tell you about weather" in chat(db_client, farmer, "help")["answer"]
    assert chat(db_client, farmer, "zzzz")["intent"] == "unknown"
    r = chat(db_client, buyer, "what is the weather")
    assert (
        r["tool_calls"][0]["error_code"] == "permission_denied" and "not available for your account type" in r["answer"]
    )
    r = chat(db_client, admin, "what supply do farmers have")
    assert r["tool_calls"][0]["tool"] == "market_supply" and r["tool_calls"][0]["ok"]


def test_a_failing_service_gives_a_safe_answer(db_client, farmer, grown, monkeypatch):
    from app.core.errors import ProviderUnavailableError
    from app.services.weather import WeatherService

    def down(*a, **k):
        raise ProviderUnavailableError("weather down")

    monkeypatch.setattr(WeatherService, "farm_weather", down)
    r = chat(db_client, farmer, "weather today")
    assert r["tool_calls"][0] == {
        "tool": "weather_summary",
        "args": {"day": "today"},  # "weather today" asks for that day
        "ok": False,
        "error_code": "provider_unavailable",
    }
    assert "could not get that information" in r["answer"]


def test_llm_failure_falls_back_to_the_template(db_container, db_client, farmer, grown):
    from app.core.errors import ProviderUnavailableError

    class Broken(FakeLLMProvider):
        def generate(self, request):  # type: ignore[no-untyped-def]
            raise ProviderUnavailableError("down")

    db_container.llm = Broken()
    r = chat(db_client, farmer, "how much will I harvest")
    assert r["llm_used"] is False and "estimate, not a guarantee" in r["answer"]


def test_past_reminder_time_is_not_proposed(db_client, farmer):
    r = chat(db_client, farmer, "remind me to sell tomatoes on 2020-01-01")
    assert not r["requires_confirmation"]
