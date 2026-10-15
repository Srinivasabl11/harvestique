"""Plot CRUD, ownership and the plot-vs-farm area rules."""

from __future__ import annotations

import contextlib
import threading
import uuid

import pytest

from app.composition import build_plot_service
from app.core.errors import DomainValidationError
from app.repositories.farms import PlotRepository
from app.schemas.farms import PlotCreate

pytestmark = pytest.mark.integration


def plots_url(farm_id: str) -> str:
    return f"/api/v1/farms/{farm_id}/plots"


def plot_url(plot_id: str) -> str:
    return f"/api/v1/plots/{plot_id}"


# ------------------------------------------------------------------- create


def test_create_plot(db_client, farmer, farm):
    r = db_client.post(
        plots_url(farm["id"]),
        headers=farmer.headers,
        json={
            "name": "Lower Field",
            "area_acres": 2.75,
            "soil_type": "red",
            "irrigation_type": "drip",
            "notes": "Sandy",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["farm_id"] == farm["id"] and body["area_acres"] == 2.75
    assert body["soil_type"] == "red" and body["irrigation_type"] == "drip" and body["is_active"] is True


def test_plot_area_equal_to_farm_area_is_allowed(api, farmer, farm):
    assert api.plot(farmer, farm["id"], area_acres=10)["area_acres"] == 10


def test_plot_larger_than_farm_is_rejected(db_client, farmer, farm):
    r = db_client.post(plots_url(farm["id"]), headers=farmer.headers, json={"name": "Big", "area_acres": 10.001})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "plot_area_exceeds_farm" and err["details"]["farm_area_acres"] == 10


def test_all_plots_together_cannot_exceed_the_farm(db_client, api, farmer, farm):
    api.plot(farmer, farm["id"], name="A", area_acres=6)
    r = db_client.post(plots_url(farm["id"]), headers=farmer.headers, json={"name": "B", "area_acres": 4.5})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "plots_exceed_farm_area" and err["details"]["other_plots_area_acres"] == 6
    assert api.plot(farmer, farm["id"], name="B", area_acres=4)["area_acres"] == 4  # exactly fills the farm
    full = db_client.post(plots_url(farm["id"]), headers=farmer.headers, json={"name": "C", "area_acres": 0.001})
    assert full.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"name": "P", "area_acres": 0},
        {"name": "P", "area_acres": -1},
        {"name": "P", "area_acres": 1.2345},
        {"name": "P"},
        {"area_acres": 1},
        {"name": "P", "area_acres": 1, "soil_type": "moon-dust"},
        {"name": "P", "area_acres": 1, "irrigation_type": "magic"},
        {"name": "P", "area_acres": 1, "farm_id": "7d6e2b7a-8f3a-4c43-9b8a-0a3a7a0d5a11"},
    ],
)
def test_invalid_plot_payloads(db_client, farmer, farm, body):
    assert db_client.post(plots_url(farm["id"]), headers=farmer.headers, json=body).status_code == 422


