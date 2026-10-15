"""Crop catalog: readable by any authenticated user, managed by admins."""

from __future__ import annotations

import pytest

from app.cli.seed_crops import main as seed_main
from app.cli.seed_crops import seed_payloads

pytestmark = pytest.mark.integration
URL = "/api/v1/crops"

VALID = {"name": "Tomato", "category": "vegetable", "typical_duration_days": 120}


# ------------------------------------------------------------------- create


def test_admin_creates_crop(db_client, admin):
    r = db_client.post(
        URL, headers=admin.headers, json={**VALID, "local_name": "ಟೊಮೆಟೊ", "season": "year_round", "notes": "Hybrid"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Tomato" and body["local_name"] == "ಟೊಮೆಟೊ"
    assert body["typical_duration_days"] == 120 and body["is_active"] is True


@pytest.mark.parametrize("who", ["farmer", "buyer"])
def test_non_admins_cannot_write_the_catalog(db_client, request, who, crop):
    actor = request.getfixturevalue(who)
    assert db_client.post(URL, headers=actor.headers, json={**VALID, "name": "Onion"}).status_code == 403
    assert db_client.patch(f"{URL}/{crop['id']}", headers=actor.headers, json={"notes": "x"}).status_code == 403
    assert db_client.delete(f"{URL}/{crop['id']}", headers=actor.headers).status_code == 403


def test_anonymous_cannot_access_the_catalog(db_client, crop):
    assert db_client.get(URL).status_code == 401
    assert db_client.get(f"{URL}/{crop['id']}").status_code == 401
    assert db_client.post(URL, json=VALID).status_code == 401


def test_duplicate_name_conflicts_case_insensitively(db_client, admin, crop):
    r = db_client.post(URL, headers=admin.headers, json={**VALID, "name": "tomato"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "crop_name_taken"


@pytest.mark.parametrize(
    "body",
    [
        {**VALID, "typical_duration_days": 0},
        {**VALID, "typical_duration_days": -5},
        {**VALID, "typical_duration_days": 3651},
        {**VALID, "category": "dragonfruit"},
        {**VALID, "season": "monsoon"},
        {**VALID, "name": "  "},
        {**VALID, "name": None},
        {**VALID, "category": None},
        {**VALID, "is_admin": True},  # unknown field
        {"category": "vegetable", "typical_duration_days": 120},  # name missing
        {"name": "Tomato", "typical_duration_days": 120},  # category missing
        {"name": "Tomato", "category": "vegetable"},  # duration missing
    ],
    ids=lambda b: str(sorted(b.items()))[:60],
)
def test_invalid_crop_payloads_are_rejected(db_client, admin, body):
    r = db_client.post(URL, headers=admin.headers, json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "request_validation_error"


# --------------------------------------------------------------------- read


def test_every_role_can_list_and_get(db_client, crop, farmer, buyer, admin):
    for actor in (farmer, buyer, admin):
        listing = db_client.get(URL, headers=actor.headers)
        assert listing.status_code == 200 and listing.json()["total"] == 1
        assert db_client.get(f"{URL}/{crop['id']}", headers=actor.headers).json()["name"] == "Tomato"


def test_search_filter_and_pagination(db_client, api, admin, farmer):
    api.crop(admin, name="Tomato", local_name="ಟೊಮೆಟೊ")
    api.crop(admin, name="Onion", category="vegetable")
    api.crop(admin, name="Paddy", category="cereal")
    api.crop(admin, name="Ragi", category="cereal")

    def names(**params):
        r = db_client.get(URL, headers=farmer.headers, params=params)
        assert r.status_code == 200
        return [c["name"] for c in r.json()["items"]], r.json()["total"]

    assert names()[0] == ["Onion", "Paddy", "Ragi", "Tomato"]  # alphabetical
    assert names(search="TOM")[0] == ["Tomato"]  # case-insensitive
    assert names(search="ಟೊಮೆಟೊ")[0] == ["Tomato"]  # local name
    assert names(category="cereal") == (["Paddy", "Ragi"], 2)
    assert names(limit=2, offset=1) == (["Paddy", "Ragi"], 4)  # total is unaffected by paging
    assert names(search="zzz") == ([], 0)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"category": "x"}])
def test_list_validates_query_params(db_client, farmer, params):
    assert db_client.get(URL, headers=farmer.headers, params=params).status_code == 422


def test_inactive_crops_are_hidden_from_non_admins(db_client, admin, farmer, crop):
    db_client.patch(f"{URL}/{crop['id']}", headers=admin.headers, json={"is_active": False})
    assert db_client.get(URL, headers=farmer.headers).json()["total"] == 0
    assert db_client.get(URL, headers=farmer.headers, params={"include_inactive": True}).json()["total"] == 0
    assert db_client.get(f"{URL}/{crop['id']}", headers=farmer.headers).status_code == 404
    # admins can still see and manage them
    assert db_client.get(URL, headers=admin.headers).json()["total"] == 0
    assert db_client.get(URL, headers=admin.headers, params={"include_inactive": True}).json()["total"] == 1
    assert db_client.get(f"{URL}/{crop['id']}", headers=admin.headers).status_code == 200


def test_unknown_crop_is_404(db_client, farmer):
    assert db_client.get(f"{URL}/7d6e2b7a-8f3a-4c43-9b8a-0a3a7a0d5a11", headers=farmer.headers).status_code == 404
    assert db_client.get(f"{URL}/not-a-uuid", headers=farmer.headers).status_code == 422


# ------------------------------------------------------------------- update


def test_admin_updates_crop(db_client, admin, crop):
    r = db_client.patch(
        f"{URL}/{crop['id']}", headers=admin.headers, json={"typical_duration_days": 90, "season": "rabi"}
    )
    assert r.status_code == 200
    assert r.json()["typical_duration_days"] == 90 and r.json()["season"] == "rabi"
    assert r.json()["name"] == "Tomato"  # untouched fields survive
    cleared = db_client.patch(f"{URL}/{crop['id']}", headers=admin.headers, json={"season": None})
    assert cleared.json()["season"] is None  # nullable column can be cleared


def test_rename_to_existing_name_conflicts(db_client, api, admin, crop):
    other = api.crop(admin, name="Onion")
    assert db_client.patch(f"{URL}/{other['id']}", headers=admin.headers, json={"name": "TOMATO"}).status_code == 409
    assert db_client.patch(f"{URL}/{crop['id']}", headers=admin.headers, json={"name": "TOMATO"}).status_code == 200


@pytest.mark.parametrize("field", ["name", "category", "typical_duration_days", "is_active"])
def test_required_fields_cannot_be_nulled(db_client, admin, crop, field):
    r = db_client.patch(f"{URL}/{crop['id']}", headers=admin.headers, json={field: None})
    assert r.status_code == 422 and r.json()["error"]["details"]["errors"][0]["field"] == field


# ------------------------------------------------------------------- delete


def test_unused_crop_can_be_deleted(db_client, admin, crop):
    assert db_client.delete(f"{URL}/{crop['id']}", headers=admin.headers).status_code == 204
    assert db_client.get(f"{URL}/{crop['id']}", headers=admin.headers).status_code == 404


def test_crop_in_use_cannot_be_deleted(db_client, admin, crop, cycle):
    r = db_client.delete(f"{URL}/{crop['id']}", headers=admin.headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "crop_in_use"
    assert db_client.get(f"{URL}/{crop['id']}", headers=admin.headers).status_code == 200  # still there


# --------------------------------------------------------------------- seed


def test_seed_payloads_are_valid_and_unique():
    payloads = seed_payloads()
    assert len(payloads) >= 15
    assert len({p.name.lower() for p in payloads}) == len(payloads)
    assert all(p.typical_duration_days > 0 for p in payloads)


def test_seed_command_is_idempotent(db_client, db_container, farmer, capsys):
    assert seed_main([], db_container) == 0
    first = capsys.readouterr().out
    total = len(seed_payloads())
    assert f"{total} created, 0 already present" in first
    assert seed_main([], db_container) == 0
    assert f"0 created, {total} already present" in capsys.readouterr().out
    assert db_client.get(URL, headers=farmer.headers).json()["total"] == total


def test_seed_does_not_overwrite_admin_edits(db_client, db_container, admin, farmer):
    seed_main([], db_container)
    tomato = db_client.get(URL, headers=farmer.headers, params={"search": "Tomato"}).json()["items"][0]
    db_client.patch(f"{URL}/{tomato['id']}", headers=admin.headers, json={"typical_duration_days": 77})
    seed_main([], db_container)
    after = db_client.get(f"{URL}/{tomato['id']}", headers=farmer.headers).json()
    assert after["typical_duration_days"] == 77


def test_seed_adds_new_catalogue_crops_without_touching_existing_ones(db_client, db_container, admin, farmer):
    # an older install: a few of the original crops, one edited by an admin
    tomato = db_client.post(
        URL,
        headers=admin.headers,
        json={"name": "Tomato", "category": "vegetable", "typical_duration_days": 101, "local_name": "Custom"},
    ).json()
    seed_main([], db_container)
    after = db_client.get(f"{URL}/{tomato['id']}", headers=farmer.headers).json()
    assert after["id"] == tomato["id"] and after["typical_duration_days"] == 101 and after["local_name"] == "Custom"
    fodder = db_client.get(URL, headers=farmer.headers, params={"category": "fodder"}).json()["items"]
    medicinal = db_client.get(URL, headers=farmer.headers, params={"category": "medicinal"}).json()["items"]
    assert {"Fodder Maize", "Napier Grass"} <= {c["name"] for c in fodder}
    assert {"Tulsi", "Aloe Vera"} <= {c["name"] for c in medicinal}
    # search works on the Kannada name too
    found = db_client.get(URL, headers=farmer.headers, params={"search": "ಮಾವು"}).json()["items"]
    assert [c["name"] for c in found] == ["Mango"]


def test_new_catalogue_entries_are_labelled_and_invent_no_reference_values():
    from app.cli.seed_crops import _MORE

    for p in seed_payloads():
        if p.name in {row[0] for row in _MORE}:
            assert p.notes and ("Indicative" in p.notes or "Perennial" in p.notes)
            assert p.reference_yield_kg_per_acre is None and p.water_need_mm is None
            assert p.local_name is None or all("ಀ" <= ch <= "೿" or ch in " ‌" for ch in p.local_name)


def test_plantation_category_and_minor_millets(db_client, db_container, farmer):
    seed_main([], db_container)
    plantation = db_client.get(URL, headers=farmer.headers, params={"category": "plantation"}).json()["items"]
    assert {"Coconut", "Arecanut", "Coffee", "Tea", "Rubber", "Cashew", "Oil Palm", "Cocoa"} == {
        c["name"] for c in plantation
    }
    cereals = {
        c["name"] for c in db_client.get(URL, headers=farmer.headers, params={"category": "cereal"}).json()["items"]
    }
    assert {"Little Millet", "Kodo Millet", "Proso Millet", "Barnyard Millet", "Browntop Millet", "Ragi"} <= cereals
    cash = {
        c["name"] for c in db_client.get(URL, headers=farmer.headers, params={"category": "cash_crop"}).json()["items"]
    }
    assert "Coconut" not in cash and "Sugarcane" in cash
