"""Virtual harvest inventory: states, safe commitments, no negatives, no over-allocation, no double booking."""

from __future__ import annotations

import contextlib
import threading
import uuid
from decimal import Decimal

import pytest

from app.composition import build_inventory_service
from app.core.errors import ConflictError
from app.repositories.intelligence import InventoryRepository
from app.schemas.intelligence import ReservationIn
from tests.conftest import days_from_today, harvest, predict

pytestmark = pytest.mark.integration
API = "/api/v1"


@pytest.fixture
def lot(db_client, farmer, growing):
    p = predict(db_client, farmer, growing["id"])
    lots = db_client.get(f"{API}/inventory/lots", headers=farmer.headers).json()["items"]
    assert len(lots) == 1
    return {**lots[0], "_prediction": p}


def reserve(client, actor, lot_id, qty, key="order-1"):
    return client.post(
        f"{API}/inventory/lots/{lot_id}/reservations",
        headers=actor.headers,
        json={"quantity_kg": qty, "booking_key": key},
    )


def get_lot(client, actor, lot_id):
    return client.get(f"{API}/inventory/lots/{lot_id}", headers=actor.headers).json()


def test_lot_is_created_from_the_prediction_and_promises_only_p10(lot):
    q = lot["_prediction"]["quantity_kg"]
    assert lot["status"] == "open" and lot["committable_kg"] == q["p10"] and lot["available_kg"] == q["p10"]
    assert (lot["p50_kg"], lot["p90_kg"], lot["committed_kg"], lot["shortfall_kg"]) == (q["p50"], q["p90"], 0, 0)
    assert "p10" in lot["basis"]


def test_reserving_reduces_availability(db_client, farmer, lot):
    r = reserve(db_client, farmer, lot["id"], 100)
    assert r.status_code == 201 and r.json()["status"] == "active"
    after = get_lot(db_client, farmer, lot["id"])
    assert after["committed_kg"] == 100 and after["available_kg"] == pytest.approx(lot["available_kg"] - 100)
    assert [x["booking_key"] for x in after["reservations"]] == ["order-1"]


def test_over_allocation_is_refused(db_client, farmer, lot):
    r = reserve(db_client, farmer, lot["id"], lot["available_kg"] + 0.001)
    assert r.status_code == 409 and r.json()["error"]["code"] == "over_allocation"
    assert (
        reserve(db_client, farmer, lot["id"], lot["available_kg"], key="all").status_code == 201
    )  # exactly all is fine
    assert reserve(db_client, farmer, lot["id"], 0.001, key="one-more").json()["error"]["code"] == "over_allocation"
    assert get_lot(db_client, farmer, lot["id"])["available_kg"] == 0


def test_double_booking_is_refused(db_client, farmer, lot):
    assert reserve(db_client, farmer, lot["id"], 10, key="trader-42").status_code == 201
    r = reserve(db_client, farmer, lot["id"], 10, key="trader-42")
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_booking"
    assert get_lot(db_client, farmer, lot["id"])["committed_kg"] == 10


@pytest.mark.parametrize(
    "body",
    [
        {"quantity_kg": 0, "booking_key": "a"},
        {"quantity_kg": -5, "booking_key": "a"},
        {"quantity_kg": 5, "booking_key": ""},
        {"quantity_kg": 5, "booking_key": "has space"},
        {"quantity_kg": 5},
    ],
)
def test_invalid_reservations(db_client, farmer, lot, body):
    assert (
        db_client.post(f"{API}/inventory/lots/{lot['id']}/reservations", headers=farmer.headers, json=body).status_code
        == 422
    )


