"""Land Utilization Planner: split limited land (and money, water, labour) between candidate crops.

A deterministic GREEDY allocator, chosen because every decision can be explained in one sentence:

  1. drop crops whose expected margin per acre is not positive;
  2. rank the rest by expected margin per acre (or by return on cost);
  3. in rank order give each crop the most area that every limit allows, and record which limit
     was binding: land (exact, accounting for crops that do not overlap in time), budget, water,
     labour, demand, the per-crop share cap, or the crop's own maximum.

Greedy is NOT guaranteed to find the best possible split - it finds a good, feasible, reproducible
one and says why. Ties are broken by crop name, then input order, so results never vary run to run.
Budget uses expected (not worst-case) cost, matching the hard check in `evaluate_plan`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_FLOOR, Decimal

from app.core.enums import CropSeason, RankBy
from app.domain.farming import Occupancy
from app.domain.planning.calculator import MONEY, batch_schedules, num, per_acre_variable_margin, q
from app.domain.planning.models import AREA_QUANT, ZERO, BatchSchedule, D, ItemInput, PlanningInputError
from app.domain.planning.timeline import UsageProfile

INFINITY = Decimal("Infinity")
MIN_AREA_DEFAULT = D("0.1")
FULL_SHARE = D(100)
# Order used to name the binding limit when several are equal.
LIMIT_ORDER = ("land", "budget", "water", "labour", "demand", "max_crop_share", "candidate_max_area")


@dataclass(frozen=True, slots=True)
class Candidate:
    """A crop the farmer is willing to grow. `template.area_acres` is ignored (the allocator decides)."""

    template: ItemInput
    min_area_acres: Decimal = MIN_AREA_DEFAULT
    max_area_acres: Decimal | None = None

    def __post_init__(self) -> None:
        if self.min_area_acres <= 0:
            raise PlanningInputError("min_area_not_positive", "min_area_acres must be positive", "min_area_acres")
        if self.max_area_acres is not None and self.max_area_acres < self.min_area_acres:
            raise PlanningInputError(
                "max_area_below_min", "max_area_acres cannot be below min_area_acres", "max_area_acres"
            )


@dataclass(frozen=True, slots=True)
class AllocationInput:
    available_land_acres: Decimal
    season: CropSeason
    candidates: tuple[Candidate, ...]
    budget_inr: Decimal | None = None
    available_water_kl: Decimal | None = None
    available_labour_person_days: Decimal | None = None
    rank_by: RankBy = RankBy.MARGIN_PER_ACRE
    max_crop_share_pct: Decimal = FULL_SHARE  # no crop may hold more than this share of the land at one time

    def __post_init__(self) -> None:
        if self.available_land_acres <= 0:
            raise PlanningInputError(
                "land_not_positive", "available_land_acres must be positive", "available_land_acres"
            )
        if not self.candidates:
            raise PlanningInputError("no_candidates", "At least one candidate crop is required")
        if not 0 < self.max_crop_share_pct <= 100:
            raise PlanningInputError("share_invalid", "max_crop_share_pct must be in (0, 100]", "max_crop_share_pct")
        for name in ("budget_inr", "available_water_kl", "available_labour_person_days"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise PlanningInputError(f"{name}_not_positive", f"{name} must be positive when given", name)


@dataclass(frozen=True, slots=True)
class Allocation:
    candidate_index: int
    crop_name: str
    area_acres: Decimal
    limited_by: str  # which limit stopped it growing (one of LIMIT_ORDER)
    cost_per_acre: Decimal
    margin_per_acre: Decimal  # expected, before fixed cost
    expected_margin: Decimal  # area x margin per acre - fixed cost
    reason: str


@dataclass(frozen=True, slots=True)
class Excluded:
    candidate_index: int
    crop_name: str
    code: str
    reason: str


@dataclass(frozen=True, slots=True)
class AllocationOutput:
    allocations: tuple[Allocation, ...]
    excluded: tuple[Excluded, ...]
    ranking: tuple[int, ...]  # candidate indices, best first
    rank_by: RankBy
    notes: tuple[str, ...]


def _floor_to(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def _land_limit(profile: UsageProfile, windows: Sequence[BatchSchedule], land: Decimal) -> Decimal:
    """The most total area a staggered crop can take without ever exceeding the land.

    Each of its `b` batches holds area/b. On any day, land used = (land used by crops already placed)
    + (area/b) x k, where k is how many of THIS crop's batches are in the ground that day (batches
    overlap when the interval is shorter than a batch's growing + harvest period). Requiring that to
    stay within `land` on every day gives  area <= (land - used_by_others) x b / k.
    Both terms are step functions, so checking each batch's sowing day and each date where other
    crops' usage changes is enough (usage only falls on the other dates).
    """
    b = len(windows)
    first = min(w.sowing_date for w in windows)
    last = max(w.harvest_end for w in windows)
    days = {w.sowing_date for w in windows} | {d for d in profile.dates if first <= d <= last}
    best = INFINITY
    for day in days:
        k = sum(1 for w in windows if w.sowing_date <= day <= w.harvest_end)
        if k:
            best = min(best, (land - profile.at(day)) * b / k)
    return max(best, ZERO)


def suggest_allocation(request: AllocationInput) -> AllocationOutput:
    land = request.available_land_acres
    excluded: list[Excluded] = []
    ranked: list[tuple[tuple[Decimal, Decimal, str, int], int, Decimal, Decimal]] = []

    # ---- 1. screen and rank
    for index, cand in enumerate(request.candidates):
        item = cand.template
        cost_pa, margin_pa, roi = per_acre_variable_margin(item)
        if margin_pa <= 0:
            excluded.append(
                Excluded(
                    index,
                    item.crop_name,
                    "non_positive_margin",
                    f"Expected margin per acre is {num(margin_pa)} (revenue {num(item.yield_per_acre_kg.expected * item.price_per_kg.expected)} "
                    f"minus cost {num(cost_pa)}), so it would not add income.",
                )
            )
            continue
        primary = margin_pa if request.rank_by is RankBy.MARGIN_PER_ACRE else (INFINITY if roi is None else roi)
        key = (-primary, -margin_pa, item.crop_name.lower(), index)
        ranked.append((key, index, cost_pa, margin_pa))
    ranked.sort(key=lambda r: r[0])

    # ---- 2. allocate in rank order
    budget_left: Decimal = request.budget_inr if request.budget_inr is not None else INFINITY
    water_left: Decimal = request.available_water_kl if request.available_water_kl is not None else INFINITY
    labour_left: Decimal = (
        request.available_labour_person_days if request.available_labour_person_days is not None else INFINITY
    )
    occupied: list[Occupancy] = []
    allocations: list[Allocation] = []

    for _, index, cost_pa, margin_pa in ranked:
        cand = request.candidates[index]
        item = cand.template
        b = item.batches
        # Batch windows do not depend on area; use a valid placeholder area (>= 1 acre per batch).
        windows = batch_schedules(replace(item, area_acres=D(b)))
        profile = UsageProfile.build(occupied)

        land_limit = _land_limit(profile, windows, land)

        fixed = item.cost.fixed_cost
        if budget_left == INFINITY:
            budget_limit = INFINITY
        elif budget_left <= fixed:
            budget_limit = ZERO
        else:
            budget_limit = (budget_left - fixed) / cost_pa if cost_pa > 0 else INFINITY

        water_pa = item.water_kl_per_acre or ZERO
        water_limit = INFINITY if (water_left == INFINITY or water_pa == 0) else water_left / water_pa
        labour_pa = item.cost.labour_person_days_per_acre
        labour_limit = INFINITY if (labour_left == INFINITY or labour_pa == 0) else labour_left / labour_pa
        demand_limit = (
            INFINITY if item.demand_quantity_kg is None else item.demand_quantity_kg / item.yield_per_acre_kg.expected
        )
        # The cap is on the land a crop holds at one time, i.e. per batch: staggered batches reuse land over time.
        share_limit = land * request.max_crop_share_pct / D(100) * b
        own_max = cand.max_area_acres if cand.max_area_acres is not None else INFINITY

        limits = {
            "land": land_limit,
            "budget": budget_limit,
            "water": water_limit,
            "labour": labour_limit,
            "demand": demand_limit,
            "max_crop_share": share_limit,
            "candidate_max_area": own_max,
        }
        binding = min(LIMIT_ORDER, key=lambda name: (limits[name], LIMIT_ORDER.index(name)))
        area = _floor_to(limits[binding], AREA_QUANT * b)  # equal batches => a multiple of b thousandths

        if area < cand.min_area_acres or area <= 0:
            excluded.append(
                Excluded(
                    index,
                    item.crop_name,
                    f"insufficient_{binding}",
                    f"Only {num(max(area, ZERO), 3)} acres fit within the {binding.replace('_', ' ')} limit, "
                    f"below the minimum of {num(cand.min_area_acres, 3)} acres.",
                )
            )
            continue

        expected_margin = area * margin_pa - fixed
        if expected_margin <= 0:
            excluded.append(
                Excluded(
                    index,
                    item.crop_name,
                    "fixed_cost_not_recovered",
                    f"At {num(area, 3)} acres the margin ({num(area * margin_pa)}) does not cover the fixed cost ({num(fixed)}).",
                )
            )
            continue

        # commit: consume the resources
        spent = cost_pa * area + fixed
        budget_left -= spent if budget_left != INFINITY else ZERO
        water_left -= water_pa * area if water_left != INFINITY else ZERO
        labour_left -= labour_pa * area if labour_left != INFINITY else ZERO
        probe_final = batch_schedules(replace(item, area_acres=area))
        occupied.extend(Occupancy(s.sowing_date, s.harvest_end, s.area_acres) for s in probe_final)

        allocations.append(
            Allocation(
                candidate_index=index,
                crop_name=item.crop_name,
                area_acres=area,
                limited_by=binding,
                cost_per_acre=q(cost_pa, MONEY),
                margin_per_acre=q(margin_pa, MONEY),
                expected_margin=q(expected_margin, MONEY),
                reason=(
                    f"Ranked #{[r[1] for r in ranked].index(index) + 1} by "
                    f"{request.rank_by.value.replace('_', ' ')}; given {num(area, 3)} acres, limited by "
                    f"{binding.replace('_', ' ')}."
                ),
            )
        )

    notes = (
        "Greedy allocation: crops are filled in rank order. It is deterministic and explainable but not "
        "guaranteed to be the best possible split.",
        "Ranking uses expected values only; evaluate the resulting plan to see the pessimistic and optimistic range.",
    )
    return AllocationOutput(
        allocations=tuple(allocations),
        excluded=tuple(sorted(excluded, key=lambda e: e.candidate_index)),
        ranking=tuple(r[1] for r in ranked),
        rank_by=request.rank_by,
        notes=notes,
    )


__all__ = [
    "Allocation",
    "AllocationInput",
    "AllocationOutput",
    "Candidate",
    "Excluded",
    "suggest_allocation",
]
