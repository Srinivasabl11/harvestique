"""Crop Health Check through the API on PostgreSQL with the real catalogue: the item in the photo is identified,
the result carries item, parent category, health score and A/B/C category; uncertain or failed checks are "Unable to
classify"; a fenced cloud answer is understood end to end."""

from __future__ import annotations

import io

import httpx
import numpy as np
import pytest
from PIL import Image

from app.cli.seed_crops import main as seed_main
from app.core.enums import CropHealthClass
from app.domain.vision import HealthAssessment
from app.providers.vision.base import ColourHeuristicClassifier
from app.providers.vision.ollama import OllamaVisionClassifier

pytestmark = pytest.mark.integration
API = "/api/v1"


def leaf_photo() -> bytes:
    rng = np.random.default_rng(9)
    arr = np.clip(np.full((400, 400, 3), (50, 140, 40), dtype=np.float64) + rng.normal(0, 25, (400, 400, 3)), 0, 255)
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8)).save(buf, format="JPEG")
    return buf.getvalue()


class Scripted:
    """Answers like the real classifier would after reading the model's JSON (that part: tests/unit)."""

    name = "scripted-vision"
    version = "1"

    def __init__(self, crop_seen: str, symptoms: list[str] | None = None, flags: list[str] | None = None) -> None:
        self.crop_seen, self.symptoms, self.flags = crop_seen, symptoms or [], flags or []

    def assess(self, rgb, language, crop=None):  # type: ignore[no-untyped-def]
        label = CropHealthClass.POSSIBLE_DISEASE if self.symptoms else CropHealthClass.HEALTHY
        features = {"crop_seen": self.crop_seen, "symptoms": self.symptoms, "ai_confidence": "high"}
        if crop is not None:
            features |= {"expected_crop": crop.name, "crop_match": True}
        return HealthAssessment(label, {label.value: 0.65}, features, self.flags, "e", "a")


def analyze(db_client, farmer, *, language="en", data=None, **fields):
    return db_client.post(
        f"{API}/crop-health/analyze",
        headers=farmer.headers,
        files={"image": ("p.jpg", data if data is not None else leaf_photo(), "image/jpeg")},
        data={"language": language, **fields},
    )


@pytest.fixture
def catalogue(db_container):
    assert seed_main(["--reconcile"], db_container) == 0


@pytest.mark.parametrize(
    ("seen", "name", "parent"),
    [
        ("ragi", "Ragi", "Cereals and grains"),
        ("tomato leaf", "Tomato", "Vegetables"),
        ("mango", "Mango", "Fruits and nuts"),
    ],
)
def test_the_item_in_a_photo_is_identified_without_choosing_a_crop(
    db_client, db_container, farmer, catalogue, seen, name, parent
):
    db_container.crop_health = Scripted(seen)
    r = analyze(db_client, farmer)
    assert r.status_code == 200, r.text
    d = r.json()["decision"]
    assert (d["item"]["name"], d["item"]["parent_name"], d["item"]["source"]) == (name, parent, "photo")
    assert (d["status"], d["health_score"], d["health_category"]) == ("healthy", 100.0, "A")


def test_kannada_results_use_the_kannada_name_and_category(db_client, db_container, farmer, catalogue):
    db_container.crop_health = Scripted("finger millet")
    d = analyze(db_client, farmer, language="kn").json()["decision"]
    assert d["item"]["display_name"] == "ರಾಗಿ" and d["item"]["parent_name"] == "ಧಾನ್ಯಗಳು"
    assert d["category_text"] == "ತುಂಬಾ ಉತ್ತಮ"


def test_a_visible_problem_gives_a_lower_category(db_client, db_container, farmer, catalogue):
    db_container.crop_health = Scripted("tomato", symptoms=["brown_spots", "yellowing", "dry_edges"])
    d = analyze(db_client, farmer).json()["decision"]
    assert d["status"] == "needs_attention" and d["health_category"] in ("B", "C")
    assert 0 <= d["health_score"] < 66.67


@pytest.mark.parametrize(
    ("seen", "flags", "reason"), [("spaceship", [], "unidentified"), ("tomato", ["several_items"], "several_items")]
)
def test_uncertain_identification_is_unable_to_classify(
    db_client, db_container, farmer, catalogue, seen, flags, reason
):
    db_container.crop_health = Scripted(seen, flags=flags)
    d = analyze(db_client, farmer).json()["decision"]
    assert (d["status"], d["reason"], d["health_category"], d["category_text"]) == (
        "retake_photo",
        reason,
        None,
        "Unable to classify",
    )


def test_the_farmers_chosen_crop_is_the_item(db_client, db_container, farmer, api, catalogue):
    db_container.crop_health = Scripted("unknown")
    potato = next(
        c
        for c in db_client.get(f"{API}/crops", headers=farmer.headers, params={"search": "Potato"}).json()["items"]
        if c["name"] == "Potato"
    )
    d = analyze(db_client, farmer, crop_id=potato["id"]).json()["decision"]
    assert d["item"]["name"] == "Potato" and d["item"]["source"] == "your_crop"
    assert d["item"]["parent_name"] == "Roots and tubers"


def test_a_fenced_cloud_answer_works_end_to_end(db_client, db_container, farmer, catalogue):
    answer = (
        '```json\n{"description": "Green leaves with no damage.", "shows_plant": true, "close_up": true, '
        '"photo_quality": "good", "symptoms": ["none"], "overall": "healthy", "confidence": "high", '
        '"crop_seen": "groundnut", "plant_part": "leaves", "items_in_photo": "one"}\n```'
    )
    db_container.crop_health = OllamaVisionClassifier(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"message": {"content": answer}}))
        ),
        base_url="https://ollama.com",
        model="gemma4:31b",
        fallback=ColourHeuristicClassifier(),
    )
    d = analyze(db_client, farmer).json()["decision"]
    assert (d["status"], d["item"]["name"], d["item"]["parent_name"], d["health_category"]) == (
        "healthy",
        "Groundnut",
        "Oilseeds",
        "A",
    )


def test_a_model_failure_is_reported_never_faked(db_client, db_container, farmer, catalogue):
    def down(req):
        raise httpx.ConnectError("unreachable")

    db_container.crop_health = OllamaVisionClassifier(
        client=httpx.Client(transport=httpx.MockTransport(down)),
        base_url="https://ollama.com",
        model="gemma4:31b",
        fallback=ColourHeuristicClassifier(),
    )
    r = analyze(db_client, farmer)
    assert r.status_code == 200
    d = r.json()["decision"]
    assert (d["status"], d["reason"], d["health_score"], d["health_category"]) == (
        "unavailable",
        "unavailable",
        None,
        None,
    )


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"not an image", "unsupported_file_type"),
        (b"", "empty_file"),
        (b"\x89PNG\r\n\x1a\n" + b"0" * 50, "invalid_image"),
    ],
)
def test_upload_failures_are_clear_errors(db_client, farmer, data, code):
    r = analyze(db_client, farmer, data=data)
    assert r.status_code == 422 and r.json()["error"]["code"] == code