def test_release_frees_the_quantity(db_client, farmer, lot):
    res = reserve(db_client, farmer, lot["id"], 100).json()
    r = db_client.post(f"{API}/inventory/reservations/{res['id']}/release", headers=farmer.headers)
    assert r.status_code == 200 and r.json()["status"] == "released"
    assert get_lot(db_client, farmer, lot["id"])["committed_kg"] == 0
    again = db_client.post(f"{API}/inventory/reservations/{res['id']}/release", headers=farmer.headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "reservation_not_active"
    assert (
        reserve(db_client, farmer, lot["id"], 5, key="order-1").json()["error"]["code"] == "duplicate_booking"
    )  # keys are single-use


def test_a_worse_prediction_puts_commitments_at_risk_without_reallocating(db_client, farmer, growing, lot):
    reserve(db_client, farmer, lot["id"], lot["available_kg"], key="big-order")
    db_client.post(
        f"{API}/crop-cycles/{growing['id']}/observations",
        headers=farmer.headers,
        json={"observed_on": days_from_today(0), "health_status": "damaged", "estimated_loss_percent": 60},
    )
    p2 = predict(db_client, farmer, growing["id"])
    after = get_lot(db_client, farmer, lot["id"])
    assert after["status"] == "at_risk" and after["available_kg"] == 0
    assert after["shortfall_kg"] == pytest.approx(lot["available_kg"] - p2["quantity_kg"]["p10"], abs=0.01)
    assert (
        after["prediction_id"] == p2["id"] and after["reservations"][0]["status"] == "active"
    )  # nothing silently moved
    fulfil = next(c for c in p2["risk"]["categories"] if c["category"] == "fulfilment")
    assert fulfil["level"] in {"medium", "high"}


def test_fulfil_only_after_the_measured_harvest(db_client, farmer, growing, lot):
    res = reserve(db_client, farmer, lot["id"], 100).json()
    early = db_client.post(f"{API}/inventory/reservations/{res['id']}/fulfil", headers=farmer.headers)
    assert early.status_code == 409 and early.json()["error"]["code"] == "not_harvested"
    harvest(db_client, farmer, growing["id"], 15000)
    after = get_lot(db_client, farmer, lot["id"])
    assert after["status"] == "harvested" and after["committable_kg"] == 15000 and after["actual_kg"] == 15000
    done = db_client.post(f"{API}/inventory/reservations/{res['id']}/fulfil", headers=farmer.headers)
    assert done.status_code == 200 and done.json()["status"] == "fulfilled"
    final = get_lot(db_client, farmer, lot["id"])
    assert final["committed_kg"] == 100 and final["available_kg"] == 14900


def test_a_small_actual_harvest_flags_a_shortfall(db_client, farmer, growing, lot):
    reserve(db_client, farmer, lot["id"], lot["available_kg"], key="all")
    harvest(db_client, farmer, growing["id"], 10)
    after = get_lot(db_client, farmer, lot["id"])
    assert after["status"] == "at_risk" and after["shortfall_kg"] == pytest.approx(lot["available_kg"] - 10, abs=0.01)


def test_abandoning_the_cycle_cancels_the_lot(db_client, farmer, growing, lot):
    reserve(db_client, farmer, lot["id"], 50)
    db_client.patch(f"{API}/crop-cycles/{growing['id']}", headers=farmer.headers, json={"status": "abandoned"})
    after = get_lot(db_client, farmer, lot["id"])
    assert after["status"] == "cancelled" and after["committable_kg"] == 0 and after["shortfall_kg"] == 50
    r = reserve(db_client, farmer, lot["id"], 1, key="late")
    assert r.status_code == 409 and r.json()["error"]["code"] == "lot_closed"


def test_inventory_is_private(db_client, farmer, other_farmer, lot):
    res = reserve(db_client, farmer, lot["id"], 10).json()
    assert db_client.get(f"{API}/inventory/lots", headers=other_farmer.headers).json()["total"] == 0
    assert db_client.get(f"{API}/inventory/lots/{lot['id']}", headers=other_farmer.headers).status_code == 404
    assert reserve(db_client, other_farmer, lot["id"], 1, key="x").status_code == 404
    assert (
        db_client.post(f"{API}/inventory/reservations/{res['id']}/release", headers=other_farmer.headers).status_code
        == 404
    )


def test_concurrent_reservations_cannot_overbook(db_container, db_client, farmer, lot, monkeypatch):
    """Two requests that each fit but not together: the lot row lock lets exactly one through."""
    barrier = threading.Barrier(2, timeout=1.5)
    original = InventoryRepository.reservations

    def rendezvous(self, lot_id):  # type: ignore[no-untyped-def]
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait()
        return original(self, lot_id)

    monkeypatch.setattr(InventoryRepository, "reservations", rendezvous)
    share = Decimal(str(lot["available_kg"])) * Decimal("0.6")
    share = share.quantize(Decimal("0.001"))
    results: list[str] = []

    def attempt(key):
        with db_container.session_factory() as session:
            try:
                build_inventory_service(session).reserve(
                    uuid.UUID(farmer.user_id), uuid.UUID(lot["id"]), ReservationIn(quantity_kg=share, booking_key=key)
                )
                results.append("ok")
            except ConflictError as exc:
                results.append(exc.code)

    threads = [threading.Thread(target=attempt, args=(k,)) for k in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    monkeypatch.undo()
    assert sorted(results) == ["ok", "over_allocation"], results
    assert get_lot(db_client, farmer, lot["id"])["committed_kg"] == pytest.approx(float(share))


def test_lots_say_which_crop_plot_and_farm_they_are(db_client, farmer, lot, growing):
    assert lot["crop_name"] and lot["plot_name"] and lot["farm_name"]
    assert lot["sowing_date"] == growing["sowing_date"]
    detail = get_lot(db_client, farmer, lot["id"])
    assert detail["crop_name"] == lot["crop_name"]
