"""Builders for planning-engine tests.

The default item is the worked example used throughout the tests (all numbers hand-checkable):
2 acres of tomato, cost/acre = 17,000 inputs + 60 person-days x 400 labour = 41,000, fixed 5,000
  -> expected cost 87,000;  medium risk -> 10% overrun -> high cost 95,700
yield 8,000 / 12,000 / 16,000 kg per acre, price 8 / 12 / 18 INR per kg
  -> revenue 128,000 / 288,000 / 576,000;  margin 32,300 / 201,000 / 489,000
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from typing import Any

from app.core.enums import CropSeason
from app.domain.planning import CostInputs, ItemInput, PlanInput, Range

TOMATO_COST = CostInputs(
    seed=D(4000),
    fertilizer=D(6000),
    pesticide=D(3000),
    irrigation=D(2000),
    machinery=D(1500),
    other=D(500),
    labour_person_days_per_acre=D(60),
    labour_wage_per_day=D(400),
    fixed_cost=D(5000),
)


def rng(low: Any, expected: Any, high: Any) -> Range:
    return Range(D(str(low)), D(str(expected)), D(str(high)))


def item(**overrides: Any) -> ItemInput:
    values: dict[str, Any] = {
        "crop_name": "Tomato",
        "area_acres": D(2),
        "sowing_date": date(2026, 11, 1),
        "duration_days": 100,
        "harvest_window_days": 30,
        "yield_per_acre_kg": rng(8000, 12000, 16000),
        "price_per_kg": rng(8, 12, 18),
        "cost": TOMATO_COST,
        **overrides,
    }
    return ItemInput(**values)


def simple(
    *, area: Any = 1, y: Any = 1000, price: Any = 10, cost_per_acre: Any = 0, fixed: Any = 0, **kw: Any
) -> ItemInput:
    """A minimal item: a single yield/price (low = expected = high) so results are trivial to verify."""
    return item(
        area_acres=D(str(area)),
        yield_per_acre_kg=rng(y, y, y),
        price_per_kg=rng(price, price, price),
        cost=CostInputs(seed=D(str(cost_per_acre)), fixed_cost=D(str(fixed)), overrun_pct=D(0)),
        **kw,
    )


def plan(*items: ItemInput, land: Any = 5, **kw: Any) -> PlanInput:
    values: dict[str, Any] = {
        "available_land_acres": D(str(land)),
        "season": CropSeason.YEAR_ROUND,
        "items": tuple(items),
        **kw,
    }
    return PlanInput(**values)


# ------------------------------------------------------------- JSON request bodies (HTTP tests)

TOMATO_COST_JSON = {
    "seed_per_acre": 4000,
    "fertilizer_per_acre": 6000,
    "pesticide_per_acre": 3000,
    "irrigation_per_acre": 2000,
    "machinery_per_acre": 1500,
    "other_per_acre": 500,
    "labour_person_days_per_acre": 60,
    "labour_wage_per_day": 400,
    "fixed_cost": 5000,
}


def item_body(**overrides: Any) -> dict[str, Any]:
    """The worked tomato example as a request body (expected cost 87,000; margin 32,300 / 201,000 / 489,000)."""
    body: dict[str, Any] = {
        "crop_name": "Tomato",
        "area_acres": 2,
        "sowing_date": "2026-11-01",
        "duration_days": 100,
        "harvest_window_days": 30,
        "yield_per_acre_kg": {"low": 8000, "expected": 12000, "high": 16000},
        "price_per_kg": {"low": 8, "expected": 12, "high": 18},
        "cost": dict(TOMATO_COST_JSON),
    }
    body.update(overrides)
    return body


def ragi_body(**overrides: Any) -> dict[str, Any]:
    return item_body(
        **{
            "crop_name": "Ragi",
            "area_acres": 4,
            "sowing_date": "2026-06-15",
            "duration_days": 120,
            "harvest_window_days": 15,
            "yield_per_acre_kg": {"low": 600, "expected": 900, "high": 1200},
            "price_per_kg": {"low": 25, "expected": 32, "high": 40},
            "cost": {
                "seed_per_acre": 800,
                "fertilizer_per_acre": 2500,
                "labour_person_days_per_acre": 15,
                "labour_wage_per_day": 400,
            },
            **overrides,
        }
    )


def calc_body(*items: dict[str, Any], land: Any = 5, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"available_land_acres": land, "items": list(items) or [item_body()]}
    body.update(overrides)
    return body


def candidate_body(name: str = "Tomato", **overrides: Any) -> dict[str, Any]:
    body = item_body(crop_name=name)
    del body["area_acres"]
    body.update(overrides)
    return body
