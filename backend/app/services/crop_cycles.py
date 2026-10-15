"""Crop-cycle use cases and their cross-entity rules.

A crop cycle is one crop grown on (part of) one plot between a sowing date and a harvest.

Rules enforced here:
  * the plot belongs to the caller; the crop exists and is active
  * area <= plot area, and the land in use at any one moment never exceeds the plot
    (cycles may overlap in time - e.g. intercropping - as long as the areas fit)
  * dates: expected harvest after sowing; actual harvest only when harvested, and not before sowing;
    a growing/harvested cycle cannot have a future sowing date
  * status only moves forward (planned -> growing -> harvested; planned/growing -> abandoned)
  * harvested/abandoned cycles are closed to edits
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.enums import CycleStatus
from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.domain.farming import (
    TERMINAL_STATUSES,
    Occupancy,
    can_transition,
    cycle_end_date,
    is_in_future,
    peak_concurrent_area,
)
from app.models.crop import Crop, CropCycle
from app.models.farm import FarmPlot
from app.repositories.crops import CropCycleRepository, CropRepository
from app.repositories.farms import FarmRepository, PlotRepository
from app.schemas.common import Page
from app.schemas.crop_cycles import CropCycleCreate, CropCycleRead, CropCycleUpdate
from app.services._common import apply_changes, conflict_on_integrity


def _fail(message: str, code: str, field: str | None = None) -> DomainValidationError:
    return DomainValidationError(message, code=code, details={"field": field} if field else None)


class CropCycleService:
    def __init__(
        self,
        *,
        session: Session,
        farms: FarmRepository,
        plots: PlotRepository,
        crops: CropRepository,
        cycles: CropCycleRepository,
        clock: Clock,
    ) -> None:
        self._session = session
        self._farms = farms
        self._plots = plots
        self._crops = crops
        self._cycles = cycles
        self._clock = clock

    # --------------------------------------------------------------- create

    def create(self, owner_id: uuid.UUID, plot_id: uuid.UUID, payload: CropCycleCreate) -> CropCycleRead:
        plot = self._plots.get_owned_for_update(plot_id, owner_id)  # lock: serialises capacity accounting
        if plot is None:
            raise NotFoundError("Plot not found")
        farm = self._farms.get(plot.farm_id)
        if not plot.is_active or farm is None or not farm.is_active:
            raise ConflictError("This plot (or its farm) is archived; un-archive it first", code="plot_archived")

        crop = self._crops.get(payload.crop_id)
        if crop is None:
            raise _fail("Crop not found in the catalog", "crop_not_found", "crop_id")
        if not crop.is_active:
            raise _fail("This crop is no longer available for new crop cycles", "crop_inactive", "crop_id")
        if payload.status is CycleStatus.ABANDONED:
            raise _fail("A crop cycle cannot start as abandoned", "invalid_initial_status", "status")

        area = payload.area_acres if payload.area_acres is not None else plot.area_acres
        self._check_dates(
            status=payload.status,
            sowing=payload.sowing_date,
            expected=payload.expected_harvest_date,
            actual=payload.actual_harvest_date,
        )
        self._check_capacity(
            plot,
            crop,
            area=area,
            sowing=payload.sowing_date,
            expected=payload.expected_harvest_date,
            actual=payload.actual_harvest_date,
            exclude_id=None,
        )

        data = payload.model_dump(exclude={"area_acres"})
        cycle = CropCycle(plot_id=plot.id, area_acres=area, **data)
        self._cycles.add(cycle)
        self._session.commit()
        return CropCycleRead.model_validate(cycle)

    # ----------------------------------------------------------------- read

    def list_for_plot(
        self, owner_id: uuid.UUID, plot_id: uuid.UUID, *, status: CycleStatus | None, limit: int, offset: int
    ) -> Page[CropCycleRead]:
        if self._plots.get_owned(plot_id, owner_id) is None:
            raise NotFoundError("Plot not found")
        items, total = self._cycles.list_for_plot(plot_id, status=status, limit=limit, offset=offset)
        return Page[CropCycleRead](
            items=[CropCycleRead.model_validate(c) for c in items], total=total, limit=limit, offset=offset
        )

    def list_for_farm(
        self, owner_id: uuid.UUID, farm_id: uuid.UUID, *, status: CycleStatus | None, limit: int, offset: int
    ) -> Page[CropCycleRead]:
        if self._farms.get_owned(farm_id, owner_id) is None:
            raise NotFoundError("Farm not found")
        items, total = self._cycles.list_for_farm(farm_id, status=status, limit=limit, offset=offset)
        return Page[CropCycleRead](
            items=[CropCycleRead.model_validate(c) for c in items], total=total, limit=limit, offset=offset
        )

    def get(self, owner_id: uuid.UUID, cycle_id: uuid.UUID) -> CropCycleRead:
        return CropCycleRead.model_validate(self._require(owner_id, cycle_id))

    # --------------------------------------------------------------- update

    def update(self, owner_id: uuid.UUID, cycle_id: uuid.UUID, payload: CropCycleUpdate) -> CropCycleRead:
        found = self._require(owner_id, cycle_id)
        plot = self._plots.get_owned_for_update(found.plot_id, owner_id)
        if plot is None:
            raise NotFoundError("Crop cycle not found")
        self._session.refresh(found)  # re-read after taking the lock

        if found.status in TERMINAL_STATUSES:
            raise ConflictError(
                f"This crop cycle is {found.status.value} and can no longer be edited", code="cycle_closed"
            )

        changes = payload.model_dump(exclude_unset=True)
        status: CycleStatus = changes.get("status", found.status)
        if not can_transition(found.status, status):
            raise ConflictError(
                f"A {found.status.value} crop cycle cannot become {status.value}", code="invalid_status_transition"
            )

        sowing: date = changes.get("sowing_date", found.sowing_date)
        expected: date | None = changes.get("expected_harvest_date", found.expected_harvest_date)
        actual: date | None = changes.get("actual_harvest_date", found.actual_harvest_date)
        area: Decimal = changes.get("area_acres", found.area_acres)

        self._check_dates(status=status, sowing=sowing, expected=expected, actual=actual)
        if status is not CycleStatus.ABANDONED:  # an abandoned cycle releases its land
            self._check_capacity(
                plot, found.crop, area=area, sowing=sowing, expected=expected, actual=actual, exclude_id=found.id
            )

        apply_changes(found, changes)
        with conflict_on_integrity(self._session, "The crop cycle could not be saved", "cycle_conflict"):
            self._session.commit()
        return CropCycleRead.model_validate(found)

    def delete(self, owner_id: uuid.UUID, cycle_id: uuid.UUID) -> None:
        cycle = self._require(owner_id, cycle_id)
        with conflict_on_integrity(
            self._session,
            "This crop has records linked to it (expenses, field work, observations, predictions or orders). "
            "Mark it abandoned instead of deleting it.",
            "cycle_not_empty",
        ):
            self._cycles.delete(cycle)
            self._session.commit()

    # ---------------------------------------------------------------- rules

    def _require(self, owner_id: uuid.UUID, cycle_id: uuid.UUID) -> CropCycle:
        cycle = self._cycles.get_owned(cycle_id, owner_id)
        if cycle is None:
            raise NotFoundError("Crop cycle not found")
        return cycle

    def _check_dates(self, *, status: CycleStatus, sowing: date, expected: date | None, actual: date | None) -> None:
        today = self._clock.now().date()
        if expected is not None and expected <= sowing:
            raise _fail(
                "Expected harvest date must be after the sowing date",
                "expected_harvest_before_sowing",
                "expected_harvest_date",
            )
        # Root cause first: if the crop was not sown yet, nothing downstream can have happened.
        if status in (CycleStatus.GROWING, CycleStatus.HARVESTED) and is_in_future(sowing, today):
            raise _fail(
                "A growing or harvested crop cycle cannot have a future sowing date",
                "sowing_date_in_future",
                "sowing_date",
            )
        if status is CycleStatus.HARVESTED:
            if actual is None:
                raise _fail(
                    "A harvested crop cycle needs an actual_harvest_date",
                    "actual_harvest_date_required",
                    "actual_harvest_date",
                )
            if actual < sowing:
                raise _fail(
                    "Actual harvest date cannot be before the sowing date",
                    "actual_harvest_before_sowing",
                    "actual_harvest_date",
                )
            if is_in_future(actual, today):
                raise _fail(
                    "Actual harvest date cannot be in the future", "actual_harvest_in_future", "actual_harvest_date"
                )
        elif actual is not None:
            raise _fail(
                "actual_harvest_date can only be set once the crop cycle is harvested",
                "actual_harvest_date_not_allowed",
                "actual_harvest_date",
            )

    def _check_capacity(
        self,
        plot: FarmPlot,
        crop: Crop,
        *,
        area: Decimal,
        sowing: date,
        expected: date | None,
        actual: date | None,
        exclude_id: uuid.UUID | None,
    ) -> None:
        if area > plot.area_acres:
            raise _fail(
                f"Crop cycle area ({area} acres) cannot exceed the plot area ({plot.area_acres} acres)",
                "cycle_area_exceeds_plot",
                "area_acres",
            )
        occupied = [
            Occupancy(
                start=r.sowing_date,
                end=cycle_end_date(
                    sowing=r.sowing_date,
                    expected_harvest=r.expected_harvest_date,
                    actual_harvest=r.actual_harvest_date,
                    typical_duration_days=r.typical_duration_days,
                ),
                area=r.area_acres,
            )
            for r in self._cycles.occupancy_for_plot(plot.id, exclude_id=exclude_id)
        ]
        this = Occupancy(
            start=sowing,
            end=cycle_end_date(
                sowing=sowing,
                expected_harvest=expected,
                actual_harvest=actual,
                typical_duration_days=crop.typical_duration_days,
            ),
            area=area,
        )
        peak = peak_concurrent_area([*occupied, this])
        if peak > plot.area_acres:
            raise DomainValidationError(
                f"Not enough free land: this crop cycle would put {peak} acres in use at once on a "
                f"{plot.area_acres}-acre plot",
                code="plot_capacity_exceeded",
                details={
                    "field": "area_acres",
                    "plot_area_acres": float(plot.area_acres),
                    "peak_area_acres": float(peak),
                },
            )
