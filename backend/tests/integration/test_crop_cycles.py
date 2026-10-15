"""Crop cycles: relationships, dates, status machine and plot-capacity rules."""

from __future__ import annotations

import pytest

from tests.conftest import days_from_today as d

pytestmark = pytest.mark.integration


def plot_cycles(plot_id: str) -> str:
    return f"/api/v1/plots/{plot_id}/crop-cycles"


def cycle_url(cycle_id: str) -> str:
    return f"/api/v1/crop-cycles/{cycle_id}"


def code(response) -> str:
    return response.json()["error"]["code"]


# ------------------------------------------------------------------- create


def test_create_cycle_defaults(db_client, farmer, plot, crop):
    r = db_client.post(
        plot_cycles(plot["id"]),
        headers=farmer.headers,
        json={"crop_id": crop["id"], "sowing_date": d(-5), "variety": "Arka Rakshak"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "planned"
    assert body["area_acres"] == plot["area_acres"]  # defaults to the whole plot
    assert body["crop_id"] == crop["id"] and body["crop_name"] == "Tomato" and body["variety"] == "Arka Rakshak"
    assert body["expected_harvest_date"] is None and body["actual_harvest_date"] is None


def test_create_growing_cycle_on_part_of_the_plot(api, farmer, plot, crop):
    c = api.cycle(farmer, plot["id"], crop["id"], status="growing", area_acres=1.5)
    assert c["status"] == "growing" and c["area_acres"] == 1.5


def test_backfill_a_harvested_cycle(api, farmer, plot, crop):
    c = api.cycle(
        farmer,
        plot["id"],
        crop["id"],
        status="harvested",
        sowing_date=d(-120),
        expected_harvest_date=d(-30),
        actual_harvest_date=d(-28),
    )
    assert c["status"] == "harvested" and c["actual_harvest_date"] == d(-28)


def test_planned_cycle_may_start_in_the_future(api, farmer, plot, crop):
    assert (
        api.cycle(farmer, plot["id"], crop["id"], sowing_date=d(30), expected_harvest_date=d(130))["status"]
        == "planned"
    )


# ------------------------------------------------------- crop relationships


def test_unknown_crop_is_rejected(db_client, farmer, plot):
    r = db_client.post(
        plot_cycles(plot["id"]),
        headers=farmer.headers,
        json={"crop_id": "7d6e2b7a-8f3a-4c43-9b8a-0a3a7a0d5a11", "sowing_date": d(-1)},
    )
    assert r.status_code == 422 and code(r) == "crop_not_found" and r.json()["error"]["details"]["field"] == "crop_id"


def test_inactive_crop_cannot_start_new_cycles(db_client, farmer, admin, plot, crop):
    db_client.patch(f"/api/v1/crops/{crop['id']}", headers=admin.headers, json={"is_active": False})
    r = db_client.post(
        plot_cycles(plot["id"]), headers=farmer.headers, json={"crop_id": crop["id"], "sowing_date": d(-1)}
    )
    assert r.status_code == 422 and code(r) == "crop_inactive"


def test_existing_cycles_survive_their_crop_being_deactivated(db_client, farmer, admin, crop, cycle):
    db_client.patch(f"/api/v1/crops/{crop['id']}", headers=admin.headers, json={"is_active": False})
    assert db_client.get(cycle_url(cycle["id"]), headers=farmer.headers).json()["crop_name"] == "Tomato"


def test_cycle_cannot_start_abandoned(db_client, farmer, plot, crop):
    r = db_client.post(
        plot_cycles(plot["id"]),
        headers=farmer.headers,
        json={"crop_id": crop["id"], "sowing_date": d(-1), "status": "abandoned"},
    )
    assert r.status_code == 422 and code(r) == "invalid_initial_status"


def test_archived_plot_does_not_accept_cycles(db_client, farmer, plot, crop):
    db_client.patch(f"/api/v1/plots/{plot['id']}", headers=farmer.headers, json={"is_active": False})
    r = db_client.post(
        plot_cycles(plot["id"]), headers=farmer.headers, json={"crop_id": crop["id"], "sowing_date": d(-1)}
    )
    assert r.status_code == 409 and code(r) == "plot_archived"


def test_archived_farm_does_not_accept_cycles(db_client, farmer, farm, plot, crop):
    db_client.patch(f"/api/v1/farms/{farm['id']}", headers=farmer.headers, json={"is_active": False})
    r = db_client.post(
        plot_cycles(plot["id"]), headers=farmer.headers, json={"crop_id": crop["id"], "sowing_date": d(-1)}
    )
    assert r.status_code == 409 and code(r) == "plot_archived"


@pytest.mark.parametrize(
    "extra",
    [
        {"area_acres": 0},
        {"area_acres": -1},
        {"area_acres": 1.2345},
        {"status": "flowering"},
        {"plot_id": "x"},
        {"sowing_date": "yesterday"},
    ],
)
def test_invalid_cycle_payloads(db_client, farmer, plot, crop, extra):
    body = {"crop_id": crop["id"], "sowing_date": d(-1), **extra}
    assert db_client.post(plot_cycles(plot["id"]), headers=farmer.headers, json=body).status_code == 422


def test_sowing_date_and_crop_are_required(db_client, farmer, plot, crop):
    assert (
        db_client.post(plot_cycles(plot["id"]), headers=farmer.headers, json={"crop_id": crop["id"]}).status_code == 422
    )
    assert (
        db_client.post(plot_cycles(plot["id"]), headers=farmer.headers, json={"sowing_date": d(-1)}).status_code == 422
    )


# --------------------------------------------------------------------- dates


@pytest.mark.parametrize(
    ("body", "error_code"),
    [
        ({"sowing_date": d(-5), "expected_harvest_date": d(-5)}, "expected_harvest_before_sowing"),
        ({"sowing_date": d(-5), "expected_harvest_date": d(-9)}, "expected_harvest_before_sowing"),
        ({"status": "harvested", "sowing_date": d(-50)}, "actual_harvest_date_required"),
        ({"status": "harvested", "sowing_date": d(-50), "actual_harvest_date": d(-60)}, "actual_harvest_before_sowing"),
        ({"status": "harvested", "sowing_date": d(-50), "actual_harvest_date": d(10)}, "actual_harvest_in_future"),
        ({"status": "growing", "sowing_date": d(-5), "actual_harvest_date": d(-1)}, "actual_harvest_date_not_allowed"),
        ({"status": "planned", "sowing_date": d(-5), "actual_harvest_date": d(-1)}, "actual_harvest_date_not_allowed"),
        ({"status": "growing", "sowing_date": d(10)}, "sowing_date_in_future"),
        ({"status": "harvested", "sowing_date": d(10), "actual_harvest_date": d(10)}, "sowing_date_in_future"),
    ],
)
def test_date_rules(db_client, farmer, plot, crop, body, error_code):
    r = db_client.post(plot_cycles(plot["id"]), headers=farmer.headers, json={"crop_id": crop["id"], **body})
    assert r.status_code == 422 and code(r) == error_code


# ----------------------------------------------------------------- capacity


def test_cycle_cannot_be_larger_than_its_plot(db_client, farmer, plot, crop):
    r = db_client.post(
        plot_cycles(plot["id"]),
        headers=farmer.headers,
        json={"crop_id": crop["id"], "sowing_date": d(-1), "area_acres": 4.001},
    )
    assert r.status_code == 422 and code(r) == "cycle_area_exceeds_plot"


def test_overlapping_cycles_cannot_exceed_the_plot(db_client, api, farmer, plot, crop):
    api.cycle(farmer, plot["id"], crop["id"], area_acres=3)  # sown 10 days ago, harvest in 80 days
    r = db_client.post(
        plot_cycles(plot["id"]),
        headers=farmer.headers,
        json={"crop_id": crop["id"], "sowing_date": d(0), "expected_harvest_date": d(60), "area_acres": 1.5},
    )
    assert r.status_code == 422 and code(r) == "plot_capacity_exceeded"
    details = r.json()["error"]["details"]
    assert details["plot_area_acres"] == 4 and details["peak_area_acres"] == 4.5
    ok = db_client.post(
        plot_cycles(plot["id"]),
        headers=farmer.headers,
        json={"crop_id": crop["id"], "sowing_date": d(0), "expected_harvest_date": d(60), "area_acres": 1},
    )
    assert ok.status_code == 201  # intercropping: 3 + 1 = exactly the plot's 4 acres


def test_sequential_cycles_can_reuse_the_same_land(api, farmer, plot, crop):
    first = api.cycle(farmer, plot["id"], crop["id"], sowing_date=d(-100), expected_harvest_date=d(-20))
    second = api.cycle(farmer, plot["id"], crop["id"], sowing_date=d(-19), expected_harvest_date=d(60))
    assert first["area_acres"] == second["area_acres"] == 4  # both occupy the full plot, at different times


def test_harvest_day_itself_is_still_occupied(db_client, api, farmer, plot, crop):
    api.cycle(farmer, plot["id"], crop["id"], sowing_date=d(-100), expected_harvest_date=d(-20))
    r = db_client.post(
        plot_cycles(plot["id"]),
        headers=farmer.headers,
        json={"crop_id": crop["id"], "sowing_date": d(-20), "expected_harvest_date": d(50)},
    )
    assert r.status_code == 422 and code(r) == "plot_capacity_exceeded"  # shares the harvest day


def test_duration_comes_from_the_crop_when_no_harvest_date_given(db_client, api, farmer, admin, plot):
    short = api.crop(admin, name="Radish", typical_duration_days=30)
    api.cycle(farmer, plot["id"], short["id"], sowing_date=d(-40), expected_harvest_date=None)  # occupied d-40..d-10
    nxt = db_client.post(
        plot_cycles(plot["id"]), headers=farmer.headers, json={"crop_id": short["id"], "sowing_date": d(-9)}
    )
    assert nxt.status_code == 201
    clash = db_client.post(
        plot_cycles(plot["id"]), headers=farmer.headers, json={"crop_id": short["id"], "sowing_date": d(-15)}
    )
    assert clash.status_code == 422 and code(clash) == "plot_capacity_exceeded"


def test_abandoned_cycles_release_their_land(db_client, api, farmer, plot, crop):
    first = api.cycle(farmer, plot["id"], crop["id"], status="growing")
    clash = {"crop_id": crop["id"], "sowing_date": d(-5), "expected_harvest_date": d(60)}
    assert db_client.post(plot_cycles(plot["id"]), headers=farmer.headers, json=clash).status_code == 422
    assert (
        db_client.patch(cycle_url(first["id"]), headers=farmer.headers, json={"status": "abandoned"}).status_code == 200
    )
    assert db_client.post(plot_cycles(plot["id"]), headers=farmer.headers, json=clash).status_code == 201


def test_capacity_is_per_plot(api, farmer, farm, plot, crop):
    other = api.plot(farmer, farm["id"], name="Other", area_acres=4)
    api.cycle(farmer, plot["id"], crop["id"])
    assert api.cycle(farmer, other["id"], crop["id"])["plot_id"] == other["id"]


# ---------------------------------------------------------------- ownership


def test_cannot_use_someone_elses_plot(db_client, plot, crop, other_farmer):
    r = db_client.post(
        plot_cycles(plot["id"]), headers=other_farmer.headers, json={"crop_id": crop["id"], "sowing_date": d(-1)}
    )
    assert r.status_code == 404
    assert db_client.get(plot_cycles(plot["id"]), headers=other_farmer.headers).status_code == 404


def test_cannot_read_edit_or_delete_someone_elses_cycle(db_client, cycle, other_farmer):
    url = cycle_url(cycle["id"])
    assert db_client.get(url, headers=other_farmer.headers).status_code == 404
    assert db_client.patch(url, headers=other_farmer.headers, json={"notes": "x"}).status_code == 404
    assert db_client.delete(url, headers=other_farmer.headers).status_code == 404


def test_cannot_list_cycles_of_someone_elses_farm(db_client, farm, cycle, other_farmer):
    assert db_client.get(f"/api/v1/farms/{farm['id']}/crop-cycles", headers=other_farmer.headers).status_code == 404


# --------------------------------------------------------------------- read


def test_list_cycles_by_plot_and_farm(db_client, api, farmer, farm, plot, crop):
    other_plot = api.plot(farmer, farm["id"], name="Other", area_acres=2)
    old = api.cycle(
        farmer,
        plot["id"],
        crop["id"],
        sowing_date=d(-200),
        expected_harvest_date=d(-100),
        status="harvested",
        actual_harvest_date=d(-100),
    )
    new = api.cycle(farmer, plot["id"], crop["id"], sowing_date=d(-10), expected_harvest_date=d(80), status="growing")
    elsewhere = api.cycle(farmer, other_plot["id"], crop["id"])

    on_plot = db_client.get(plot_cycles(plot["id"]), headers=farmer.headers).json()
    assert [c["id"] for c in on_plot["items"]] == [new["id"], old["id"]]  # newest sowing first
    on_farm = db_client.get(f"/api/v1/farms/{farm['id']}/crop-cycles", headers=farmer.headers).json()
    assert on_farm["total"] == 3 and elsewhere["id"] in {c["id"] for c in on_farm["items"]}
    growing = db_client.get(plot_cycles(plot["id"]), headers=farmer.headers, params={"status": "growing"}).json()
    assert [c["id"] for c in growing["items"]] == [new["id"]]
    assert db_client.get(plot_cycles(plot["id"]), headers=farmer.headers, params={"status": "bogus"}).status_code == 422


# ----------------------------------------------------------- status machine


def test_planned_to_growing_to_harvested(db_client, farmer, cycle):
    url = cycle_url(cycle["id"])
    grow = db_client.patch(url, headers=farmer.headers, json={"status": "growing"})
    assert grow.status_code == 200 and grow.json()["status"] == "growing"
    done = db_client.patch(url, headers=farmer.headers, json={"status": "harvested", "actual_harvest_date": d(-1)})
    assert done.status_code == 200
    assert done.json()["status"] == "harvested" and done.json()["actual_harvest_date"] == d(-1)


@pytest.mark.parametrize("target", ["harvested"])
def test_cannot_skip_growing(db_client, farmer, cycle, target):
    r = db_client.patch(
        cycle_url(cycle["id"]), headers=farmer.headers, json={"status": target, "actual_harvest_date": d(-1)}
    )
    assert r.status_code == 409 and code(r) == "invalid_status_transition"


def test_cannot_go_back_to_planned(db_client, farmer, cycle):
    db_client.patch(cycle_url(cycle["id"]), headers=farmer.headers, json={"status": "growing"})
    r = db_client.patch(cycle_url(cycle["id"]), headers=farmer.headers, json={"status": "planned"})
    assert r.status_code == 409 and code(r) == "invalid_status_transition"


def test_harvesting_needs_a_valid_actual_date(db_client, farmer, cycle):
    url = cycle_url(cycle["id"])
    db_client.patch(url, headers=farmer.headers, json={"status": "growing"})
    missing = db_client.patch(url, headers=farmer.headers, json={"status": "harvested"})
    assert missing.status_code == 422 and code(missing) == "actual_harvest_date_required"
    early = db_client.patch(url, headers=farmer.headers, json={"status": "harvested", "actual_harvest_date": d(-30)})
    assert early.status_code == 422 and code(early) == "actual_harvest_before_sowing"
    assert db_client.get(url, headers=farmer.headers).json()["status"] == "growing"  # failed attempts changed nothing


@pytest.mark.parametrize("final", ["harvested", "abandoned"])
def test_closed_cycles_are_read_only(db_client, farmer, cycle, final):
    url = cycle_url(cycle["id"])
    db_client.patch(url, headers=farmer.headers, json={"status": "growing"})
    close = {"status": final, **({"actual_harvest_date": d(-1)} if final == "harvested" else {})}
    assert db_client.patch(url, headers=farmer.headers, json=close).status_code == 200
    for body in ({"notes": "edit"}, {"status": "growing"}, {"area_acres": 1}):
        r = db_client.patch(url, headers=farmer.headers, json=body)
        assert r.status_code == 409 and code(r) == "cycle_closed", body


def test_planned_cycle_can_be_abandoned(db_client, farmer, cycle):
    assert (
        db_client.patch(cycle_url(cycle["id"]), headers=farmer.headers, json={"status": "abandoned"}).json()["status"]
        == "abandoned"
    )


# ------------------------------------------------------------------- update


def test_update_fields(db_client, farmer, cycle):
    r = db_client.patch(
        cycle_url(cycle["id"]),
        headers=farmer.headers,
        json={"variety": "Local", "area_acres": 2, "expected_harvest_date": d(70), "notes": "Late sowing"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["variety"] == "Local" and body["area_acres"] == 2 and body["expected_harvest_date"] == d(70)
    assert body["crop_id"] == cycle["crop_id"] and body["sowing_date"] == cycle["sowing_date"]


def test_update_revalidates_dates_together(db_client, farmer, cycle):
    url = cycle_url(cycle["id"])
    r = db_client.patch(url, headers=farmer.headers, json={"sowing_date": d(90)})  # after the existing expected harvest
    assert r.status_code == 422 and code(r) == "expected_harvest_before_sowing"
    ok = db_client.patch(url, headers=farmer.headers, json={"sowing_date": d(90), "expected_harvest_date": d(180)})
    assert ok.status_code == 200
    cleared = db_client.patch(url, headers=farmer.headers, json={"expected_harvest_date": None})
    assert cleared.status_code == 200 and cleared.json()["expected_harvest_date"] is None


def test_update_revalidates_capacity_without_counting_itself(db_client, api, farmer, plot, crop):
    full = api.cycle(farmer, plot["id"], crop["id"])  # whole plot (4 acres)
    assert db_client.patch(cycle_url(full["id"]), headers=farmer.headers, json={"area_acres": 4}).status_code == 200
    assert db_client.patch(cycle_url(full["id"]), headers=farmer.headers, json={"area_acres": 4.5}).status_code == 422


def test_growing_a_cycle_into_a_neighbour_is_rejected(db_client, api, farmer, plot, crop):
    api.cycle(farmer, plot["id"], crop["id"], area_acres=2)
    other = api.cycle(farmer, plot["id"], crop["id"], area_acres=1)
    r = db_client.patch(cycle_url(other["id"]), headers=farmer.headers, json={"area_acres": 2.5})
    assert r.status_code == 422 and code(r) == "plot_capacity_exceeded"


@pytest.mark.parametrize("field", ["status", "area_acres", "sowing_date"])
def test_required_cycle_fields_cannot_be_nulled(db_client, farmer, cycle, field):
    assert db_client.patch(cycle_url(cycle["id"]), headers=farmer.headers, json={field: None}).status_code == 422


@pytest.mark.parametrize(
    "immutable",
    [{"crop_id": "7d6e2b7a-8f3a-4c43-9b8a-0a3a7a0d5a11"}, {"plot_id": "7d6e2b7a-8f3a-4c43-9b8a-0a3a7a0d5a11"}],
)
def test_crop_and_plot_are_immutable(db_client, farmer, cycle, immutable):
    assert db_client.patch(cycle_url(cycle["id"]), headers=farmer.headers, json=immutable).status_code == 422


# ------------------------------------------------------------------- delete


def test_delete_cycle(db_client, farmer, cycle):
    assert db_client.delete(cycle_url(cycle["id"]), headers=farmer.headers).status_code == 204
    assert db_client.get(cycle_url(cycle["id"]), headers=farmer.headers).status_code == 404


@pytest.mark.parametrize("record", ["observation", "expense", "activity"])
def test_cycle_with_records_cannot_be_deleted(db_client, api, farmer, farm, cycle, record):
    if record == "observation":
        api.observation(farmer, cycle["id"])
    elif record == "expense":
        api.expense(farmer, farm["id"], crop_cycle_id=cycle["id"])
    else:
        api.activity(farmer, farm["id"], crop_cycle_id=cycle["id"])
    r = db_client.delete(cycle_url(cycle["id"]), headers=farmer.headers)
    assert r.status_code == 409 and code(r) == "cycle_not_empty"
    assert db_client.get(cycle_url(cycle["id"]), headers=farmer.headers).status_code == 200
