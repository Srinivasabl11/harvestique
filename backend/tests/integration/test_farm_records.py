"""Expenses, activities and crop observations: CRUD, cross-references, ownership, validation."""

from __future__ import annotations

import pytest

from tests.conftest import days_from_today as d

pytestmark = pytest.mark.integration
API = "/api/v1"


def code(response) -> str:
    return response.json()["error"]["code"]


def field_errors(response) -> set[str]:
    return {e["field"] for e in response.json()["error"]["details"]["errors"]}


# ===================================================================== expenses


class TestExpenses:
    def url(self, farm_id: str) -> str:
        return f"{API}/farms/{farm_id}/expenses"

    def test_create_farm_level_and_cycle_level(self, db_client, farmer, farm, cycle):
        overhead = db_client.post(
            self.url(farm["id"]),
            headers=farmer.headers,
            json={"category": "labour", "amount": 2500, "expense_date": d(-1), "description": "Weeding crew"},
        )
        assert overhead.status_code == 201
        body = overhead.json()
        assert body["crop_cycle_id"] is None and body["amount"] == 2500 and body["farm_id"] == farm["id"]
        tied = db_client.post(
            self.url(farm["id"]),
            headers=farmer.headers,
            json={"category": "seed", "amount": 1234.56, "expense_date": d(-9), "crop_cycle_id": cycle["id"]},
        )
        assert (
            tied.status_code == 201 and tied.json()["amount"] == 1234.56 and tied.json()["crop_cycle_id"] == cycle["id"]
        )

    @pytest.mark.parametrize("amount", [0, -1, -0.01, 1.005, "free", None, 10**12])
    def test_amount_must_be_positive_money(self, db_client, farmer, farm, amount):
        r = db_client.post(
            self.url(farm["id"]),
            headers=farmer.headers,
            json={"category": "seed", "amount": amount, "expense_date": d(-1)},
        )
        assert r.status_code == 422 and "amount" in field_errors(r)

    @pytest.mark.parametrize(
        "body",
        [
            {"amount": 5, "expense_date": d(-1)},  # category missing
            {"category": "seed", "expense_date": d(-1)},  # amount missing
            {"category": "seed", "amount": 5},  # date missing
            {"category": "gold-plating", "amount": 5, "expense_date": d(-1)},
            {"category": "seed", "amount": 5, "expense_date": "someday"},
            {"category": "seed", "amount": 5, "expense_date": d(-1), "farm_id": "x"},
        ],
    )
    def test_invalid_payloads(self, db_client, farmer, farm, body):
        assert db_client.post(self.url(farm["id"]), headers=farmer.headers, json=body).status_code == 422

    def test_future_dated_expense_rejected(self, db_client, farmer, farm):
        r = db_client.post(
            self.url(farm["id"]), headers=farmer.headers, json={"category": "seed", "amount": 5, "expense_date": d(5)}
        )
        assert r.status_code == 422 and code(r) == "expense_date_in_future"

    def test_expense_before_sowing_is_fine(self, api, farmer, farm, cycle):
        """Seed and land preparation are bought before the crop is sown."""
        assert api.expense(farmer, farm["id"], crop_cycle_id=cycle["id"], expense_date=d(-60))["id"]

    def test_cycle_must_belong_to_the_same_farm(self, db_client, api, farmer, farm, cycle):
        other_farm = api.farm(farmer, name="Second Farm")
        r = db_client.post(
            self.url(other_farm["id"]),
            headers=farmer.headers,
            json={"category": "seed", "amount": 5, "expense_date": d(-1), "crop_cycle_id": cycle["id"]},
        )
        assert r.status_code == 422 and code(r) == "crop_cycle_not_in_farm"

    def test_cannot_attach_to_someone_elses_cycle(self, db_client, api, other_farmer, farm, cycle):
        theirs = api.farm(other_farmer, name="Theirs")
        r = db_client.post(
            self.url(theirs["id"]),
            headers=other_farmer.headers,
            json={"category": "seed", "amount": 5, "expense_date": d(-1), "crop_cycle_id": cycle["id"]},
        )
        assert r.status_code == 422 and code(r) == "crop_cycle_not_in_farm"  # indistinguishable from "does not exist"

    def test_archived_farm_rejects_new_expenses(self, db_client, farmer, farm):
        db_client.patch(f"{API}/farms/{farm['id']}", headers=farmer.headers, json={"is_active": False})
        r = db_client.post(
            self.url(farm["id"]), headers=farmer.headers, json={"category": "seed", "amount": 5, "expense_date": d(-1)}
        )
        assert r.status_code == 409 and code(r) == "farm_archived"

    def test_ownership(self, db_client, api, farmer, other_farmer, farm):
        expense = api.expense(farmer, farm["id"])
        url = f"{API}/expenses/{expense['id']}"
        body = {"category": "seed", "amount": 5, "expense_date": d(-1)}
        assert db_client.post(self.url(farm["id"]), headers=other_farmer.headers, json=body).status_code == 404
        assert db_client.get(self.url(farm["id"]), headers=other_farmer.headers).status_code == 404
        assert db_client.get(url, headers=other_farmer.headers).status_code == 404
        assert db_client.patch(url, headers=other_farmer.headers, json={"amount": 1}).status_code == 404
        assert db_client.delete(url, headers=other_farmer.headers).status_code == 404
        assert db_client.get(url, headers=farmer.headers).json()["amount"] == 1500.5  # untouched

    def test_list_filters_and_ordering(self, db_client, api, farmer, farm, cycle):
        a = api.expense(farmer, farm["id"], category="seed", expense_date=d(-30), crop_cycle_id=cycle["id"])
        b = api.expense(farmer, farm["id"], category="labour", expense_date=d(-10))
        c = api.expense(farmer, farm["id"], category="labour", expense_date=d(-2), crop_cycle_id=cycle["id"])

        def ids(**params):
            r = db_client.get(self.url(farm["id"]), headers=farmer.headers, params=params)
            assert r.status_code == 200
            return [e["id"] for e in r.json()["items"]]

        assert ids() == [c["id"], b["id"], a["id"]]  # newest first
        assert ids(category="labour") == [c["id"], b["id"]]
        assert ids(crop_cycle_id=cycle["id"]) == [c["id"], a["id"]]
        assert ids(date_from=d(-12), date_to=d(-5)) == [b["id"]]
        assert ids(date_from=d(-30), date_to=d(-30)) == [a["id"]]  # both bounds inclusive
        assert ids(limit=1, offset=1) == [b["id"]]

    def test_list_is_scoped_to_the_farm(self, db_client, api, farmer, farm):
        other = api.farm(farmer, name="Second Farm")
        api.expense(farmer, farm["id"])
        assert db_client.get(self.url(other["id"]), headers=farmer.headers).json()["total"] == 0

    def test_update(self, db_client, api, farmer, farm, cycle):
        e = api.expense(farmer, farm["id"], description="Seeds")
        url = f"{API}/expenses/{e['id']}"
        r = db_client.patch(url, headers=farmer.headers, json={"amount": 99.99, "crop_cycle_id": cycle["id"]})
        assert r.status_code == 200 and r.json()["amount"] == 99.99 and r.json()["crop_cycle_id"] == cycle["id"]
        assert r.json()["description"] == "Seeds"
        detached = db_client.patch(url, headers=farmer.headers, json={"crop_cycle_id": None, "description": None})
        assert detached.json()["crop_cycle_id"] is None and detached.json()["description"] is None

    @pytest.mark.parametrize("field", ["category", "amount", "expense_date"])
    def test_update_cannot_null_required_fields(self, db_client, api, farmer, farm, field):
        e = api.expense(farmer, farm["id"])
        assert (
            db_client.patch(f"{API}/expenses/{e['id']}", headers=farmer.headers, json={field: None}).status_code == 422
        )

    def test_update_revalidates(self, db_client, api, farmer, farm):
        e = api.expense(farmer, farm["id"])
        url = f"{API}/expenses/{e['id']}"
        assert db_client.patch(url, headers=farmer.headers, json={"amount": 0}).status_code == 422
        assert (
            code(db_client.patch(url, headers=farmer.headers, json={"expense_date": d(9)})) == "expense_date_in_future"
        )
        stray = db_client.patch(
            url, headers=farmer.headers, json={"crop_cycle_id": "7d6e2b7a-8f3a-4c43-9b8a-0a3a7a0d5a11"}
        )
        assert code(stray) == "crop_cycle_not_in_farm"

    def test_delete(self, db_client, api, farmer, farm):
        e = api.expense(farmer, farm["id"])
        assert db_client.delete(f"{API}/expenses/{e['id']}", headers=farmer.headers).status_code == 204
        assert db_client.get(f"{API}/expenses/{e['id']}", headers=farmer.headers).status_code == 404


