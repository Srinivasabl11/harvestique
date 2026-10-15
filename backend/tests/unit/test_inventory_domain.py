from decimal import Decimal as D

import pytest

from app.core.enums import CycleStatus, LotStatus, ReservationStatus
from app.domain.inventory import InventoryError, check_fulfil, check_release, check_reservation, derive_lot

G, A = CycleStatus.GROWING, CycleStatus.ABANDONED


def test_before_harvest_only_p10_can_be_promised():
    v = derive_lot(G, D(800), None, D(300), D(0))
    assert (v.status, v.committable_kg, v.committed_kg, v.available_kg, v.shortfall_kg) == (
        LotStatus.OPEN,
        D(800),
        D(300),
        D(500),
        D(0),
    )


def test_lower_new_prediction_flags_at_risk_with_shortfall_and_never_negative_available():
    v = derive_lot(G, D(200), None, D(300), D(0))
    assert (v.status, v.available_kg, v.shortfall_kg) == (LotStatus.AT_RISK, D(0), D(100))


def test_measured_harvest_replaces_the_forecast():
    v = derive_lot(CycleStatus.HARVESTED, D(800), D(1000), D(300), D(200))
    assert (v.status, v.committable_kg, v.available_kg, v.basis) == (
        LotStatus.HARVESTED,
        D(1000),
        D(500),
        "measured harvest",
    )


def test_abandoned_cycle_cancels_the_lot():
    v = derive_lot(A, D(800), None, D(300), D(0))
    assert (v.status, v.committable_kg, v.shortfall_kg) == (LotStatus.CANCELLED, D(0), D(300))


def test_no_prediction_means_nothing_committable():
    assert derive_lot(G, None, None, D(0), D(0)).committable_kg == 0


@pytest.mark.parametrize(
    ("qty", "key", "code"),
    [
        (D(0), "k", "quantity_not_positive"),
        (D(-5), "k", "quantity_not_positive"),
        (D(501), "new", "over_allocation"),
        (D(10), "used", "duplicate_booking"),
    ],
)
def test_reservation_rules(qty, key, code):
    with pytest.raises(InventoryError) as exc:
        check_reservation(derive_lot(G, D(800), None, D(300), D(0)), qty, key, {"used"})
    assert exc.value.code == code


def test_exactly_the_available_quantity_can_be_reserved():
    check_reservation(derive_lot(G, D(800), None, D(300), D(0)), D(500), "k", set())


def test_cancelled_lots_accept_nothing():
    with pytest.raises(InventoryError) as exc:
        check_reservation(derive_lot(A, D(800), None, D(0), D(0)), D(1), "k", set())
    assert exc.value.code == "lot_closed"


def test_fulfil_only_after_measured_harvest_and_only_active():
    with pytest.raises(InventoryError) as exc:
        check_fulfil(derive_lot(G, D(800), None, D(300), D(0)), ReservationStatus.ACTIVE)
    assert exc.value.code == "not_harvested"
    check_fulfil(derive_lot(CycleStatus.HARVESTED, D(800), D(900), D(300), D(0)), ReservationStatus.ACTIVE)
    with pytest.raises(InventoryError):
        check_fulfil(derive_lot(CycleStatus.HARVESTED, D(800), D(900), D(300), D(0)), ReservationStatus.RELEASED)
    with pytest.raises(InventoryError):
        check_release(ReservationStatus.FULFILLED)
