"""Produce quality grading (A/B/C) of a recorded harvest, on PostgreSQL: manual grading, AI photo proposals that the
farmer reviews and corrects, refusals without enough evidence, the hub lock, buyers' view and authorization."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from app.core.ratelimit import HourlyLimit
from app.providers.vision.produce import DisabledProduceGrader, ProduceProposal
from tests.conftest import days_from_today, harvest
from tests.integration.test_farming_authorization import Route, sweep

pytestmark = pytest.mark.integration
API = "/api/v1"
ALL_BEST = {"size": 0, "maturity": 0, "damage": 0, "freshness": 0}
AUTHZ_ROUTES = [
    Route("GET", "/crop-cycles/{cycle_id}/grading"),
    Route("PUT", "/crop-cycles/{cycle_id}/grading", lambda i: {"levels": ALL_BEST}),
    Route("POST", "/crop-cycles/{cycle_id}/grading/photo"),
]


def photo() -> bytes:
    rng = np.random.default_rng(5)
    arr = np.clip(np.full((400, 400, 3), (190, 60, 40), dtype=np.float64) + rng.normal(0, 30, (400, 400, 3)), 0, 255)
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8)).save(buf, format="JPEG")
    return buf.getvalue()


class FakeGrader:
    name = "fake"

    def __init__(self, proposal: ProduceProposal) -> None:
        self.proposal = proposal
        self.calls: list[tuple[str, str | None]] = []

    def propose(self, rgb, profile, crop):
        self.calls.append((profile, crop.name if crop else None))
        return self.proposal


def grading(client, actor, cycle_id, language="en"):
    return client.get(f"{API}/crop-cycles/{cycle_id}/grading", headers=actor.headers, params={"language": language})


def confirm(client, actor, cycle_id, levels, **kw):
    return client.put(f"{API}/crop-cycles/{cycle_id}/grading", headers=actor.headers, json={"levels": levels, **kw})


def upload(client, actor, cycle_id, data=None, language="en"):
    return client.post(
        f"{API}/crop-cycles/{cycle_id}/grading/photo",
        headers=actor.headers,
        files={"image": ("p.jpg", data or photo(), "image/jpeg")},
        data={"language": language},
    )


@pytest.fixture
def harvested(db_client, farmer, growing):
    harvest(db_client, farmer, growing["id"], 800)
    return growing


def test_no_grade_before_the_harvest_is_recorded(db_client, farmer, growing):
    r = grading(db_client, farmer, growing["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "harvest_not_recorded"
    assert confirm(db_client, farmer, growing["id"], ALL_BEST).status_code == 409


def test_manual_grading_sets_the_grade_and_the_lot_buyers_see(db_client, farmer, harvested):
    r = grading(db_client, farmer, harvested["id"])
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["status"] == "not_graded" and g["grade"] is None and g["is_official"] is False
    assert [a["id"] for a in g["criteria"]["attributes"]] == ["size", "maturity", "damage", "freshness"]
    assert "AGMARK" in g["criteria"]["note"]

    r = confirm(db_client, farmer, harvested["id"], {**ALL_BEST, "damage": 1})
    assert r.status_code == 200, r.text
    g = r.json()
    assert (g["status"], g["grade"], g["criteria_grade"], g["grade_source"]) == ("graded", "B", "B", "manual")
    assert g["lot_expected_grade"] == "B" and g["confirmed_at"] and g["grade_text"].startswith("Grade B")

    r = confirm(db_client, farmer, harvested["id"], ALL_BEST)  # regrading before delivery is allowed
    assert r.json()["grade"] == "A" and r.json()["lot_expected_grade"] == "A"
    lot = next(
        x
        for x in db_client.get(f"{API}/inventory/lots", headers=farmer.headers).json()["items"]
        if x["crop_cycle_id"] == harvested["id"]
    )
    assert lot["expected_grade"] == "A"


def test_no_definitive_grade_without_every_check(db_client, farmer, harvested):
    r = confirm(db_client, farmer, harvested["id"], {"size": 0, "damage": 0})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "checks_missing" and err["details"]["missing"] == ["maturity", "freshness"]
    assert grading(db_client, farmer, harvested["id"]).json()["grade"] is None  # nothing stored


@pytest.mark.parametrize(
    ("levels", "code"),
    [({**ALL_BEST, "colour": 0}, "unknown_check"), ({**ALL_BEST, "size": 5}, "request_validation_error")],
)
def test_invalid_ratings_are_refused(db_client, farmer, harvested, levels, code):
    r = confirm(db_client, farmer, harvested["id"], levels)
    assert r.status_code == 422 and r.json()["error"]["code"] == code


def test_a_grade_can_be_lowered_with_a_reason_but_never_raised(db_client, farmer, harvested):
    damaged = {**ALL_BEST, "damage": 2}
    r = confirm(db_client, farmer, harvested["id"], damaged, grade="A")
    assert r.status_code == 422 and r.json()["error"]["code"] == "grade_above_criteria"
    r = confirm(db_client, farmer, harvested["id"], ALL_BEST, grade="B")
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"
    r = confirm(db_client, farmer, harvested["id"], ALL_BEST, grade="B", reason="Sorted late, some softening")
    g = r.json()
    assert (g["grade"], g["criteria_grade"], g["override_reason"]) == ("B", "A", "Sorted late, some softening")


def test_a_photo_proposal_waits_for_review_and_corrections_are_recorded(db_client, db_container, farmer, harvested):
    grader = FakeGrader(
        ProduceProposal(
            "proposed",
            "rated",
            {"size": 0, "maturity": 1, "damage": 0, "freshness": 0},
            confidence="medium",
            description="Red tomatoes, a few uneven in colour.",
            produce_seen="tomato",
            model_name="ollama-vision",
            model_version="gemma3:4b",
        )
    )
    db_container.produce_grader = grader
    r = upload(db_client, farmer, harvested["id"])
    assert r.status_code == 200, r.text
    g = r.json()
    assert grader.calls == [("fresh", "Tomato")]
    assert g["status"] == "needs_review" and g["grade"] is None  # a proposal is never final
    p = g["proposal"]
    assert (p["status"], p["proposed_grade"], p["open_checks"]) == ("proposed", "B", [])
    assert "Review each one" in p["message"] and p["description"].startswith("Red tomatoes")

    # the farmer sees the produce: colour is even, but some pieces are damaged
    r = confirm(db_client, farmer, harvested["id"], {"size": 0, "maturity": 0, "damage": 1, "freshness": 0})
    g = r.json()
    assert (g["grade"], g["grade_source"], g["corrected_checks"]) == ("B", "photo_corrected", ["damage", "maturity"])

    r = confirm(db_client, farmer, harvested["id"], {"size": 0, "maturity": 1, "damage": 0, "freshness": 0})
    assert r.json()["grade_source"] == "photo_confirmed" and r.json()["corrected_checks"] == []


def test_a_partial_proposal_lists_the_open_checks_and_proposes_no_grade(db_client, db_container, api, admin, farmer):
    ragi = api.crop(admin, name="Ragi", category="cereal", typical_duration_days=110)
    farm = api.farm(farmer, name="Dry Farm")
    cycle = api.cycle(
        farmer,
        api.plot(farmer, farm["id"])["id"],
        ragi["id"],
        status="growing",
        sowing_date=days_from_today(-120),
        expected_harvest_date=days_from_today(-5),
    )
    harvest(db_client, farmer, cycle["id"], 300)
    db_container.produce_grader = FakeGrader(
        ProduceProposal("needs_more_evidence", "partial", {"size": 0, "colour": 0, "damage": 1, "foreign_matter": 0})
    )
    g = upload(db_client, farmer, cycle["id"]).json()
    assert g["criteria"]["profile"] == "dry"
    p = g["proposal"]
    assert p["open_checks"] == ["dryness"] and p["proposed_grade"] is None
    assert "Dryness" in p["message"]
    r = confirm(db_client, farmer, cycle["id"], {"size": 0, "colour": 0, "damage": 1, "foreign_matter": 0})
    assert r.status_code == 422 and r.json()["error"]["details"]["missing"] == ["dryness"]
    r = confirm(
        db_client, farmer, cycle["id"], {"size": 0, "colour": 0, "damage": 1, "foreign_matter": 0, "dryness": 0}
    )
    assert r.json()["grade"] == "B"


def test_without_ai_the_farmer_still_grades_manually(db_client, db_container, farmer, harvested):
    db_container.produce_grader = DisabledProduceGrader()
    g = upload(db_client, farmer, harvested["id"]).json()
    assert g["proposal"]["status"] == "unavailable" and "Rate the checks yourself" in g["proposal"]["message"]
    assert g["status"] == "not_graded"
    assert confirm(db_client, farmer, harvested["id"], ALL_BEST).json()["grade"] == "A"


def test_kannada_texts(db_client, db_container, farmer, harvested):
    db_container.produce_grader = DisabledProduceGrader()
    g = upload(db_client, farmer, harvested["id"], language="kn").json()
    assert "ಮಟ್ಟ" in g["proposal"]["message"]
    g = grading(db_client, farmer, harvested["id"], language="kn").json()
    assert g["criteria"]["attributes"][0]["title"] == "ಗಾತ್ರ ಮತ್ತು ಏಕರೂಪತೆ"


def test_bad_files_and_the_hourly_photo_limit(db_client, db_container, farmer, harvested):
    r = upload(db_client, farmer, harvested["id"], data=b"not an image")
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_file_type"
    db_container.produce_grader = DisabledProduceGrader()
    db_container.ai_photo_limit = HourlyLimit(limit=1, clock=db_container.clock, what="AI photo checks")
    assert upload(db_client, farmer, harvested["id"]).status_code == 200
    r = upload(db_client, farmer, harvested["id"])
    assert r.status_code == 429 and r.json()["error"]["code"] == "ai_photo_limit"
    assert int(r.headers["Retry-After"]) > 0


def test_the_grade_is_locked_once_produce_reached_a_hub(db_client, farmer, harvested, monkeypatch):
    from app.repositories.intelligence import ActualRepository

    assert confirm(db_client, farmer, harvested["id"], ALL_BEST).status_code == 200
    monkeypatch.setattr(ActualRepository, "batches_received", lambda self, actual_id: 1)
    r = confirm(db_client, farmer, harvested["id"], {**ALL_BEST, "damage": 2})
    assert r.status_code == 409 and r.json()["error"]["code"] == "grading_locked"
    g = grading(db_client, farmer, harvested["id"]).json()
    assert g["locked"] is True and g["grade"] == "A" and "collection hub" in g["warnings"][0]
    assert upload(db_client, farmer, harvested["id"]).status_code == 409


def test_buyers_see_which_grades_were_graded_after_harvest(db_client, pool_world, farmer, buyer):
    a = pool_world.farms["A"]
    harvest(db_client, farmer, a["cycle_id"], 480)
    assert confirm(db_client, farmer, a["cycle_id"], ALL_BEST).json()["lot_expected_grade"] == "A"
    r = db_client.get(
        f"{API}/market/harvests",
        headers=buyer.headers,
        params={
            "crop_id": pool_world.crop["id"],
            "quantity_kg": 100,
            "window_start": days_from_today(-30),
            "window_end": days_from_today(200),
        },
    )
    assert r.status_code == 200, r.text
    matches = {m["lot_id"]: m for m in r.json()["matches"]}
    assert matches, r.json()
    for lot_id, m in matches.items():
        if lot_id == a["lot_id"]:
            assert (m["grade"], m["grade_basis"]) == ("A", "farmer_graded")
        else:
            assert (m["grade"], m["grade_basis"]) == ("B", "farmer_expected")


# ------------------------------------------------------------------------------------- authorization
@pytest.fixture
def world(db_client, farmer, harvested):
    return {"cycle_id": harvested["id"]}


def test_anonymous_buyers_and_admins_are_refused(db_client, world, buyer, admin):
    assert sweep(db_client, AUTHZ_ROUTES, world, None, 401, "not_authenticated") == []
    assert sweep(db_client, AUTHZ_ROUTES, world, buyer.headers, 403, "permission_denied") == []
    assert sweep(db_client, AUTHZ_ROUTES, world, admin.headers, 403, "permission_denied") == []


def test_another_farmers_harvest_is_not_found(db_client, db_container, world, other_farmer):
    json_routes = [r for r in AUTHZ_ROUTES if not r.path.endswith("/photo")]  # the photo route needs a real file
    assert sweep(db_client, json_routes, world, other_farmer.headers, 404, "not_found") == []
    db_container.produce_grader = DisabledProduceGrader()
    r = upload(db_client, other_farmer, world["cycle_id"])
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_a_graded_lot_keeps_its_grade_in_the_lot_settings(db_client, farmer, harvested):
    confirm(db_client, farmer, harvested["id"], ALL_BEST)
    lot = next(
        x
        for x in db_client.get(f"{API}/inventory/lots", headers=farmer.headers).json()["items"]
        if x["crop_cycle_id"] == harvested["id"]
    )
    r = db_client.patch(f"{API}/inventory/lots/{lot['id']}", headers=farmer.headers, json={"expected_grade": "C"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "grade_set_by_grading"
    r = db_client.patch(f"{API}/inventory/lots/{lot['id']}", headers=farmer.headers, json={"pool_eligible": True})
    assert r.status_code == 200 and r.json()["expected_grade"] == "A"  # other settings still change
