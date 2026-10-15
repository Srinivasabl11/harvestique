"""Pure marketplace rules: order state machine, participation transitions, quality verification, fulfilment."""

from decimal import Decimal as D

import pytest

from app.core.enums import OrderItemStatus as I
from app.core.enums import OrderStatus as O
from app.core.enums import ParticipationStatus as P
from app.core.enums import QualityGrade as G
from app.core.enums import QualityResult as Q
from app.domain.marketplace import (
    MarketplaceRuleError,
    batch_code,
    check_cancel,
    check_respond,
    fulfil_quantity,
    order_quantities,
    order_status,
    quality_result,
)


@pytest.mark.parametrize(
    ("items", "fulfilled", "batch", "expected"),
    [
        ([I.AWAITING_FARMER, I.ACCEPTED], 0, False, O.PLACED),
        ([I.ACCEPTED, I.ACCEPTED], 0, False, O.CONFIRMED),
        ([I.ACCEPTED, I.DECLINED], 0, False, O.CONFIRMED),  # declined items do not block confirmation once replaced
        ([I.ACCEPTED, I.ACCEPTED], 0, True, O.IN_FULFILMENT),
        ([I.FULFILLED, I.ACCEPTED], 500, True, O.IN_FULFILMENT),
        ([I.FULFILLED, I.FULFILLED], 2000, True, O.FULFILLED),
        ([I.FULFILLED, I.SHORT], 1500, True, O.PARTIALLY_FULFILLED),
        ([I.FULFILLED, I.REMOVED], 1985, True, O.PARTIALLY_FULFILLED),
        ([I.DECLINED, I.REMOVED], 0, False, O.PLACED),  # nothing delivered: waiting for replacement supply
        ([], 0, False, O.PLACED),
    ],
)
def test_order_state(items, fulfilled, batch, expected):
    assert order_status(O.PLACED, items, D(fulfilled), D(2000), batch, accepted_kg=D(2000)) is expected


@pytest.mark.parametrize(("accepted", "expected"), [(250, O.PLACED), (299.999, O.PLACED), (300, O.CONFIRMED)])
def test_an_order_is_confirmed_only_when_farmers_accepted_the_whole_ordered_quantity(accepted, expected):
    """300 kg ordered; both farms asked have accepted but cover only 250 kg: not confirmed (no false 'secured')."""
    status = order_status(O.PLACED, [I.ACCEPTED, I.ACCEPTED], D(0), D(300), False, accepted_kg=D(str(accepted)))
    assert status is expected


def test_order_quantities_split_confirmed_waiting_and_uncovered():
    q = order_quantities(
        [(I.ACCEPTED, D(100)), (I.ACCEPTED, D(120)), (I.AWAITING_FARMER, D(50)), (I.DECLINED, D(40))], D(0), D(300)
    )
    assert (q.confirmed_kg, q.awaiting_kg, q.uncovered_kg) == (220, 50, 30)
    over = order_quantities([(I.ACCEPTED, D(200))], D(0), D(150))
    assert over.uncovered_kg == 0  # never negative
    delivered = order_quantities([(I.FULFILLED, D(90)), (I.ACCEPTED, D(100))], D(90), D(200))
    assert (delivered.confirmed_kg, delivered.uncovered_kg) == (190, 10)


def test_cancelled_order_stays_cancelled():
    assert order_status(O.CANCELLED, [I.ACCEPTED], D(0), D(10), False, accepted_kg=D(10)) is O.CANCELLED


@pytest.mark.parametrize(
    ("part", "item", "decline", "batch", "code"),
    [
        (P.PENDING, I.AWAITING_FARMER, False, False, None),
        (P.PENDING, I.AWAITING_FARMER, True, False, None),
        (P.ACCEPTED, I.ACCEPTED, True, False, None),  # a farmer may change their mind before collection
        (P.ACCEPTED, I.ACCEPTED, False, False, "invalid_transition"),  # accept twice
        (P.DECLINED, I.DECLINED, True, False, "item_closed"),
        (P.WITHDRAWN, I.REMOVED, False, False, "item_closed"),
        (P.ACCEPTED, I.ACCEPTED, True, True, "already_collected"),
        (P.ACCEPTED, I.FULFILLED, True, True, "item_closed"),
    ],
)
def test_participation_transitions(part, item, decline, batch, code):
    if code is None:
        check_respond(part, item, decline=decline, has_batch=batch)
    else:
        with pytest.raises(MarketplaceRuleError) as e:
            check_respond(part, item, decline=decline, has_batch=batch)
        assert e.value.code == code


@pytest.mark.parametrize(
    ("status", "batch", "code"),
    [
        (O.PLACED, False, None),
        (O.CONFIRMED, False, None),
        (O.CONFIRMED, True, "already_collected"),
        (O.FULFILLED, True, "order_closed"),
        (O.CANCELLED, False, "order_closed"),
    ],
)
def test_cancel_rules(status, batch, code):
    if code is None:
        check_cancel(status, batch)
    else:
        with pytest.raises(MarketplaceRuleError) as e:
            check_cancel(status, batch)
        assert e.value.code == code


@pytest.mark.parametrize(
    ("received", "acc", "rej", "grade", "minimum", "result"),
    [
        (100, 100, 0, G.A, G.B, Q.ACCEPTED),
        (100, 90, 10, G.B, G.B, Q.PARTIALLY_ACCEPTED),
        (100, 0, 100, None, G.B, Q.REJECTED),
        (100, 0, 100, G.C, G.B, Q.REJECTED),  # below minimum can still be recorded as rejected
    ],
)
def test_quality_results(received, acc, rej, grade, minimum, result):
    assert quality_result(D(received), D(acc), D(rej), grade, minimum) is result


@pytest.mark.parametrize(
    ("received", "acc", "rej", "grade", "code"),
    [
        (100, 60, 30, G.A, "quantities_mismatch"),  # 90 != 100: weight must balance exactly
        (100, 70, 40, G.A, "quantities_mismatch"),
        (100, 100, 0, None, "grade_required"),
        (100, 100, 0, G.C, "grade_below_order_minimum"),
        (100, -1, 101, G.A, "negative_quantity"),
    ],
)
def test_quality_rejections(received, acc, rej, grade, code):
    with pytest.raises(MarketplaceRuleError) as e:
        quality_result(D(received), D(acc), D(rej), grade, G.B)
    assert e.value.code == code


@pytest.mark.parametrize(("accepted", "committed", "out"), [(500, 450, 450), (395, 400, 395), (0, 300, 0), (10, 0, 0)])
def test_fulfil_quantity_counts_only_accepted_and_never_more_than_committed(accepted, committed, out):
    assert fulfil_quantity(D(accepted), D(committed)) == out


def test_batch_code_format():
    assert batch_code("3f9a2cdeadbeef", "261008") == "HQ-261008-3F9A2C"
