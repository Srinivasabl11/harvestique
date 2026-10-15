"""Stateless planning use cases: the calculator and the land allocator. No database involved."""

from __future__ import annotations

from app.domain.planning import AllocationInput, PlanInput, evaluate_plan, suggest_allocation
from app.schemas.planning import AllocationRequestIn, CalcItem, CalcRequest
from app.schemas.planning_results import AllocationOut, AllocationResponse, ExcludedOut, PlanResultOut
from app.services._common import planning_errors
from app.services.planning_mapping import from_calc_item, from_candidate


class PlanningService:
    def calculate(self, request: CalcRequest) -> PlanResultOut:
        """Cost, yield/revenue range, margin, break-even, land use, income continuity, risk, confidence."""
        with planning_errors():
            plan = PlanInput(
                available_land_acres=request.available_land_acres,
                season=request.season,
                items=tuple(from_calc_item(i) for i in request.items),
                budget_inr=request.budget_inr,
                available_water_kl=request.available_water_kl,
                available_labour_person_days=request.available_labour_person_days,
            )
            return PlanResultOut.model_validate(evaluate_plan(plan))

    def suggest_allocation(self, request: AllocationRequestIn) -> AllocationResponse:
        """Split the land between the candidate crops (greedy, deterministic, explained), then evaluate the split."""
        with planning_errors():
            output = suggest_allocation(
                AllocationInput(
                    available_land_acres=request.available_land_acres,
                    season=request.season,
                    candidates=tuple(from_candidate(c) for c in request.candidates),
                    budget_inr=request.budget_inr,
                    available_water_kl=request.available_water_kl,
                    available_labour_person_days=request.available_labour_person_days,
                    rank_by=request.rank_by,
                    max_crop_share_pct=request.max_crop_share_pct,
                )
            )

            suggested: list[CalcItem] = []
            for allocation in output.allocations:
                candidate = request.candidates[allocation.candidate_index]
                data = candidate.model_dump(exclude={"min_area_acres", "max_area_acres"})
                suggested.append(CalcItem(**data, area_acres=allocation.area_acres))

            evaluation: PlanResultOut | None = None
            if suggested:
                plan = PlanInput(
                    available_land_acres=request.available_land_acres,
                    season=request.season,
                    items=tuple(from_calc_item(i) for i in suggested),
                    budget_inr=request.budget_inr,
                    available_water_kl=request.available_water_kl,
                    available_labour_person_days=request.available_labour_person_days,
                )
                evaluation = PlanResultOut.model_validate(evaluate_plan(plan))

            return AllocationResponse(
                rank_by=output.rank_by,
                ranking=list(output.ranking),
                allocations=[AllocationOut.model_validate(a) for a in output.allocations],
                excluded=[ExcludedOut.model_validate(e) for e in output.excluded],
                notes=list(output.notes),
                suggested_items=suggested,
                plan=evaluation,
            )
