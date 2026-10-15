"""Prediction feedback (predicted vs actual) and calibration from recorded outcomes."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import days_from_today, harvest, predict

pytestmark = pytest.mark.integration
API = "/api/v1"


def test_actual_requires_a_harvested_cycle(db_client, farmer, growing):
    r = db_client.post(
        f"{API}/crop-cycles/{growing['id']}/harvest-actual", headers=farmer.headers, json={"quantity_kg": 100}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "cycle_not_harvested"


def test_feedback_scores_every_prediction_version(db_client, farmer, growing):
    v1 = predict(db_client, farmer, growing["id"])
    v2 = predict(
        db_client, farmer, growing["id"], {"farmer_estimate_per_acre": {"low": 6000, "expected": 7000, "high": 8000}}
    )
    report = harvest(db_client, farmer, growing["id"], 15000)
    assert report["actual"]["quantity_kg"] == 15000 and report["actual"]["data_kind"] == "measured"
    rows = {f["prediction_version"]: f for f in report["feedback"]}
    assert set(rows) == {1, 2}
    for version, pred in ((1, v1), (2, v2)):
        q, f = pred["quantity_kg"], rows[version]
        assert f["signed_error_kg"] == pytest.approx(15000 - q["p50"], abs=0.001)
        assert f["abs_pct_error"] == pytest.approx(abs(15000 - q["p50"]) / 15000 * 100, abs=0.01)
        assert f["within_interval"] is (q["p10"] <= 15000 <= q["p90"])
    assert db_client.get(f"{API}/crop-cycles/{growing['id']}/feedback", headers=farmer.headers).json() == report


def test_date_feedback_uses_the_given_harvest_start(db_client, farmer, growing):
    p = predict(db_client, farmer, growing["id"])
    db_client.patch(
        f"{API}/crop-cycles/{growing['id']}",
        headers=farmer.headers,
        json={"status": "harvested", "actual_harvest_date": days_from_today(-1)},
    )
    r = db_client.post(
        f"{API}/crop-cycles/{growing['id']}/harvest-actual",
        headers=farmer.headers,
        json={"quantity_kg": 9000, "harvest_start_date": days_from_today(-3)},
    )
    from datetime import date

    expected = (date.fromisoformat(days_from_today(-3)) - date.fromisoformat(p["timing"]["start_p50"])).days
    assert r.json()["feedback"][0]["date_error_days"] == expected


def test_actual_is_recorded_once(db_client, farmer, growing):
    harvest(db_client, farmer, growing["id"], 1000)
    r = db_client.post(
        f"{API}/crop-cycles/{growing['id']}/harvest-actual", headers=farmer.headers, json={"quantity_kg": 2000}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "actual_already_recorded"


@pytest.mark.parametrize("body", [{"quantity_kg": -1}, {"quantity_kg": "lots"}, {}, {"quantity_kg": 1, "extra": 1}])
def test_invalid_actuals(db_client, farmer, growing, body):
    db_client.patch(
        f"{API}/crop-cycles/{growing['id']}",
        headers=farmer.headers,
        json={"status": "harvested", "actual_harvest_date": days_from_today(-1)},
    )
    assert (
        db_client.post(
            f"{API}/crop-cycles/{growing['id']}/harvest-actual", headers=farmer.headers, json=body
        ).status_code
        == 422
    )


def test_zero_harvest_is_a_valid_measurement(db_client, farmer, growing):
    predict(db_client, farmer, growing["id"])
    report = harvest(db_client, farmer, growing["id"], 0)
    assert report["feedback"][0]["abs_pct_error"] is None and report["feedback"][0]["within_interval"] is False


def test_feedback_without_actual(db_client, farmer, growing):
    body = db_client.get(f"{API}/crop-cycles/{growing['id']}/feedback", headers=farmer.headers).json()
    assert body["actual"] is None and body["feedback"] == [] and "No harvest" in body["note"]


# -------------------------------------------------------------- calibration


def run_season(db_client, api, farmer, plot, crop, actual):
    c = api.cycle(farmer, plot["id"], crop["id"], status="growing", area_acres=0.5, sowing_date=days_from_today(-40))
    predict(db_client, farmer, c["id"])
    harvest(db_client, farmer, c["id"], actual)
    return c


def profiles(db_client, actor):
    return {p["scope"]: p for p in db_client.get(f"{API}/calibration", headers=actor.headers).json()}


def test_calibration_is_not_applied_until_enough_outcomes_exist(db_client, api, farmer, geo_plot, ref_crop):
    for _ in range(4):
        run_season(db_client, api, farmer, geo_plot, ref_crop, 4000)
    prof = profiles(db_client, farmer)
    assert prof["global"]["sample_size"] == 4 and prof["global"]["sufficient"] is False
    assert prof["global"]["bias_factor"] == 1 and prof["global"]["interval_scale"] == 1
    nxt = api.cycle(
        farmer, geo_plot["id"], ref_crop["id"], status="growing", area_acres=0.5, sowing_date=days_from_today(-40)
    )
    p = predict(db_client, farmer, nxt["id"])
    assert p["confidence"]["basis"] == "heuristic" and p["calibration_profile_id"] is None
    assert "not a measured accuracy" in p["confidence"]["calibration_note"]


def test_calibration_applies_once_sufficient_and_is_versioned(db_client, db_container, api, farmer, geo_plot, ref_crop):
    for _ in range(5):
        run_season(db_client, api, farmer, geo_plot, ref_crop, 4000)
    prof = profiles(db_client, farmer)
    crop_scope = f"crop:{ref_crop['id']}"
    assert (
        prof[crop_scope]["sufficient"] is True
        and prof[crop_scope]["sample_size"] == 5
        and prof[crop_scope]["version"] == 5
    )
    assert prof[crop_scope]["bias_factor"] < 1  # actual ~8,000/acre vs higher predictions
    nxt = api.cycle(
        farmer, geo_plot["id"], ref_crop["id"], status="growing", area_acres=0.5, sowing_date=days_from_today(-40)
    )
    p = predict(db_client, farmer, nxt["id"])
    assert p["confidence"]["basis"] == "calibrated" and p["calibration_profile_id"] == prof[crop_scope]["id"]
    assert any(f["name"] == "calibration_bias" for f in p["factors"])
    with db_container.engine.connect() as conn:  # never overwritten: one row per recompute
        assert conn.scalar(text("SELECT count(*) FROM calibration_profiles WHERE scope = :s"), {"s": crop_scope}) == 5


def test_admin_recompute_appends_new_profiles(db_client, api, farmer, admin, geo_plot, ref_crop):
    run_season(db_client, api, farmer, geo_plot, ref_crop, 5000)
    before = profiles(db_client, farmer)["global"]["version"]
    r = db_client.post(f"{API}/admin/calibration/recompute", headers=admin.headers)
    assert r.status_code == 200
    assert profiles(db_client, farmer)["global"]["version"] == before + 1
    assert db_client.post(f"{API}/admin/calibration/recompute", headers=farmer.headers).status_code == 403


def test_calibration_is_empty_without_outcomes(db_client, buyer):
    assert db_client.get(f"{API}/calibration", headers=buyer.headers).json() == []
