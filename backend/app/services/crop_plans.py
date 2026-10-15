"""Saved planning scenarios (crop plans): CRUD, evaluation, comparison and duplication.

Only inputs are stored; every evaluation recomputes from them with the deterministic engine.
Plans are scenarios: one that exceeds the land or budget is *saved* (so it can be explored) and reported
as infeasible by its evaluation, rather than rejected.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.enums import FindingSeverity
from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.domain.planning import PlanInput, PlanResult, evaluate_plan
from app.domain.planning.models import MAX_ITEMS
from app.domain.prediction.planning_bridge import PredictionNotUsable, planning_estimate
from app.models.crop import Crop, CropCycle
from app.models.planning import CropPlan, CropPlanItem
from app.repositories.crops import CropRepository
from app.repositories.farms import FarmRepository
from app.repositories.intelligence import PredictionRepository
from app.repositories.planning import CropPlanItemRepository, CropPlanRepository
from app.schemas.common import Page
from app.schemas.intelligence import PlanItemFromPrediction
from app.schemas.planning import (
    CropPlanCreate,
    CropPlanDuplicate,
    CropPlanRead,
    CropPlanSummary,
    CropPlanUpdate,
    PlanItemCreate,
    PlanItemRead,
    PlanItemUpdate,
    YieldRangeIn,
)
from app.schemas.planning_results import CompareResponse, CompareRow, PlanResultOut
from app.services._common import apply_changes, conflict_on_integrity, planning_errors
from app.services.planning_mapping import cost_columns, from_row, item_read, price_columns, yield_columns
from app.services.predictions import PredictionService

NAME_TAKEN = "You already have a crop plan with this name"
COMPARE_NOTE = (
    "Compared on expected values and their ranges. A plan that is not feasible exceeds your land or budget "
    "and is never ranked best. These are estimates, not guarantees."
)


def _invalid(message: str, code: str, field: str) -> DomainValidationError:
    return DomainValidationError(message, code=code, details={"field": field})


def _ensure_unique(items: Sequence[CropPlanItem]) -> None:
    """One entry per crop and sowing date: a second one is a duplicate (stagger with `batches`, or change the date)."""
    seen: set[tuple[str, object]] = set()
    for i in items:
        key = (i.crop_name.strip().lower(), i.sowing_date)
        if key in seen:
            raise ConflictError(
                f"This plan already has {i.crop_name} sown on {i.sowing_date.isoformat()}. "
                "Edit that entry or choose another sowing date.",
                code="duplicate_plan_item",
                details={"crop_name": i.crop_name, "sowing_date": i.sowing_date.isoformat()},
            )
        seen.add(key)


class CropPlanService:
    def __init__(
        self,
        *,
        session: Session,
        plans: CropPlanRepository,
        items: CropPlanItemRepository,
        farms: FarmRepository,
        crops: CropRepository,
    ) -> None:
        self._session = session
        self._plans = plans
        self._items = items
        self._farms = farms
        self._crops = crops

    # ----------------------------------------------------------------- plans

    def create(self, owner_id: uuid.UUID, payload: CropPlanCreate) -> CropPlanRead:
        if self._plans.name_taken(owner_id, payload.name):
            raise ConflictError(NAME_TAKEN, code="plan_name_taken")
        land = self._resolve_land(owner_id, payload.farm_id, payload.available_land_acres)
        plan = CropPlan(
            owner_id=owner_id,
            farm_id=payload.farm_id,
            name=payload.name,
            description=payload.description,
            season=payload.season,
            available_land_acres=land,
            budget_inr=payload.budget_inr,
            available_water_kl=payload.available_water_kl,
            available_labour_person_days=payload.available_labour_person_days,
        )
        built = [self._build_item(item, position) for position, item in enumerate(payload.items)]
        _ensure_unique(built)
        plan.items.extend(built)
        with conflict_on_integrity(self._session, NAME_TAKEN, "plan_name_taken"):
            self._plans.add(plan)
            self._session.commit()
        return self._read(plan)

    def list_owned(
        self, owner_id: uuid.UUID, *, farm_id: uuid.UUID | None, limit: int, offset: int
    ) -> Page[CropPlanSummary]:
        plans, total = self._plans.list_owned(owner_id, farm_id=farm_id, limit=limit, offset=offset)
        rows = [
            CropPlanSummary(
                id=p.id,
                farm_id=p.farm_id,
                name=p.name,
                season=p.season,
                available_land_acres=p.available_land_acres,
                budget_inr=p.budget_inr,
                item_count=len(p.items),
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
            for p in plans
        ]
        return Page[CropPlanSummary](items=rows, total=total, limit=limit, offset=offset)

    def get(self, owner_id: uuid.UUID, plan_id: uuid.UUID) -> CropPlanRead:
        return self._read(self._require(owner_id, plan_id))

    def update(self, owner_id: uuid.UUID, plan_id: uuid.UUID, payload: CropPlanUpdate) -> CropPlanRead:
        plan = self._require(owner_id, plan_id)
        changes = payload.model_dump(exclude_unset=True)
        if "name" in changes and self._plans.name_taken(owner_id, changes["name"], exclude_id=plan.id):
            raise ConflictError(NAME_TAKEN, code="plan_name_taken")
        if "farm_id" in changes or "available_land_acres" in changes:
            farm_id = changes.get("farm_id", plan.farm_id)
            land = changes.get("available_land_acres", plan.available_land_acres)
            changes["available_land_acres"] = self._resolve_land(owner_id, farm_id, land)
        apply_changes(plan, changes)
        with conflict_on_integrity(self._session, NAME_TAKEN, "plan_name_taken"):
            self._session.commit()
        return self._read(plan)

    def delete(self, owner_id: uuid.UUID, plan_id: uuid.UUID) -> None:
        plan = self._require(owner_id, plan_id)
        self._session.delete(plan)  # items are owned parts: removed with the plan
        self._session.commit()

    def duplicate(self, owner_id: uuid.UUID, plan_id: uuid.UUID, payload: CropPlanDuplicate) -> CropPlanRead:
        """Copy a plan with all its items so a variation can be tried without losing the original."""
        source = self._require(owner_id, plan_id)
        if self._plans.name_taken(owner_id, payload.name):
            raise ConflictError(NAME_TAKEN, code="plan_name_taken")
        copy = CropPlan(
            owner_id=owner_id,
            farm_id=source.farm_id,
            name=payload.name,
            description=source.description,
            season=source.season,
            available_land_acres=source.available_land_acres,
            budget_inr=source.budget_inr,
            available_water_kl=source.available_water_kl,
            available_labour_person_days=source.available_labour_person_days,
        )
        columns = [
            c.key for c in CropPlanItem.__table__.columns if c.key not in {"id", "plan_id", "created_at", "updated_at"}
        ]
        for item in source.items:
            copy.items.append(CropPlanItem(**{key: getattr(item, key) for key in columns}))
        with conflict_on_integrity(self._session, NAME_TAKEN, "plan_name_taken"):
            self._plans.add(copy)
            self._session.commit()
        return self._read(copy)

    # ----------------------------------------------------------------- items

    def add_item(self, owner_id: uuid.UUID, plan_id: uuid.UUID, payload: PlanItemCreate) -> PlanItemRead:
        plan = self._plans.get_owned_for_update(plan_id, owner_id)
        if plan is None:
            raise NotFoundError("Crop plan not found")
        self._session.refresh(plan)  # re-read items after taking the lock
        if len(plan.items) >= MAX_ITEMS:
            raise ConflictError(f"A plan can hold at most {MAX_ITEMS} crops", code="too_many_items")
        position = max((i.position for i in plan.items), default=-1) + 1
        item = self._build_item(payload, position)
        _ensure_unique([*plan.items, item])
        plan.items.append(item)
        self._session.flush()
        self._session.commit()
        return item_read(item)

    def add_item_from_prediction(
        self, owner_id: uuid.UUID, plan_id: uuid.UUID, payload: PlanItemFromPrediction
    ) -> PlanItemRead:
        """Bridge Phase 4 -> Phase 3: a saved prediction's p10/p50/p90 become the item's yield range."""
        self._require(owner_id, plan_id)  # the plan in the URL is authorised first (404), then the body
        prediction = PredictionRepository(self._session).get_owned(payload.prediction_id, owner_id)
        if prediction is None:
            raise _invalid("Prediction not found", "prediction_not_found", "prediction_id")
        cycle = self._session.get(CropCycle, prediction.crop_cycle_id)
        assert cycle is not None
        try:
            est = planning_estimate(PredictionService.domain_result(prediction), cycle.sowing_date)
        except PredictionNotUsable as exc:
            raise ConflictError(f"This prediction cannot feed a plan: {exc}", code="prediction_not_usable") from exc
        y = est.yield_per_acre_kg
        item = PlanItemCreate(
            crop_id=cycle.crop_id,
            crop_name=cycle.crop_name,
            area_acres=cycle.area_acres,
            sowing_date=cycle.sowing_date,
            duration_days=est.duration_days,
            harvest_window_days=est.harvest_window_days,
            yield_per_acre_kg=YieldRangeIn(low=y.low, expected=y.expected, high=y.high),
            price_per_kg=payload.price_per_kg,
            cost=payload.cost,
            water_kl_per_acre=payload.water_kl_per_acre,
            demand_level=payload.demand_level,
            demand_quantity_kg=payload.demand_quantity_kg,
            declared_risk=payload.declared_risk,
            estimate_basis=est.estimate_basis,
            notes=payload.notes
            or f"From prediction v{prediction.version} ({prediction.model_name} {prediction.model_version}).",
        )
        return self.add_item(owner_id, plan_id, item)

    def get_item(self, owner_id: uuid.UUID, item_id: uuid.UUID) -> PlanItemRead:
        return item_read(self._require_item(owner_id, item_id))

    def update_item(self, owner_id: uuid.UUID, item_id: uuid.UUID, payload: PlanItemUpdate) -> PlanItemRead:
        item = self._require_item(owner_id, item_id)
        sent = payload.model_fields_set

        if "crop_id" in sent:
            if payload.crop_id is not None:
                crop = self._active_crop(payload.crop_id)
                item.crop_id, item.crop = crop.id, crop
                if "crop_name" not in sent:
                    item.crop_name = crop.name  # re-linking relabels unless a name was sent too
            else:
                item.crop_id, item.crop = None, None
        if payload.yield_per_acre_kg is not None:
            apply_changes(item, yield_columns(payload.yield_per_acre_kg))
        if payload.price_per_kg is not None:
            apply_changes(item, price_columns(payload.price_per_kg))
        if payload.cost is not None:
            apply_changes(item, cost_columns(payload.cost))
        plain = payload.model_dump(exclude_unset=True, exclude={"crop_id", "yield_per_acre_kg", "price_per_kg", "cost"})
        apply_changes(item, plain)

        try:
            with planning_errors():
                from_row(item)  # the stored row must stay evaluable
            _ensure_unique(item.plan.items)
        except (DomainValidationError, ConflictError):
            self._session.rollback()
            raise
        self._session.commit()
        return item_read(item)

    def delete_item(self, owner_id: uuid.UUID, item_id: uuid.UUID) -> None:
        item = self._require_item(owner_id, item_id)
        plan = self._require(owner_id, item.plan_id)
        plan.items.remove(item)
        self._session.commit()

    # ------------------------------------------------------------ evaluation

    def evaluate(self, owner_id: uuid.UUID, plan_id: uuid.UUID) -> PlanResultOut:
        return PlanResultOut.model_validate(self._evaluate(self._require(owner_id, plan_id)))

    def compare(self, owner_id: uuid.UUID, plan_ids: Sequence[uuid.UUID]) -> CompareResponse:
        unique = list(dict.fromkeys(plan_ids))
        if len(unique) < 2:
            raise _invalid("Provide at least two different plan_id values to compare", "compare_needs_two", "plan_id")
        found = {p.id: p for p in self._plans.get_many_owned(unique, owner_id)}
        if len(found) != len(unique):
            raise NotFoundError("Crop plan not found")  # also covers plans owned by someone else

        rows: list[CompareRow] = []
        for plan_id in unique:  # keep the order the caller asked for
            plan = found[plan_id]
            result = PlanResultOut.model_validate(self._evaluate(plan))
            rows.append(
                CompareRow(
                    plan_id=plan.id,
                    name=plan.name,
                    feasible=result.feasible,
                    hard_findings=sum(1 for f in result.findings if f.severity is FindingSeverity.HARD),
                    warnings=sum(1 for f in result.findings if f.severity is FindingSeverity.WARNING),
                    cost=result.totals.cost,
                    revenue=result.totals.revenue,
                    margin=result.totals.margin,
                    roi_expected_pct=result.totals.roi_expected_pct,
                    peak_land_utilization_pct=result.land.peak_utilization_pct,
                    planning_period=result.period,
                    continuity=result.continuity.level,
                    risk=result.risk,
                    confidence=result.confidence,
                )
            )
        feasible = [r for r in rows if r.feasible]
        best = min(feasible, key=lambda r: (-r.margin.expected, r.name.lower(), str(r.plan_id)), default=None)
        return CompareResponse(
            rows=rows, best_expected_margin_plan_id=best.plan_id if best else None, note=COMPARE_NOTE
        )

    # --------------------------------------------------------------- helpers

    def _evaluate(self, plan: CropPlan) -> PlanResult:
        if not plan.items:
            raise ConflictError("Add at least one crop to this plan before evaluating it", code="plan_has_no_items")
        with planning_errors():
            return evaluate_plan(
                PlanInput(
                    available_land_acres=plan.available_land_acres,
                    season=plan.season,
                    items=tuple(from_row(i) for i in plan.items),
                    budget_inr=plan.budget_inr,
                    available_water_kl=plan.available_water_kl,
                    available_labour_person_days=plan.available_labour_person_days,
                )
            )

    def _require(self, owner_id: uuid.UUID, plan_id: uuid.UUID) -> CropPlan:
        plan = self._plans.get_owned(plan_id, owner_id)
        if plan is None:
            raise NotFoundError("Crop plan not found")
        return plan

    def _require_item(self, owner_id: uuid.UUID, item_id: uuid.UUID) -> CropPlanItem:
        item = self._items.get_owned(item_id, owner_id)
        if item is None:
            raise NotFoundError("Crop plan item not found")
        return item

    def _read(self, plan: CropPlan) -> CropPlanRead:
        return CropPlanRead(
            id=plan.id,
            farm_id=plan.farm_id,
            name=plan.name,
            description=plan.description,
            season=plan.season,
            available_land_acres=plan.available_land_acres,
            budget_inr=plan.budget_inr,
            available_water_kl=plan.available_water_kl,
            available_labour_person_days=plan.available_labour_person_days,
            items=[item_read(i) for i in plan.items],
            created_at=plan.created_at,
            updated_at=plan.updated_at,
        )

    def _resolve_land(self, owner_id: uuid.UUID, farm_id: uuid.UUID | None, land: Decimal | None) -> Decimal:
        """Validate the farm link and the land figure against it (defaulting to the farm's area)."""
        if farm_id is None:
            assert land is not None  # CropPlanCreate / an existing plan always supply it
            return land
        farm = self._farms.get_owned(farm_id, owner_id)
        if farm is None:
            raise _invalid("Farm not found", "farm_not_found", "farm_id")
        if land is None:
            return farm.total_area_acres
        if land > farm.total_area_acres:
            raise _invalid(
                f"Available land ({land} acres) cannot exceed the farm's area ({farm.total_area_acres} acres)",
                "plan_land_exceeds_farm",
                "available_land_acres",
            )
        return land

    def _active_crop(self, crop_id: uuid.UUID) -> Crop:
        crop = self._crops.get(crop_id)
        if crop is None:
            raise _invalid("Crop not found in the catalog", "crop_not_found", "crop_id")
        if not crop.is_active:
            raise _invalid("This crop is no longer available", "crop_inactive", "crop_id")
        return crop

    def _build_item(self, payload: PlanItemCreate, position: int) -> CropPlanItem:
        crop = self._active_crop(payload.crop_id) if payload.crop_id is not None else None
        name = payload.crop_name or (crop.name if crop else None)
        duration = payload.duration_days or (crop.typical_duration_days if crop else None)
        assert name is not None and duration is not None  # PlanItemCreate guarantees one source for each
        item = CropPlanItem(
            crop_id=crop.id if crop else None,
            position=position,
            crop_name=name,
            area_acres=payload.area_acres,
            sowing_date=payload.sowing_date,
            duration_days=duration,
            harvest_window_days=payload.harvest_window_days,
            batches=payload.batches,
            batch_interval_days=payload.batch_interval_days,
            water_kl_per_acre=payload.water_kl_per_acre,
            demand_level=payload.demand_level,
            demand_quantity_kg=payload.demand_quantity_kg,
            declared_risk=payload.declared_risk,
            estimate_basis=payload.estimate_basis,
            notes=payload.notes,
            **yield_columns(payload.yield_per_acre_kg),
            **price_columns(payload.price_per_kg),
            **cost_columns(payload.cost),
        )
        item.crop = crop
        with planning_errors():
            from_row(item)  # validate with the engine so every stored item is evaluable
        return item
