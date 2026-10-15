"""Farm CRUD, ownership and validation."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration
URL = "/api/v1/farms"


# ------------------------------------------------------------------- create


def test_create_farm(db_client, farmer):
    r = db_client.post(
        URL,
        headers=farmer.headers,
        json={
            "name": "Hunsur Farm",
            "village": "Hunsur",
            "district": "Mysuru",
            "state": "Karnataka",
            "latitude": 12.3052,
            "longitude": 76.6551,
            "total_area_acres": 12.5,
            "notes": "Red soil",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Hunsur Farm" and body["total_area_acres"] == 12.5  # JSON number
    assert body["latitude"] == 12.3052 and body["is_active"] is True
    assert body["id"] and body["created_at"]
    assert "owner_id" not in body  # ownership is implicit, never exposed or client-supplied


def test_minimal_farm(db_client, farmer):
    r = db_client.post(URL, headers=farmer.headers, json={"name": "Small", "total_area_acres": 0.25})
    assert r.status_code == 201 and r.json()["village"] is None and r.json()["latitude"] is None


def test_farm_is_owned_by_the_caller(db_client, api, farmer, other_farmer):
    farm = api.farm(farmer)
    mine = db_client.get(URL, headers=farmer.headers).json()
    theirs = db_client.get(URL, headers=other_farmer.headers).json()
    assert [f["id"] for f in mine["items"]] == [farm["id"]] and theirs["total"] == 0


def test_cannot_set_owner_via_payload(db_client, farmer, other_farmer):
    r = db_client.post(
        URL, headers=farmer.headers, json={"name": "X", "total_area_acres": 1, "owner_id": other_farmer.user_id}
    )
    assert r.status_code == 422


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"total_area_acres": 0}, "total_area_acres"),
        ({"total_area_acres": -3}, "total_area_acres"),
        ({"total_area_acres": 1.2345}, "total_area_acres"),  # more than 3 decimal places
        ({"total_area_acres": "lots"}, "total_area_acres"),
        ({"total_area_acres": None}, "total_area_acres"),
        ({"name": ""}, "name"),
        ({"name": "x" * 121}, "name"),
        ({"latitude": 91, "longitude": 10}, "latitude"),
        ({"latitude": 10, "longitude": -181}, "longitude"),
    ],
)
def test_invalid_farm_payloads(db_client, farmer, override, field):
    r = db_client.post(URL, headers=farmer.headers, json={"name": "Farm", "total_area_acres": 5, **override})
    assert r.status_code == 422
    assert field in {e["field"] for e in r.json()["error"]["details"]["errors"]}


def test_missing_required_fields(db_client, farmer):
    r = db_client.post(URL, headers=farmer.headers, json={})
    assert {e["field"] for e in r.json()["error"]["details"]["errors"]} == {"name", "total_area_acres"}


def test_latitude_and_longitude_must_come_together(db_client, farmer):
    r = db_client.post(URL, headers=farmer.headers, json={"name": "F", "total_area_acres": 1, "latitude": 12.3})
    assert r.status_code == 422


def test_duplicate_name_per_farmer(db_client, api, farmer, other_farmer):
    api.farm(farmer, name="Green Acres")
    r = db_client.post(URL, headers=farmer.headers, json={"name": "green acres", "total_area_acres": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "farm_name_taken"
    assert api.farm(other_farmer, name="Green Acres")["id"]  # another farmer may reuse the name


# --------------------------------------------------------------------- read


def test_get_farm(db_client, farmer, farm):
    r = db_client.get(f"{URL}/{farm['id']}", headers=farmer.headers)
    assert r.status_code == 200 and r.json() == farm


def test_list_orders_by_name_and_paginates(db_client, api, farmer):
    for name in ("Charlie", "alpha", "Bravo"):
        api.farm(farmer, name=name)
    page = db_client.get(URL, headers=farmer.headers, params={"limit": 2}).json()
    assert [f["name"] for f in page["items"]] == ["alpha", "Bravo"] and page["total"] == 3
    rest = db_client.get(URL, headers=farmer.headers, params={"limit": 2, "offset": 2}).json()
    assert [f["name"] for f in rest["items"]] == ["Charlie"]


def test_unknown_and_malformed_ids(db_client, farmer):
    assert db_client.get(f"{URL}/7d6e2b7a-8f3a-4c43-9b8a-0a3a7a0d5a11", headers=farmer.headers).status_code == 404
    assert db_client.get(f"{URL}/nope", headers=farmer.headers).status_code == 422


# ------------------------------------------------------------------ ownership


def test_other_farmers_cannot_see_or_touch_my_farm(db_client, farm, other_farmer):
    url = f"{URL}/{farm['id']}"
    for method, kwargs in (("get", {}), ("patch", {"json": {"name": "Hacked"}}), ("delete", {})):
        r = getattr(db_client, method)(url, headers=other_farmer.headers, **kwargs)
        assert r.status_code == 404, method  # 404, not 403: existence is not revealed
        assert r.json()["error"]["code"] == "not_found"


def test_failed_attack_leaves_farm_unchanged(db_client, farmer, farm, other_farmer):
    db_client.patch(f"{URL}/{farm['id']}", headers=other_farmer.headers, json={"name": "Hacked"})
    db_client.delete(f"{URL}/{farm['id']}", headers=other_farmer.headers)
    assert db_client.get(f"{URL}/{farm['id']}", headers=farmer.headers).json()["name"] == "Green Acres"


# ------------------------------------------------------------------- update


def test_partial_update(db_client, farmer, farm):
    r = db_client.patch(
        f"{URL}/{farm['id']}", headers=farmer.headers, json={"village": "Hunsur", "total_area_acres": 20}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["village"] == "Hunsur" and body["total_area_acres"] == 20 and body["name"] == "Green Acres"
    assert body["updated_at"] >= farm["updated_at"]


def test_clear_nullable_field(db_client, api, farmer):
    farm = api.farm(farmer, village="Hunsur")
    r = db_client.patch(f"{URL}/{farm['id']}", headers=farmer.headers, json={"village": None})
    assert r.json()["village"] is None


@pytest.mark.parametrize("field", ["name", "total_area_acres", "is_active"])
def test_required_fields_cannot_be_nulled(db_client, farmer, farm, field):
    assert db_client.patch(f"{URL}/{farm['id']}", headers=farmer.headers, json={field: None}).status_code == 422


def test_rename_conflict(db_client, api, farmer, farm):
    api.farm(farmer, name="Second")
    assert db_client.patch(f"{URL}/{farm['id']}", headers=farmer.headers, json={"name": "second"}).status_code == 409
    assert (
        db_client.patch(f"{URL}/{farm['id']}", headers=farmer.headers, json={"name": "GREEN ACRES"}).status_code == 200
    )


def test_setting_only_one_coordinate_is_rejected(db_client, farmer, farm):
    r = db_client.patch(f"{URL}/{farm['id']}", headers=farmer.headers, json={"latitude": 12.3})
    assert r.status_code == 422 and r.json()["error"]["code"] == "coordinates_incomplete"
    ok = db_client.patch(f"{URL}/{farm['id']}", headers=farmer.headers, json={"latitude": 12.3, "longitude": 76.6})
    assert ok.status_code == 200 and ok.json()["longitude"] == 76.6


def test_farm_cannot_shrink_below_its_plots(db_client, api, farmer, farm):
    api.plot(farmer, farm["id"], name="A", area_acres=6)
    api.plot(farmer, farm["id"], name="B", area_acres=3)
    r = db_client.patch(f"{URL}/{farm['id']}", headers=farmer.headers, json={"total_area_acres": 8})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "farm_area_below_plots" and err["details"]["plotted_area_acres"] == 9
    assert (
        db_client.patch(f"{URL}/{farm['id']}", headers=farmer.headers, json={"total_area_acres": 9}).status_code == 200
    )


# --------------------------------------------------------- archive / delete


def test_archive_hides_farm_from_default_listing(db_client, farmer, farm):
    db_client.patch(f"{URL}/{farm['id']}", headers=farmer.headers, json={"is_active": False})
    assert db_client.get(URL, headers=farmer.headers).json()["total"] == 0
    assert db_client.get(URL, headers=farmer.headers, params={"include_archived": True}).json()["total"] == 1
    assert db_client.get(f"{URL}/{farm['id']}", headers=farmer.headers).json()["is_active"] is False  # still readable


def test_delete_empty_farm(db_client, farmer, farm):
    assert db_client.delete(f"{URL}/{farm['id']}", headers=farmer.headers).status_code == 204
    assert db_client.get(f"{URL}/{farm['id']}", headers=farmer.headers).status_code == 404


def test_farm_with_plots_cannot_be_deleted(db_client, farmer, farm, plot):
    r = db_client.delete(f"{URL}/{farm['id']}", headers=farmer.headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "farm_not_empty"
    assert db_client.get(f"{URL}/{farm['id']}", headers=farmer.headers).status_code == 200
    assert db_client.get(f"/api/v1/plots/{plot['id']}", headers=farmer.headers).status_code == 200


def test_farm_with_only_expenses_cannot_be_deleted(db_client, api, farmer, farm):
    api.expense(farmer, farm["id"])
    assert db_client.delete(f"{URL}/{farm['id']}", headers=farmer.headers).status_code == 409