# ==================================================================== activities


class TestActivities:
    def url(self, farm_id: str) -> str:
        return f"{API}/farms/{farm_id}/activities"

    def test_create_variants(self, db_client, farmer, farm, plot, cycle):
        general = db_client.post(
            self.url(farm["id"]),
            headers=farmer.headers,
            json={"activity_type": "land_preparation", "activity_date": d(-12)},
        )
        assert (
            general.status_code == 201 and general.json()["plot_id"] is None and general.json()["crop_cycle_id"] is None
        )
        full = db_client.post(
            self.url(farm["id"]),
            headers=farmer.headers,
            json={
                "activity_type": "fertilizing",
                "activity_date": d(-3),
                "plot_id": plot["id"],
                "crop_cycle_id": cycle["id"],
                "description": "Urea 20kg",
            },
        )
        assert full.status_code == 201 and full.json()["description"] == "Urea 20kg"

    @pytest.mark.parametrize(
        "body",
        [
            {"activity_date": d(-1)},
            {"activity_type": "irrigation"},
            {"activity_type": "dancing", "activity_date": d(-1)},
            {"activity_type": "irrigation", "activity_date": "soon"},
            {"activity_type": "irrigation", "activity_date": d(-1), "farm_id": "x"},
        ],
    )
    def test_invalid_payloads(self, db_client, farmer, farm, body):
        assert db_client.post(self.url(farm["id"]), headers=farmer.headers, json=body).status_code == 422

    def test_future_date_rejected(self, db_client, farmer, farm):
        r = db_client.post(
            self.url(farm["id"]), headers=farmer.headers, json={"activity_type": "irrigation", "activity_date": d(3)}
        )
        assert r.status_code == 422 and code(r) == "activity_date_in_future"

    def test_plot_must_belong_to_the_farm(self, db_client, api, farmer, farm):
        other_farm = api.farm(farmer, name="Second Farm")
        foreign_plot = api.plot(farmer, other_farm["id"], name="Elsewhere")
        r = db_client.post(
            self.url(farm["id"]),
            headers=farmer.headers,
            json={"activity_type": "weeding", "activity_date": d(-1), "plot_id": foreign_plot["id"]},
        )
        assert r.status_code == 422 and code(r) == "plot_not_in_farm"

    def test_cycle_must_belong_to_the_farm(self, db_client, api, farmer, farm, cycle):
        other_farm = api.farm(farmer, name="Second Farm")
        r = db_client.post(
            self.url(other_farm["id"]),
            headers=farmer.headers,
            json={"activity_type": "weeding", "activity_date": d(-1), "crop_cycle_id": cycle["id"]},
        )
        assert r.status_code == 422 and code(r) == "crop_cycle_not_in_farm"

    def test_cycle_and_plot_must_agree(self, db_client, api, farmer, farm, cycle):
        another_plot = api.plot(farmer, farm["id"], name="Second Plot", area_acres=2)
        r = db_client.post(
            self.url(farm["id"]),
            headers=farmer.headers,
            json={
                "activity_type": "weeding",
                "activity_date": d(-1),
                "plot_id": another_plot["id"],
                "crop_cycle_id": cycle["id"],
            },
        )
        assert r.status_code == 422 and code(r) == "cycle_plot_mismatch"

    def test_ownership(self, db_client, api, farmer, other_farmer, farm):
        activity = api.activity(farmer, farm["id"])
        url = f"{API}/activities/{activity['id']}"
        body = {"activity_type": "weeding", "activity_date": d(-1)}
        assert db_client.post(self.url(farm["id"]), headers=other_farmer.headers, json=body).status_code == 404
        assert db_client.get(self.url(farm["id"]), headers=other_farmer.headers).status_code == 404
        assert db_client.get(url, headers=other_farmer.headers).status_code == 404
        assert db_client.patch(url, headers=other_farmer.headers, json={"description": "x"}).status_code == 404
        assert db_client.delete(url, headers=other_farmer.headers).status_code == 404

    def test_list_filters(self, db_client, api, farmer, farm, plot, cycle):
        a = api.activity(farmer, farm["id"], activity_type="irrigation", activity_date=d(-20))
        b = api.activity(farmer, farm["id"], activity_type="weeding", activity_date=d(-8), plot_id=plot["id"])
        c = api.activity(farmer, farm["id"], activity_type="irrigation", activity_date=d(-1), crop_cycle_id=cycle["id"])

        def ids(**params):
            return [
                x["id"]
                for x in db_client.get(self.url(farm["id"]), headers=farmer.headers, params=params).json()["items"]
            ]

        assert ids() == [c["id"], b["id"], a["id"]]
        assert ids(activity_type="irrigation") == [c["id"], a["id"]]
        assert ids(plot_id=plot["id"]) == [b["id"]]
        assert ids(crop_cycle_id=cycle["id"]) == [c["id"]]
        assert ids(date_from=d(-10), date_to=d(-5)) == [b["id"]]

    def test_update_revalidates_links(self, db_client, api, farmer, farm, plot, cycle):
        a = api.activity(farmer, farm["id"], plot_id=plot["id"])
        url = f"{API}/activities/{a['id']}"
        ok = db_client.patch(url, headers=farmer.headers, json={"crop_cycle_id": cycle["id"], "description": "Done"})
        assert ok.status_code == 200 and ok.json()["crop_cycle_id"] == cycle["id"]
        other_plot = api.plot(farmer, farm["id"], name="Other", area_acres=2)
        mismatch = db_client.patch(url, headers=farmer.headers, json={"plot_id": other_plot["id"]})
        assert mismatch.status_code == 422 and code(mismatch) == "cycle_plot_mismatch"
        cleared = db_client.patch(url, headers=farmer.headers, json={"plot_id": None, "crop_cycle_id": None})
        assert cleared.status_code == 200 and cleared.json()["plot_id"] is None

    @pytest.mark.parametrize("field", ["activity_type", "activity_date"])
    def test_update_cannot_null_required_fields(self, db_client, api, farmer, farm, field):
        a = api.activity(farmer, farm["id"])
        assert (
            db_client.patch(f"{API}/activities/{a['id']}", headers=farmer.headers, json={field: None}).status_code
            == 422
        )

    def test_delete(self, db_client, api, farmer, farm):
        a = api.activity(farmer, farm["id"])
        assert db_client.delete(f"{API}/activities/{a['id']}", headers=farmer.headers).status_code == 204
        assert db_client.get(f"{API}/activities/{a['id']}", headers=farmer.headers).status_code == 404


