"""Reminders, notifications, suggestions, calendar, admin dashboard and profile updates."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.composition import build_reminder_service
from app.core.clock import FixedClock
from tests.conftest import days_from_today, make_demand, make_pool, predict

pytestmark = pytest.mark.integration
API = "/api/v1"
IST = "+05:30"


def when(days: int, hour: int = 9) -> str:
    d = (datetime.now(UTC) + timedelta(days=days)).date()
    return f"{d.isoformat()}T{hour:02d}:00:00{IST}"


def make_reminder(client, actor, **kw):
    body = {"reminder_type": "irrigation", "title": "Irrigate north plot", "due_at": when(1), **kw}
    r = client.post(f"{API}/reminders", headers=actor.headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def make_due_reminder(client, actor, container, days_ago: int, hour: int = 9, **kw):
    """A reminder that has become due: created for later (past times are refused), then time passes."""
    r = make_reminder(client, actor, **kw)
    with container.engine.begin() as conn:
        conn.execute(text("UPDATE reminders SET due_at = :d WHERE id = :i"), {"d": when(-days_ago, hour), "i": r["id"]})
    return r


def test_reminder_crud_and_validation(db_client, farmer, buyer, api):
    farm = api.farm(farmer)
    r = make_reminder(db_client, farmer, farm_id=farm["id"], notes="Drip line 2")
    assert r["status"] == "pending" and r["source"] == "user"
    assert (
        db_client.post(
            f"{API}/reminders",
            headers=farmer.headers,
            json={"reminder_type": "custom", "title": "x", "due_at": "2026-10-09T09:00:00"},
        ).status_code
        == 422
    )  # no timezone
    assert (
        db_client.post(
            f"{API}/reminders",
            headers=farmer.headers,
            json={"reminder_type": "wizardry", "title": "x", "due_at": when(1)},
        ).status_code
        == 422
    )
    upd = db_client.patch(f"{API}/reminders/{r['id']}", headers=farmer.headers, json={"title": "Irrigate both plots"})
    assert upd.json()["title"] == "Irrigate both plots"
    assert (
        db_client.patch(f"{API}/reminders/{r['id']}", headers=farmer.headers, json={"title": None}).status_code == 422
    )
    done = db_client.post(f"{API}/reminders/{r['id']}/complete", headers=farmer.headers).json()
    assert done["status"] == "done"
    assert db_client.post(f"{API}/reminders/{r['id']}/dismiss", headers=farmer.headers).status_code == 409
    assert db_client.get(f"{API}/reminders/{r['id']}", headers=buyer.headers).status_code == 404  # not yours
    buyer_r = make_reminder(db_client, buyer, reminder_type="collection", title="Visit hub")
    assert buyer_r["reminder_type"] == "collection"
    assert db_client.get(f"{API}/reminders", headers=buyer.headers).json()["total"] == 1


def test_reminders_cannot_point_at_another_farmers_farm(db_client, farmer, other_farmer, api):
    farm = api.farm(farmer)
    r = db_client.post(
        f"{API}/reminders",
        headers=other_farmer.headers,
        json={"reminder_type": "custom", "title": "x", "due_at": when(1), "farm_id": farm["id"]},
    )
    assert r.status_code == 404


def test_recurring_reminder_rolls_forward_and_notifies_once_per_occurrence(db_client, db_container, farmer):
    r = make_due_reminder(db_client, farmer, db_container, 3, 3, recurrence="daily", title="Check water tank")
    feed = db_client.get(f"{API}/notifications", headers=farmer.headers).json()
    assert [n["title"] for n in feed["items"]] == ["Check water tank"]
    db_client.get(f"{API}/notifications", headers=farmer.headers)  # polling again does not duplicate
    assert db_client.get(f"{API}/notifications/unread-count", headers=farmer.headers).json() == {"unread": 1}
    nxt = db_client.post(f"{API}/reminders/{r['id']}/complete", headers=farmer.headers).json()
    assert nxt["status"] == "pending" and datetime.fromisoformat(nxt["due_at"]) > datetime.now(UTC)


def test_due_reminder_processing_is_idempotent_under_concurrency(db_container, db_client, farmer):
    for i in range(5):
        make_due_reminder(db_client, farmer, db_container, 1, 1, title=f"Task {i}")
    counts: list[int] = []
    barrier = threading.Barrier(3)

    def run():
        with db_container.session_factory() as s:
            barrier.wait()
            counts.append(build_reminder_service(s, db_container).process_due())

    ts = [threading.Thread(target=run) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=30)
    assert sum(counts) == 5
    with db_container.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM notifications WHERE category = 'reminder'")) == 5


def test_notifications_read_and_ownership(db_client, db_container, farmer, other_farmer):
    make_due_reminder(db_client, farmer, db_container, 1, title="A")
    make_due_reminder(db_client, farmer, db_container, 1, title="B")
    items = db_client.get(f"{API}/notifications", headers=farmer.headers).json()["items"]
    assert db_client.post(f"{API}/notifications/{items[0]['id']}/read", headers=other_farmer.headers).status_code == 404
    read = db_client.post(f"{API}/notifications/{items[0]['id']}/read", headers=farmer.headers).json()
    assert read["read_at"] is not None
    assert (
        db_client.get(f"{API}/notifications", headers=farmer.headers, params={"unread_only": True}).json()["total"] == 1
    )
    assert db_client.post(f"{API}/notifications/read-all", headers=farmer.headers).json() == {"unread": 0}


def test_suggestions_come_only_from_recorded_data(db_client, farmer, api, crop, db_container):
    farm = api.farm(farmer)
    plot = api.plot(farmer, farm["id"])
    cycle = api.cycle(farmer, plot["id"], crop["id"], status="growing", sowing_date=days_from_today(-45))
    kinds = {
        s["reminder_type"]: s for s in db_client.get(f"{API}/reminders/suggestions", headers=farmer.headers).json()
    }
    assert set(kinds) == {"crop_observation", "expense"}  # nothing recorded yet; no prediction -> no harvest advice
    assert (
        kinds["crop_observation"]["basis"] == "measured"
        and "No field observation" in kinds["crop_observation"]["reason"]
    )
    api.observation(farmer, cycle["id"], health_status="pest_affected", observed_on=days_from_today(-1))
    api.expense(farmer, farm["id"], crop_cycle_id=cycle["id"], expense_date=days_from_today(-2))
    kinds = {s["reminder_type"] for s in db_client.get(f"{API}/reminders/suggestions", headers=farmer.headers).json()}
    assert kinds == {"crop_health"}
    # accepting a suggestion = creating it; then it is not suggested again
    s = db_client.get(f"{API}/reminders/suggestions", headers=farmer.headers).json()[0]
    body = {k: s[k] for k in ("reminder_type", "title", "due_at", "farm_id", "crop_cycle_id")}
    assert (
        db_client.post(f"{API}/reminders", headers=farmer.headers, params={"from_suggestion": True}, json=body).json()[
            "source"
        ]
        == "suggestion"
    )
    assert db_client.get(f"{API}/reminders/suggestions", headers=farmer.headers).json() == []


def test_harvest_suggestion_uses_the_prediction_and_says_it_is_an_estimate(db_client, farmer, api, crop):
    farm = api.farm(farmer)
    plot = api.plot(farmer, farm["id"])
    cycle = api.cycle(
        farmer,
        plot["id"],
        crop["id"],
        status="growing",
        sowing_date=days_from_today(-95),
        expected_harvest_date=days_from_today(7),
    )
    predict(db_client, farmer, cycle["id"])
    harvest = [
        s
        for s in db_client.get(f"{API}/reminders/suggestions", headers=farmer.headers).json()
        if s["reminder_type"] == "harvest"
    ]
    assert len(harvest) == 1 and harvest[0]["basis"] == "estimate" and "an estimate" in harvest[0]["reason"]


def test_calendar(db_client, farmer, buyer, api, crop):
    farm = api.farm(farmer)
    plot = api.plot(farmer, farm["id"])
    cycle = api.cycle(
        farmer,
        plot["id"],
        crop["id"],
        status="growing",
        sowing_date=days_from_today(-10),
        expected_harvest_date=days_from_today(80),
    )
    predict(db_client, farmer, cycle["id"])
    api.activity(farmer, farm["id"], activity_type="weeding", activity_date=days_from_today(-2))
    make_reminder(db_client, farmer, due_at=when(3))
    cal = db_client.get(
        f"{API}/calendar", headers=farmer.headers, params={"start": days_from_today(-30), "end": days_from_today(120)}
    ).json()
    kinds = {e["kind"]: e for e in cal["events"]}
    assert {"sowing", "expected_harvest", "predicted_harvest_window", "activity", "reminder"} <= set(kinds)
    assert (
        kinds["predicted_harvest_window"]["data_kind"] == "estimate" and kinds["sowing"]["data_kind"] == "user_entered"
    )
    assert [e["start"] for e in cal["events"]] == sorted(e["start"] for e in cal["events"])
    assert (
        db_client.get(
            f"{API}/calendar", headers=farmer.headers, params={"start": days_from_today(0), "end": days_from_today(400)}
        ).status_code
        == 422
    )
    assert (
        db_client.get(
            f"{API}/calendar", headers=buyer.headers, params={"start": days_from_today(0), "end": days_from_today(30)}
        ).json()["events"]
        == []
    )


def test_admin_dashboard_reports_real_counts_only(db_client, admin, buyer, pool_world):
    make_pool(db_client, buyer, make_demand(db_client, buyer, pool_world.crop["id"], 2000)["id"])
    d = db_client.get(f"{API}/admin/dashboard", headers=admin.headers).json()
    assert d["users"] == {"admin": 1, "buyer": 1, "farmer": 1} and d["farms"] == 5
    assert d["pools"] == {"filled": 1} and d["available_kg"] == 0 and d["predictions_scored"] == 0
    assert "no accuracy is claimed" in d["calibration_note"]
    assert db_client.get(f"{API}/admin/dashboard", headers=buyer.headers).status_code == 403


def test_profile_updates(db_client, farmer, buyer):
    r = db_client.patch(
        f"{API}/farmers/me", headers=farmer.headers, json={"preferred_language": "kn", "village": "Hunsur"}
    )
    assert r.status_code == 200 and r.json()["preferred_language"] == "kn"
    assert (
        db_client.patch(f"{API}/farmers/me", headers=farmer.headers, json={"preferred_language": None}).status_code
        == 422
    )
    assert (
        db_client.patch(f"{API}/buyers/me", headers=buyer.headers, json={"city": "Mysuru"}).json()["city"] == "Mysuru"
    )
    assert db_client.patch(f"{API}/buyers/me", headers=farmer.headers, json={"city": "x"}).status_code == 403


def test_due_processing_uses_the_injected_clock(db_container, db_client, farmer):
    make_reminder(db_client, farmer, due_at=when(10))
    with db_container.session_factory() as s:
        assert build_reminder_service(s, db_container).process_due() == 0  # not due yet
    db_container.clock = FixedClock(
        datetime.now(UTC) + timedelta(days=11)
    )  # (auth would expire tokens: use the service)
    with db_container.session_factory() as s:
        assert build_reminder_service(s, db_container).process_due() == 1


def test_reminders_cannot_be_set_in_the_past_but_can_be_rescheduled_and_deleted(db_client, farmer, other_farmer):
    r = db_client.post(
        f"{API}/reminders", headers=farmer.headers, json={"reminder_type": "custom", "title": "x", "due_at": when(-1)}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "due_in_past"
    rem = make_reminder(db_client, farmer, title="Spray neem")
    moved = db_client.patch(f"{API}/reminders/{rem['id']}", headers=farmer.headers, json={"due_at": when(3, 7)})
    assert moved.status_code == 200 and moved.json()["due_at"].startswith(when(3, 7)[:10])
    back = db_client.patch(f"{API}/reminders/{rem['id']}", headers=farmer.headers, json={"due_at": when(-2)})
    assert back.status_code == 422
    assert db_client.delete(f"{API}/reminders/{rem['id']}", headers=other_farmer.headers).status_code == 404
    assert db_client.delete(f"{API}/reminders/{rem['id']}", headers=farmer.headers).status_code == 204
    assert db_client.get(f"{API}/reminders/{rem['id']}", headers=farmer.headers).status_code == 404


def test_a_rescheduled_reminder_is_notified_again_at_its_new_time(db_client, db_container, farmer):
    r = make_due_reminder(db_client, farmer, db_container, 1, title="Irrigate")
    assert db_client.get(f"{API}/notifications/unread-count", headers=farmer.headers).json() == {"unread": 1}
    db_client.patch(f"{API}/reminders/{r['id']}", headers=farmer.headers, json={"due_at": when(1)})
    with db_container.engine.begin() as conn:  # the new time arrives
        conn.execute(text("UPDATE reminders SET due_at = :d WHERE id = :i"), {"d": when(0, 0), "i": r["id"]})
    assert db_client.get(f"{API}/notifications/unread-count", headers=farmer.headers).json() == {"unread": 2}
