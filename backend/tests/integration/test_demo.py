"""The repeatable end-to-end demo runs through the real API and produces the documented scenario."""

from __future__ import annotations

import pytest

from app.cli.demo import DemoError, reset_database, run_demo
from app.providers.prediction.demo import DemoScriptedPredictor
from app.providers.weather.fake import FakeWeatherProvider

pytestmark = pytest.mark.integration


@pytest.fixture
def demo_container(db_container):
    db_container.predictor = DemoScriptedPredictor()
    db_container.weather = FakeWeatherProvider()
    return db_container


def test_full_demo_scenario(db_client, demo_container):
    logs: list[str] = []
    s = run_demo(db_client, demo_container, log=logs.append)
    assert s["initial_allocation_kg"] == 2000
    assert (s["shortage_kg"], s["replaced_kg"], s["unresolved_kg"], s["reallocation_outcome"]) == (250, 250, 0, "full")
    # quality rejected 10 kg (B) + 5 kg (E): only accepted produce counts, so the order is honestly partial
    assert s["fulfilled_kg"] == 1985 and s["order_status"] == "partially_fulfilled"
    assert set(s["batches"]) == {"A", "B", "C", "D", "E", "F"}
    assert {
        "allocation",
        "farmer_participation",
        "predictions",
        "harvest",
        "collection_batch",
        "quality",
        "fulfilment",
        "prediction_feedback",
    } <= set(s["trace_steps"])
    assert len(logs) == 11 and "SIMULATED" in s["data_note"]
    # prediction feedback: v1 said 450, v2 said 200, the measured harvest was 210
    assert [(v, p) for v, p, _e in s["farm_c_feedback"]] == [(1, 450), (2, 200)]
    assert "v1 predicted 450 kg" in logs[-1] and "v2 predicted 200 kg" in logs[-1]


def test_reset_refuses_a_non_demo_database(demo_container):
    with pytest.raises(DemoError, match="must contain 'demo'"):
        reset_database(demo_container)
