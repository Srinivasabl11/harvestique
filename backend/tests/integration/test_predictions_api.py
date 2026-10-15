"""Weather, harvest predictions (ranges, window, confidence, risk), versioning, changes, missing data."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.clock import FixedClock
from tests.conftest import FailingWeather, days_from_today, predict, relogin, today

pytestmark = pytest.mark.integration
API = "/api/v1"


# ----------------------------------------------------------------- weather


def test_farm_weather_returns_labelled_forecast_and_recent_days(db_client, farmer, geo_farm):
    r = db_client.get(f"{API}/farms/{geo_farm['id']}/weather", headers=farmer.headers, params={"days": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "fresh" and len(body["forecast"]) == 5 and body["recent"]
    assert {d["data_kind"] for d in body["forecast"]} == {"estimate"} and {d["data_kind"] for d in body["recent"]} == {
        "measured"
    }


def test_farm_without_coordinates_has_no_weather(db_client, farmer, farm):
    r = db_client.get(f"{API}/farms/{farm['id']}/weather", headers=farmer.headers)
    assert r.status_code == 422 and r.json()["error"]["code"] == "farm_location_missing"


def test_weather_outage_without_cache_is_unavailable(db_client, db_container, farmer, geo_farm):
    db_container.weather = FailingWeather()
    body = db_client.get(f"{API}/farms/{geo_farm['id']}/weather", headers=farmer.headers).json()
    assert body["status"] == "unavailable" and body["forecast"] == [] and "unavailable" in body["note"]


def test_weather_outage_with_cache_serves_stale_data(db_client, db_container, farmer, geo_farm, fixed_clock):
    assert db_client.get(f"{API}/farms/{geo_farm['id']}/weather", headers=farmer.headers).json()["status"] == "fresh"
    db_container.weather = FailingWeather()
    fixed_clock.advance_to(fixed_clock.now() + timedelta(hours=13))  # cache now older than the 12 h limit
    body = db_client.get(f"{API}/farms/{geo_farm['id']}/weather", headers=relogin(db_client)).json()
    assert body["status"] == "stale" and body["recent"]


def test_fresh_cache_avoids_refetching(db_client, db_container, farmer, geo_farm):
    db_client.get(f"{API}/farms/{geo_farm['id']}/weather", headers=farmer.headers)
    FailingWeather.calls = 0
    db_container.weather = FailingWeather()  # would fail if called
    assert db_client.get(f"{API}/farms/{geo_farm['id']}/weather", headers=farmer.headers).json()["status"] == "fresh"
    assert FailingWeather.calls == 0


# ------------------------------------------------------------- predictions


def test_prediction_has_ordered_quantiles_window_confidence_and_risk(db_client, farmer, growing):
    p = predict(db_client, farmer, growing["id"])
    q, t = p["quantity_kg"], p["timing"]
    assert p["status"] == "ok" and p["version"] == 1 and p["output_kind"] == "estimate"
    assert 0 <= q["p10"] <= q["p50"] <= q["p90"]
    assert t["start_p10"] < t["start_p50"] < t["start_p90"] < t["end_p90"]
    assert 0 <= p["confidence"]["score"] <= 100 and p["confidence"]["basis"] == "heuristic"
    assert {c["category"] for c in p["risk"]["categories"]} == {
        "weather",
        "disease",
        "water",
        "yield",
        "market",
        "demand",
        "labour",
        "timing",
        "fulfilment",
    }
    assert "does not guarantee" in p["disclaimer"] and p["explanations"] and p["weather_status"] == "fresh"
    assert {s["kind"] for s in p["sources"]} <= {"measured", "estimate", "assumption"}


def test_catalog_reference_drives_the_estimate(db_client, farmer, growing):
    p = predict(db_client, farmer, growing["id"])
    assert abs(p["yield_per_acre_kg"]["p50"] - 10000) < 3000  # reference 10,000 kg/acre, adjusted by weather
    assert any(s["name"] == "reference_yield" and s["kind"] == "assumption" and s["used"] for s in p["sources"])


def test_farmer_estimate_and_market_inputs(db_client, farmer, growing):
    body = {
        "farmer_estimate_per_acre": {"low": 6000, "expected": 7000, "high": 8000},
        "price_per_kg": {"low": 8, "expected": 12, "high": 18},
        "demand_quantity_kg": 5000,
        "labour_person_days_needed": 80,
        "labour_person_days_available": 100,
    }
    p = predict(db_client, farmer, growing["id"], body)
    cats = {c["category"]: c for c in p["risk"]["categories"]}
    assert all(cats[c]["score"] is not None for c in ("market", "demand", "labour"))
    assert any(s["name"] == "farmer_estimate" and s["used"] for s in p["sources"])


def test_unsupplied_risk_inputs_are_reported_as_insufficient_data(db_client, farmer, growing):
    cats = {c["category"]: c for c in predict(db_client, farmer, growing["id"])["risk"]["categories"]}
    assert cats["market"]["level"] == "insufficient_data" and cats["market"]["score"] is None


def test_insufficient_data_is_reported_honestly(db_client, api, farmer, admin, geo_plot):
    unknown = api.crop(admin, name="Exotic", typical_duration_days=90)  # no reference yield
    cycle = api.cycle(farmer, geo_plot["id"], unknown["id"], status="growing", area_acres=1)
    p = predict(db_client, farmer, cycle["id"])
    assert p["status"] == "insufficient_data" and p["quantity_kg"] is None and p["timing"]["start_p50"]
    assert any("No basis" in w for w in p["warnings"])
    with_estimate = predict(
        db_client, farmer, cycle["id"], {"farmer_estimate_per_acre": {"low": 1000, "expected": 1500, "high": 2000}}
    )
    assert with_estimate["status"] == "ok" and with_estimate["version"] == 2


def test_no_coordinates_still_predicts_with_wider_ranges(db_client, api, farmer, farm, ref_crop):
    plot = api.plot(farmer, farm["id"], name="No-geo plot", area_acres=4)
    no_geo = api.cycle(
        farmer,
        plot["id"],
        ref_crop["id"],
        status="growing",
        area_acres=2,
        sowing_date=days_from_today(-40),
        expected_harvest_date=days_from_today(60),
    )
    p = predict(db_client, farmer, no_geo["id"])
    assert p["weather_status"] == "unavailable" and p["status"] == "ok"
    assert any(w["name"] == "weather_unavailable" for w in p["widenings"])


def test_weather_outage_still_predicts(db_client, db_container, farmer, growing):
    db_container.weather = FailingWeather()
    p = predict(db_client, farmer, growing["id"])
    assert p["weather_status"] == "unavailable" and p["status"] == "ok" and p["warnings"]


@pytest.mark.parametrize(("change", "code"), [({"status": "abandoned"}, "cycle_abandoned")])
def test_closed_cycles_cannot_be_predicted(db_client, farmer, growing, change, code):
    db_client.patch(f"{API}/crop-cycles/{growing['id']}", headers=farmer.headers, json=change)
    r = db_client.post(f"{API}/crop-cycles/{growing['id']}/predictions", headers=farmer.headers, json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == code


def test_harvested_cycle_cannot_be_predicted(db_client, farmer, growing):
    db_client.patch(
        f"{API}/crop-cycles/{growing['id']}",
        headers=farmer.headers,
        json={"status": "harvested", "actual_harvest_date": days_from_today(-1)},
    )
    r = db_client.post(f"{API}/crop-cycles/{growing['id']}/predictions", headers=farmer.headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "cycle_harvested"


def test_invalid_prediction_request(db_client, farmer, growing):
    bad = {"farmer_estimate_per_acre": {"low": 9, "expected": 5, "high": 12}}
    assert (
        db_client.post(f"{API}/crop-cycles/{growing['id']}/predictions", headers=farmer.headers, json=bad).status_code
        == 422
    )
    assert (
        db_client.post(
            f"{API}/crop-cycles/{growing['id']}/predictions", headers=farmer.headers, json={"surprise": 1}
        ).status_code
        == 422
    )


# ------------------------------------------------------- versioning & changes


def test_predictions_are_versioned_and_never_overwritten(db_client, db_container, farmer, growing):
    v1 = predict(db_client, farmer, growing["id"])
    db_client.post(
        f"{API}/crop-cycles/{growing['id']}/observations",
        headers=farmer.headers,
        json={"observed_on": days_from_today(0), "health_status": "damaged", "estimated_loss_percent": 40},
    )
    v2 = predict(db_client, farmer, growing["id"])
    assert (v1["version"], v2["version"]) == (1, 2)
    assert v2["quantity_kg"]["p50"] < v1["quantity_kg"]["p50"]  # the observation lowered it
    assert v2["change"]["previous_version"] == 1 and v2["change"]["p50_change_pct"] < 0
    assert v1["change"] is None
    again = db_client.get(f"{API}/predictions/{v1['id']}", headers=farmer.headers).json()
    assert again == v1  # version 1 is untouched
    listing = db_client.get(f"{API}/crop-cycles/{growing['id']}/predictions", headers=farmer.headers).json()
    assert [p["version"] for p in listing["items"]] == [2, 1] and listing["total"] == 2
    with db_container.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM yield_predictions")) == 2


def test_recorded_history_is_used_for_later_predictions(db_client, api, farmer, geo_plot, ref_crop, growing):
    from tests.conftest import harvest

    old = api.cycle(
        farmer,
        geo_plot["id"],
        ref_crop["id"],
        status="growing",
        area_acres=1,
        sowing_date=days_from_today(-120),
        expected_harvest_date=days_from_today(-5),
    )
    harvest(db_client, farmer, old["id"], 6000)  # 6,000 kg/acre MEASURED on this farm
    p = predict(db_client, farmer, growing["id"])
    hist = next(s for s in p["sources"] if s["name"] == "farm_history")
    assert hist["used"] and hist["kind"] == "measured" and "1 recorded harvest" in hist["detail"]


def test_timing_uses_the_clock(db_client, farmer, growing, fixed_clock):
    early = predict(db_client, farmer, growing["id"])
    fixed_clock.advance_to(fixed_clock.now() + timedelta(days=30))
    later = predict(db_client, type(farmer)(relogin(db_client), farmer.user_id, farmer.role), growing["id"])
    assert later["timing"]["spread_days"] <= early["timing"]["spread_days"]  # less season left, less uncertainty


# ----------------------------------------------------------------- farm risk


def test_farm_risk_aggregates_open_cycles(db_client, api, farmer, geo_plot, ref_crop, growing, geo_farm):
    other = api.cycle(
        farmer, geo_plot["id"], ref_crop["id"], status="growing", area_acres=1, sowing_date=days_from_today(-20)
    )
    predict(db_client, farmer, growing["id"])
    predict(db_client, farmer, other["id"], {"price_per_kg": {"low": 2, "expected": 10, "high": 30}})
    body = db_client.get(f"{API}/farms/{geo_farm['id']}/risk", headers=farmer.headers).json()
    assert len(body["cycles"]) == 2 and body["overall_level"] in {"low", "medium", "high"}
    assert body["worst_by_category"]["market"] is not None and body["worst_by_category"]["labour"] is None


def test_farm_risk_without_predictions(db_client, farmer, geo_farm):
    body = db_client.get(f"{API}/farms/{geo_farm['id']}/risk", headers=farmer.headers).json()
    assert body["cycles"] == [] and body["overall_level"] == "insufficient_data"


# ------------------------------------------------------------------- planning


def test_prediction_feeds_a_plan(db_client, farmer, growing):
    p = predict(db_client, farmer, growing["id"])
    plan = db_client.post(
        f"{API}/crop-plans", headers=farmer.headers, json={"name": "From prediction", "available_land_acres": 10}
    ).json()
    r = db_client.post(
        f"{API}/crop-plans/{plan['id']}/items/from-prediction",
        headers=farmer.headers,
        json={"prediction_id": p["id"], "price_per_kg": {"low": 8, "expected": 12, "high": 18}},
    )
    assert r.status_code == 201, r.text
    item = r.json()
    y = p["yield_per_acre_kg"]
    assert item["yield_per_acre_kg"] == {"low": y["p10"], "expected": y["p50"], "high": y["p90"]}
    assert item["crop_id"] == growing["crop_id"] and item["area_acres"] == 2 and item["estimate_basis"] == "assumption"
    assert "From prediction v1" in item["notes"]
    evaluation = db_client.get(f"{API}/crop-plans/{plan['id']}/evaluation", headers=farmer.headers).json()
    assert evaluation["totals"]["revenue"]["expected"] > 0


def test_insufficient_prediction_cannot_feed_a_plan(db_client, api, farmer, admin, geo_plot):
    unknown = api.crop(admin, name="Exotic", typical_duration_days=90)
    cycle = api.cycle(farmer, geo_plot["id"], unknown["id"], status="growing", area_acres=1)
    p = predict(db_client, farmer, cycle["id"])
    plan = db_client.post(
        f"{API}/crop-plans", headers=farmer.headers, json={"name": "P", "available_land_acres": 5}
    ).json()
    r = db_client.post(
        f"{API}/crop-plans/{plan['id']}/items/from-prediction",
        headers=farmer.headers,
        json={"prediction_id": p["id"], "price_per_kg": {"low": 1, "expected": 2, "high": 3}},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "prediction_not_usable"


def test_cannot_use_someone_elses_prediction_in_a_plan(db_client, farmer, other_farmer, growing):
    p = predict(db_client, farmer, growing["id"])
    plan = db_client.post(
        f"{API}/crop-plans", headers=other_farmer.headers, json={"name": "P", "available_land_acres": 5}
    ).json()
    r = db_client.post(
        f"{API}/crop-plans/{plan['id']}/items/from-prediction",
        headers=other_farmer.headers,
        json={"prediction_id": p["id"], "price_per_kg": {"low": 1, "expected": 2, "high": 3}},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "prediction_not_found"


def test_fixed_clock_is_in_utc(fixed_clock):
    assert isinstance(fixed_clock, FixedClock) and fixed_clock.now().date() == today()