def test_plot_names_are_unique_within_a_farm_only(db_client, api, farmer, farm):
    api.plot(farmer, farm["id"], name="North", area_acres=1)
    r = db_client.post(plots_url(farm["id"]), headers=farmer.headers, json={"name": "NORTH", "area_acres": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "plot_name_taken"
    second_farm = api.farm(farmer, name="Second Farm")
    assert api.plot(farmer, second_farm["id"], name="North", area_acres=1)["id"]


def test_archived_farm_does_not_accept_new_plots(db_client, farmer, farm):
    db_client.patch(f"/api/v1/farms/{farm['id']}", headers=farmer.headers, json={"is_active": False})
    r = db_client.post(plots_url(farm["id"]), headers=farmer.headers, json={"name": "P", "area_acres": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "farm_archived"


# ---------------------------------------------------------------- ownership


def test_cannot_create_or_list_plots_on_someone_elses_farm(db_client, farm, other_farmer):
    assert (
        db_client.post(
            plots_url(farm["id"]), headers=other_farmer.headers, json={"name": "P", "area_acres": 1}
        ).status_code
        == 404
    )
    assert db_client.get(plots_url(farm["id"]), headers=other_farmer.headers).status_code == 404


def test_cannot_read_edit_or_delete_someone_elses_plot(db_client, plot, other_farmer):
    url = plot_url(plot["id"])
    assert db_client.get(url, headers=other_farmer.headers).status_code == 404
    assert db_client.patch(url, headers=other_farmer.headers, json={"name": "Mine now"}).status_code == 404
    assert db_client.delete(url, headers=other_farmer.headers).status_code == 404


# --------------------------------------------------------------------- read


def test_list_and_get(db_client, api, farmer, farm):
    b = api.plot(farmer, farm["id"], name="b", area_acres=1)
    a = api.plot(farmer, farm["id"], name="A", area_acres=1)
    listing = db_client.get(plots_url(farm["id"]), headers=farmer.headers).json()
    assert [p["name"] for p in listing["items"]] == ["A", "b"] and listing["total"] == 2
    assert db_client.get(plot_url(a["id"]), headers=farmer.headers).json() == a
    assert db_client.get(plot_url(b["id"]), headers=farmer.headers).json()["name"] == "b"


def test_archived_plots_hidden_unless_requested(db_client, farmer, farm, plot):
    db_client.patch(plot_url(plot["id"]), headers=farmer.headers, json={"is_active": False})
    assert db_client.get(plots_url(farm["id"]), headers=farmer.headers).json()["total"] == 0
    assert (
        db_client.get(plots_url(farm["id"]), headers=farmer.headers, params={"include_archived": True}).json()["total"]
        == 1
    )


# ------------------------------------------------------------------- update


def test_update_plot(db_client, farmer, plot):
    r = db_client.patch(
        plot_url(plot["id"]), headers=farmer.headers, json={"soil_type": "black", "notes": "Cotton soil"}
    )
    assert r.status_code == 200 and r.json()["soil_type"] == "black" and r.json()["name"] == "North Field"
    cleared = db_client.patch(plot_url(plot["id"]), headers=farmer.headers, json={"soil_type": None})
    assert cleared.json()["soil_type"] is None


@pytest.mark.parametrize("field", ["name", "area_acres", "is_active"])
def test_required_plot_fields_cannot_be_nulled(db_client, farmer, plot, field):
    assert db_client.patch(plot_url(plot["id"]), headers=farmer.headers, json={field: None}).status_code == 422


def test_plot_cannot_move_to_another_farm(db_client, farmer, plot):
    r = db_client.patch(plot_url(plot["id"]), headers=farmer.headers, json={"farm_id": str(uuid.uuid4())})
    assert r.status_code == 422


def test_growing_a_plot_respects_farm_capacity(db_client, api, farmer, farm, plot):
    api.plot(farmer, farm["id"], name="Other", area_acres=5)  # 4 + 5 = 9 of 10 acres used
    assert db_client.patch(plot_url(plot["id"]), headers=farmer.headers, json={"area_acres": 5}).status_code == 200
    r = db_client.patch(plot_url(plot["id"]), headers=farmer.headers, json={"area_acres": 5.001})
    assert r.status_code == 422 and r.json()["error"]["code"] == "plots_exceed_farm_area"


def test_resaving_the_same_area_does_not_count_the_plot_twice(db_client, api, farmer, farm):
    full = api.plot(farmer, farm["id"], area_acres=10)  # fills the whole farm
    assert db_client.patch(plot_url(full["id"]), headers=farmer.headers, json={"area_acres": 10}).status_code == 200


def test_plot_cannot_shrink_below_the_land_its_cycles_use(db_client, api, farmer, plot, crop):
    api.cycle(farmer, plot["id"], crop["id"], area_acres=3)  # 3 of the plot's 4 acres in use
    r = db_client.patch(plot_url(plot["id"]), headers=farmer.headers, json={"area_acres": 2.5})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "plot_area_below_cycles" and err["details"]["peak_cycle_area_acres"] == 3
    assert db_client.patch(plot_url(plot["id"]), headers=farmer.headers, json={"area_acres": 3}).status_code == 200


def test_rename_conflict(db_client, api, farmer, farm, plot):
    api.plot(farmer, farm["id"], name="Other", area_acres=1)
    r = db_client.patch(plot_url(plot["id"]), headers=farmer.headers, json={"name": "other"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "plot_name_taken"


# ------------------------------------------------------------------- delete


def test_delete_empty_plot(db_client, farmer, plot):
    assert db_client.delete(plot_url(plot["id"]), headers=farmer.headers).status_code == 204
    assert db_client.get(plot_url(plot["id"]), headers=farmer.headers).status_code == 404


def test_plot_with_crop_cycles_cannot_be_deleted(db_client, farmer, plot, cycle):
    r = db_client.delete(plot_url(plot["id"]), headers=farmer.headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "plot_not_empty"
    assert db_client.get(plot_url(plot["id"]), headers=farmer.headers).status_code == 200


def test_plot_with_activities_cannot_be_deleted(db_client, api, farmer, farm, plot):
    api.activity(farmer, farm["id"], plot_id=plot["id"])
    assert db_client.delete(plot_url(plot["id"]), headers=farmer.headers).status_code == 409


# -------------------------------------------------------------- concurrency


def test_concurrent_plot_creation_cannot_oversubscribe_the_farm(db_container, db_client, farmer, farm, monkeypatch):
    """Two requests that each fit alone but not together: exactly one must win.

    Both threads are held at the area-accounting step until the other arrives (barrier). Without the
    farm row lock both would read 'nothing allocated yet' and both would succeed; with it the second
    blocks on the lock, the barrier times out for the first, and the second then sees the first's plot.
    """
    barrier = threading.Barrier(2, timeout=1.5)
    original = PlotRepository.total_area

    def total_area_after_rendezvous(self, farm_id, *, exclude_id=None):  # type: ignore[no-untyped-def]
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait()
        return original(self, farm_id, exclude_id=exclude_id)

    monkeypatch.setattr(PlotRepository, "total_area", total_area_after_rendezvous)
    results: dict[str, str] = {}

    def create(name: str) -> None:
        with db_container.session_factory() as session:
            try:
                build_plot_service(session).create(
                    uuid.UUID(farmer.user_id), uuid.UUID(farm["id"]), PlotCreate(name=name, area_acres=6)
                )
                results[name] = "created"
            except DomainValidationError as exc:
                results[name] = exc.code

    threads = [threading.Thread(target=create, args=(n,)) for n in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert sorted(results.values()) == ["created", "plots_exceed_farm_area"], results
    listing = db_client.get(plots_url(farm["id"]), headers=farmer.headers).json()
    assert listing["total"] == 1 and listing["items"][0]["area_acres"] == 6
