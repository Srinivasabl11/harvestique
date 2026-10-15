"""Translation between API schemas / ORM rows and the pure planning engine's value objects."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.domain.planning import Candidate, CostInputs, ItemInput, Range
from app.models.planning import CropPlanItem
from app.schemas.planning import (
    CalcItem,
    CandidateIn,
    CostIn,
    PlanItemRead,
    PriceRangeIn,
    RangeOut,
    YieldRangeIn,
)

ONE_ACRE = Decimal(1)

# CostIn field -> CropPlanItem column
COST_COLUMNS: dict[str, str] = {
    "seed_per_acre": "seed_cost",
    "fertilizer_per_acre": "fertilizer_cost",
    "pesticide_per_acre": "pesticide_cost",
    "irrigation_per_acre": "irrigation_cost",
    "machinery_per_acre": "machinery_cost",
    "other_per_acre": "other_cost",
    "labour_person_days_per_acre": "labour_person_days",
    "labour_wage_per_day": "labour_wage",
    "fixed_cost": "fixed_cost",
    "overrun_pct": "cost_overrun_pct",
}


def cost_inputs(cost: CostIn) -> CostInputs:
    return CostInputs(
        seed=cost.seed_per_acre,
        fertilizer=cost.fertilizer_per_acre,
        pesticide=cost.pesticide_per_acre,
        irrigation=cost.irrigation_per_acre,
        machinery=cost.machinery_per_acre,
        other=cost.other_per_acre,
        labour_person_days_per_acre=cost.labour_person_days_per_acre,
        labour_wage_per_day=cost.labour_wage_per_day,
        fixed_cost=cost.fixed_cost,
        overrun_pct=cost.overrun_pct,
    )


def _range(r: YieldRangeIn | PriceRangeIn) -> Range:
    return Range(r.low, r.expected, r.high)


def from_calc_item(item: CalcItem) -> ItemInput:
    assert item.crop_name is not None and item.duration_days is not None  # guaranteed by CalcItem validation
    return ItemInput(
        crop_name=item.crop_name,
        area_acres=item.area_acres,
        sowing_date=item.sowing_date,
        duration_days=item.duration_days,
        harvest_window_days=item.harvest_window_days,
        yield_per_acre_kg=_range(item.yield_per_acre_kg),
        price_per_kg=_range(item.price_per_kg),
        cost=cost_inputs(item.cost),
        water_kl_per_acre=item.water_kl_per_acre,
        demand_level=item.demand_level,
        demand_quantity_kg=item.demand_quantity_kg,
        declared_risk=item.declared_risk,
        estimate_basis=item.estimate_basis,
        batches=item.batches,
        batch_interval_days=item.batch_interval_days,
    )


def from_candidate(candidate: CandidateIn) -> Candidate:
    assert candidate.crop_name is not None and candidate.duration_days is not None
    template = ItemInput(
        crop_name=candidate.crop_name,
        area_acres=Decimal(candidate.batches),  # placeholder: the allocator decides the real area
        sowing_date=candidate.sowing_date,
        duration_days=candidate.duration_days,
        harvest_window_days=candidate.harvest_window_days,
        yield_per_acre_kg=_range(candidate.yield_per_acre_kg),
        price_per_kg=_range(candidate.price_per_kg),
        cost=cost_inputs(candidate.cost),
        water_kl_per_acre=candidate.water_kl_per_acre,
        demand_level=candidate.demand_level,
        demand_quantity_kg=candidate.demand_quantity_kg,
        declared_risk=candidate.declared_risk,
        estimate_basis=candidate.estimate_basis,
        batches=candidate.batches,
        batch_interval_days=candidate.batch_interval_days,
    )
    return Candidate(template, candidate.min_area_acres, candidate.max_area_acres)


def from_row(item: CropPlanItem) -> ItemInput:
    """A stored plan item as engine input (catalog season is read live from the linked crop)."""
    return ItemInput(
        crop_name=item.crop_name,
        area_acres=item.area_acres,
        sowing_date=item.sowing_date,
        duration_days=item.duration_days,
        harvest_window_days=item.harvest_window_days,
        yield_per_acre_kg=Range(item.yield_low_kg, item.yield_expected_kg, item.yield_high_kg),
        price_per_kg=Range(item.price_low, item.price_expected, item.price_high),
        cost=CostInputs(
            seed=item.seed_cost,
            fertilizer=item.fertilizer_cost,
            pesticide=item.pesticide_cost,
            irrigation=item.irrigation_cost,
            machinery=item.machinery_cost,
            other=item.other_cost,
            labour_person_days_per_acre=item.labour_person_days,
            labour_wage_per_day=item.labour_wage,
            fixed_cost=item.fixed_cost,
            overrun_pct=item.cost_overrun_pct,
        ),
        water_kl_per_acre=item.water_kl_per_acre,
        demand_level=item.demand_level,
        demand_quantity_kg=item.demand_quantity_kg,
        declared_risk=item.declared_risk,
        estimate_basis=item.estimate_basis,
        batches=item.batches,
        batch_interval_days=item.batch_interval_days,
        crop_season=item.crop.season if item.crop is not None else None,
        has_catalog_crop=item.crop_id is not None,
    )


def cost_columns(cost: CostIn) -> dict[str, Any]:
    dumped = cost.model_dump()
    return {column: dumped[field] for field, column in COST_COLUMNS.items()}


def yield_columns(r: YieldRangeIn) -> dict[str, Decimal]:
    return {"yield_low_kg": r.low, "yield_expected_kg": r.expected, "yield_high_kg": r.high}


def price_columns(r: PriceRangeIn) -> dict[str, Decimal]:
    return {"price_low": r.low, "price_expected": r.expected, "price_high": r.high}


def item_read(item: CropPlanItem) -> PlanItemRead:
    return PlanItemRead(
        id=item.id,
        plan_id=item.plan_id,
        crop_id=item.crop_id,
        crop_name=item.crop_name,
        position=item.position,
        area_acres=item.area_acres,
        sowing_date=item.sowing_date,
        duration_days=item.duration_days,
        harvest_window_days=item.harvest_window_days,
        batches=item.batches,
        batch_interval_days=item.batch_interval_days,
        yield_per_acre_kg=RangeOut(low=item.yield_low_kg, expected=item.yield_expected_kg, high=item.yield_high_kg),
        price_per_kg=RangeOut(low=item.price_low, expected=item.price_expected, high=item.price_high),
        cost=CostIn(
            **{field: getattr(item, column) for field, column in COST_COLUMNS.items()},
        ),
        water_kl_per_acre=item.water_kl_per_acre,
        demand_level=item.demand_level,
        demand_quantity_kg=item.demand_quantity_kg,
        declared_risk=item.declared_risk,
        estimate_basis=item.estimate_basis,
        notes=item.notes,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