# ================================================================= observations


class TestObservations:
    def url(self, cycle_id: str) -> str:
        return f"{API}/crop-cycles/{cycle_id}/observations"

    def test_create(self, db_client, farmer, cycle):
        r = db_client.post(
            self.url(cycle["id"]),
            headers=farmer.headers,
            json={
                "observed_on": d(-2),
                "growth_stage": "flowering",
                "health_status": "pest_affected",
                "estimated_loss_percent": 12.5,
                "notes": "Whitefly on lower leaves",
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert body["crop_cycle_id"] == cycle["id"] and body["growth_stage"] == "flowering"
        assert body["health_status"] == "pest_affected" and body["estimated_loss_percent"] == 12.5

    def test_minimal(self, api, farmer, cycle):
        o = api.observation(farmer, cycle["id"])
        assert o["growth_stage"] is None and o["estimated_loss_percent"] is None

    @pytest.mark.parametrize("percent", [0, 0.01, 50, 100])
    def test_loss_percent_accepts_0_to_100(self, api, farmer, cycle, percent):
        assert api.observation(farmer, cycle["id"], estimated_loss_percent=percent)["estimated_loss_percent"] == percent

    @pytest.mark.parametrize("percent", [-0.01, -1, 100.01, 101, 12.345, "lots"])
    def test_loss_percent_outside_range_rejected(self, db_client, farmer, cycle, percent):
        r = db_client.post(
            self.url(cycle["id"]),
            headers=farmer.headers,
            json={"observed_on": d(-1), "health_status": "healthy", "estimated_loss_percent": percent},
        )
        assert r.status_code == 422 and "estimated_loss_percent" in field_errors(r)

    @pytest.mark.parametrize(
        "body",
        [
            {"health_status": "healthy"},
            {"observed_on": d(-1)},
            {"observed_on": d(-1), "health_status": "thriving"},
            {"observed_on": d(-1), "health_status": "healthy", "growth_stage": "ripe"},
            {"observed_on": d(-1), "health_status": "healthy", "crop_cycle_id": "x"},
        ],
    )
    def test_invalid_payloads(self, db_client, farmer, cycle, body):
        assert db_client.post(self.url(cycle["id"]), headers=farmer.headers, json=body).status_code == 422

    def test_cannot_observe_before_sowing(self, db_client, farmer, cycle):
        r = db_client.post(
            self.url(cycle["id"]), headers=farmer.headers, json={"observed_on": d(-11), "health_status": "healthy"}
        )  # the fixture cycle was sown 10 days ago
        assert r.status_code == 422 and code(r) == "observation_before_sowing"

    def test_observation_on_the_sowing_day_is_allowed(self, api, farmer, cycle):
        assert api.observation(farmer, cycle["id"], observed_on=d(-10))["observed_on"] == d(-10)

    def test_future_observation_rejected(self, db_client, farmer, cycle):
        r = db_client.post(
            self.url(cycle["id"]), headers=farmer.headers, json={"observed_on": d(4), "health_status": "healthy"}
        )
        assert r.status_code == 422 and code(r) == "observed_on_in_future"

    def test_ownership(self, db_client, api, farmer, other_farmer, cycle):
        o = api.observation(farmer, cycle["id"])
        url = f"{API}/observations/{o['id']}"
        body = {"observed_on": d(-1), "health_status": "healthy"}
        assert db_client.post(self.url(cycle["id"]), headers=other_farmer.headers, json=body).status_code == 404
        assert db_client.get(self.url(cycle["id"]), headers=other_farmer.headers).status_code == 404
        assert db_client.get(url, headers=other_farmer.headers).status_code == 404
        assert db_client.patch(url, headers=other_farmer.headers, json={"notes": "x"}).status_code == 404
        assert db_client.delete(url, headers=other_farmer.headers).status_code == 404

    def test_list_newest_first_with_paging(self, db_client, api, farmer, cycle):
        old = api.observation(farmer, cycle["id"], observed_on=d(-8))
        mid = api.observation(farmer, cycle["id"], observed_on=d(-5))
        new = api.observation(farmer, cycle["id"], observed_on=d(-1))
        page = db_client.get(self.url(cycle["id"]), headers=farmer.headers).json()
        assert [o["id"] for o in page["items"]] == [new["id"], mid["id"], old["id"]] and page["total"] == 3
        assert [
            o["id"]
            for o in db_client.get(
                self.url(cycle["id"]), headers=farmer.headers, params={"limit": 1, "offset": 2}
            ).json()["items"]
        ] == [old["id"]]

    def test_update(self, db_client, api, farmer, cycle):
        o = api.observation(farmer, cycle["id"], estimated_loss_percent=5)
        url = f"{API}/observations/{o['id']}"
        r = db_client.patch(
            url, headers=farmer.headers, json={"health_status": "damaged", "estimated_loss_percent": 40}
        )
        assert (
            r.status_code == 200 and r.json()["health_status"] == "damaged" and r.json()["estimated_loss_percent"] == 40
        )
        assert (
            db_client.patch(url, headers=farmer.headers, json={"estimated_loss_percent": None}).json()[
                "estimated_loss_percent"
            ]
            is None
        )
        assert db_client.patch(url, headers=farmer.headers, json={"estimated_loss_percent": 101}).status_code == 422
        assert db_client.patch(url, headers=farmer.headers, json={"health_status": None}).status_code == 422
        before_sowing = db_client.patch(url, headers=farmer.headers, json={"observed_on": d(-20)})
        assert before_sowing.status_code == 422 and code(before_sowing) == "observation_before_sowing"

    def test_delete(self, db_client, api, farmer, cycle):
        o = api.observation(farmer, cycle["id"])
        assert db_client.delete(f"{API}/observations/{o['id']}", headers=farmer.headers).status_code == 204
        assert db_client.get(f"{API}/observations/{o['id']}", headers=farmer.headers).status_code == 404
