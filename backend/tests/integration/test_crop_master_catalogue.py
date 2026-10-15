"""Catalogue reconciliation on PostgreSQL (existing ids, names and Kannada names kept; A-Z crops added once; aliases
searchable), crop context in photo checks, and the per-crop validation report."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from app.cli.seed_crops import main as seed_main
from app.core.enums import CropHealthClass
from app.domain.crop_catalog import NEW
from app.domain.vision import HealthAssessment

pytestmark = pytest.mark.integration
API = "/api/v1"


def all_crops(client, actor):
    first = client.get(f"{API}/crops", headers=actor.headers, params={"limit": 100}).json()
    out = list(first["items"])
    for offset in range(100, first["total"], 100):
        out += client.get(f"{API}/crops", headers=actor.headers, params={"limit": 100, "offset": offset}).json()[
            "items"
        ]
    return out


def photo() -> bytes:
    buf = io.BytesIO()
    Image.fromarray(np.full((300, 300, 3), (50, 140, 40), dtype=np.uint8)).save(buf, "JPEG")
    return buf.getvalue()


class SeeingClassifier:
    """Records the crop context it is given (the real model is tested in tests/unit/test_vision_ollama.py)."""

    name = "scripted-vision"
    version = "1"

    def __init__(self) -> None:
        self.contexts: list[object] = []

    def assess(self, rgb, language, crop=None):  # type: ignore[no-untyped-def]
        self.contexts.append(crop)
        probs = {c.value: 0.0 for c in CropHealthClass}
        probs["unknown"] = 1.0
        return HealthAssessment(CropHealthClass.UNKNOWN, probs, {"crop_seen": "unknown"}, [], "e", "a")


def test_reconcile_keeps_existing_crops_and_adds_the_a_to_z_list_once(db_client, db_container, admin, farmer, api):
    ragi = api.crop(admin, name="Ragi", local_name="ರಾಗಿ", category="cereal", typical_duration_days=120)
    custom = api.crop(admin, name="Kokum Special", category="fruit", typical_duration_days=365, aliases=["kokum"])
    assert seed_main(["--reconcile"], db_container) == 0
    by_name = {c["name"]: c for c in all_crops(db_client, farmer)}
    assert by_name["Ragi"]["id"] == ragi["id"] and by_name["Ragi"]["local_name"] == "ರಾಗಿ"  # id and Kannada kept
    assert by_name["Ragi"]["scientific_name"] == "Eleusine coracana" and "finger millet" in by_name["Ragi"]["aliases"]
    assert by_name["Ragi"]["crop_group"] == "millets"
    assert "Kokum" not in by_name and by_name["Kokum Special"]["id"] == custom["id"]  # alias clash: not duplicated
    assert {"Cassava", "Xanthosoma", "Zucchini", "Mushroom", "Quinoa"} <= set(by_name)
    assert all(by_name[c.name]["local_name"] is None for c in NEW if c.name in by_name)  # no invented Kannada
    count = len(by_name)
    assert seed_main(["--reconcile"], db_container) == 0  # running again adds nothing
    again = all_crops(db_client, farmer)
    assert len(again) == count


def test_crops_are_found_by_alias_scientific_and_kannada_name(db_client, db_container, farmer):
    seed_main(["--reconcile"], db_container)
    for query, expected in (
        ("finger millet", "Ragi"),
        ("chikoo", "Sapota"),
        ("Cajanus", "Red Gram"),
        ("ರಾಗಿ", "Ragi"),
        ("tapioca", "Cassava"),
        ("lady's finger", "Okra"),
    ):
        names = [
            c["name"]
            for c in db_client.get(f"{API}/crops", headers=farmer.headers, params={"search": query}).json()["items"]
        ]
        assert expected in names, (query, names)


def test_the_photo_check_is_told_the_crop_from_the_cycle_or_crop_id(db_client, db_container, farmer, api, admin):
    seed_main(["--reconcile"], db_container)
    clf = SeeingClassifier()
    db_container.crop_health = clf
    potato = next(
        c
        for c in db_client.get(f"{API}/crops", headers=farmer.headers, params={"search": "Potato"}).json()["items"]
        if c["name"] == "Potato"
    )
    farm = api.farm(farmer)
    cycle = api.cycle(farmer, api.plot(farmer, farm["id"])["id"], potato["id"])
    r = db_client.post(
        f"{API}/crop-health/analyze",
        headers=farmer.headers,
        files={"image": ("p.jpg", photo(), "image/jpeg")},
        data={"crop_cycle_id": cycle["id"]},
    )
    assert r.status_code == 200, r.text
    ctx = clf.contexts[-1]
    assert ctx.name == "Potato" and ctx.part == "tuber" and "solanum" in ctx.names
    assert r.json()["features"]["validation"]["verdict"] == "insufficient_evidence"
    limits = next(x for x in r.json()["features"]["analysis"]["sections"] if x["id"] == "limitations")
    assert any("Potato has not been validated" in item for item in limits["items"])
    mush = next(
        c
        for c in db_client.get(f"{API}/crops", headers=farmer.headers, params={"search": "mushroom"}).json()["items"]
        if c["name"] == "Mushroom"
    )
    r = db_client.post(
        f"{API}/crop-health/analyze",
        headers=farmer.headers,
        files={"image": ("m.jpg", photo(), "image/jpeg")},
        data={"crop_id": mush["id"]},
    )
    assert r.status_code == 200 and clf.contexts[-1].specialist_only
    r = db_client.post(
        f"{API}/crop-health/analyze",
        headers=farmer.headers,
        files={"image": ("x.jpg", photo(), "image/jpeg")},
        data={"crop_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 404
    db_client.post(
        f"{API}/crop-health/analyze", headers=farmer.headers, files={"image": ("y.jpg", photo(), "image/jpeg")}
    )
    assert clf.contexts[-1] is None  # no crop chosen: no crop assumed


def test_validation_report_lists_every_crop_and_never_claims_unmeasured_accuracy(db_client, db_container, farmer):
    seed_main(["--reconcile"], db_container)
    r = db_client.get(f"{API}/crop-health/validation", headers=farmer.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    names = {c["name"] for c in body["crops"]}
    assert body["summary"]["catalogue_crops"] == len(names) >= 200 and body["summary"]["reliable"] == 0
    groundnut = next(c for c in body["crops"] if c["name"] == "Groundnut")
    assert groundnut["validation"]["verdict"] == "not_reliable" and groundnut["main_part"] == "pod"
    assert "coverage is not accuracy" in body["rule"]
    assert db_client.get(f"{API}/crop-health/validation").status_code == 401
