"""Farm and plot use cases.

Ownership: every method takes the caller's `owner_id` and only ever loads rows scoped to it.
A farm/plot that belongs to someone else is reported as 404 - its existence is not revealed.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.domain.farming import Occupancy, cycle_end_date, peak_concurrent_area
from app.models.farm import Farm, FarmPlot
from app.repositories.crops import CropCycleRepository
from app.repositories.farms import FarmRepository, PlotRepository
from app.schemas.common import Page
from app.schemas.farms import FarmCreate, FarmRead, FarmUpdate, PlotCreate, PlotRead, PlotUpdate
from app.services._common import apply_changes, conflict_on_integrity


def _acres(value: Decimal) -> float:
    return float(value)


class FarmService:
    def __init__(self, *, session: Session, farms: FarmRepository, plots: PlotRepository) -> None:
        self._session = session
        self._farms = farms
        self._plots = plots

    def create(self, owner_id: uuid.UUID, payload: FarmCreate) -> FarmRead:
        if self._farms.name_taken(owner_id, payload.name):
            raise ConflictError("You already have a farm with this name", code="farm_name_taken")
        farm = Farm(owner_id=owner_id, **payload.model_dump())
        with conflict_on_integrity(self._session, "You already have a farm with this name", "farm_name_taken"):
            self._farms.add(farm)
            self._session.commit()
        return FarmRead.model_validate(farm)

    def list_owned(self, owner_id: uuid.UUID, *, include_archived: bool, limit: int, offset: int) -> Page[FarmRead]:
        items, total = self._farms.list_owned(owner_id, include_archived=include_archived, limit=limit, offset=offset)
        return Page[FarmRead](
            items=[FarmRead.model_validate(f) for f in items], total=total, limit=limit, offset=offset
        )

    def get(self, owner_id: uuid.UUID, farm_id: uuid.UUID) -> FarmRead:
        return FarmRead.model_validate(self._require(owner_id, farm_id))

    def update(self, owner_id: uuid.UUID, farm_id: uuid.UUID, payload: FarmUpdate) -> FarmRead:
        farm = self._farms.get_owned_for_update(farm_id, owner_id)
        if farm is None:
            raise NotFoundError("Farm not found")
        changes = payload.model_dump(exclude_unset=True)

        if "name" in changes and self._farms.name_taken(owner_id, changes["name"], exclude_id=farm.id):
            raise ConflictError("You already have a farm with this name", code="farm_name_taken")

        if "total_area_acres" in changes:
            plotted = self._plots.total_area(farm.id)
            if changes["total_area_acres"] < plotted:
                raise DomainValidationError(
                    f"Farm area cannot be smaller than the {plotted} acres already divided into plots",
                    code="farm_area_below_plots",
                    details={"field": "total_area_acres", "plotted_area_acres": _acres(plotted)},
                )

        latitude = changes.get("latitude", farm.latitude)
        longitude = changes.get("longitude", farm.longitude)
        if (latitude is None) != (longitude is None):
            raise DomainValidationError(
                "latitude and longitude must be provided together", code="coordinates_incomplete"
            )

        apply_changes(farm, changes)
        with conflict_on_integrity(self._session, "You already have a farm with this name", "farm_name_taken"):
            self._session.commit()
        return FarmRead.model_validate(farm)

    def delete(self, owner_id: uuid.UUID, farm_id: uuid.UUID) -> None:
        farm = self._require(owner_id, farm_id)
        with conflict_on_integrity(
            self._session,
            "This farm still has plots, expenses, activities or crop plans. Archive it instead of deleting it.",
            "farm_not_empty",
        ):
            self._farms.delete(farm)
            self._session.commit()

    def _require(self, owner_id: uuid.UUID, farm_id: uuid.UUID) -> Farm:
        farm = self._farms.get_owned(farm_id, owner_id)
        if farm is None:
            raise NotFoundError("Farm not found")
        return farm


class PlotService:
    def __init__(
        self,
        *,
        session: Session,
        farms: FarmRepository,
        plots: PlotRepository,
        cycles: CropCycleRepository,
    ) -> None:
        self._session = session
        self._farms = farms
        self._plots = plots
        self._cycles = cycles

    def create(self, owner_id: uuid.UUID, farm_id: uuid.UUID, payload: PlotCreate) -> PlotRead:
        farm = self._farms.get_owned_for_update(farm_id, owner_id)  # lock: serialises area accounting
        if farm is None:
            raise NotFoundError("Farm not found")
        if not farm.is_active:
            raise ConflictError("This farm is archived; un-archive it to add plots", code="farm_archived")
        if self._plots.name_taken(farm.id, payload.name):
            raise ConflictError("This farm already has a plot with this name", code="plot_name_taken")
        self._check_fits_in_farm(farm, payload.area_acres, exclude_plot_id=None)

        plot = FarmPlot(farm_id=farm.id, **payload.model_dump())
        with conflict_on_integrity(self._session, "This farm already has a plot with this name", "plot_name_taken"):
            self._plots.add(plot)
            self._session.commit()
        return PlotRead.model_validate(plot)

    def list_for_farm(
        self, owner_id: uuid.UUID, farm_id: uuid.UUID, *, include_archived: bool, limit: int, offset: int
    ) -> Page[PlotRead]:
        if self._farms.get_owned(farm_id, owner_id) is None:
            raise NotFoundError("Farm not found")
        items, total = self._plots.list_for_farm(farm_id, include_archived=include_archived, limit=limit, offset=offset)
        return Page[PlotRead](
            items=[PlotRead.model_validate(p) for p in items], total=total, limit=limit, offset=offset
        )

    def get(self, owner_id: uuid.UUID, plot_id: uuid.UUID) -> PlotRead:
        plot = self._plots.get_owned(plot_id, owner_id)
        if plot is None:
            raise NotFoundError("Plot not found")
        return PlotRead.model_validate(plot)

    def update(self, owner_id: uuid.UUID, plot_id: uuid.UUID, payload: PlotUpdate) -> PlotRead:
        found = self._plots.get_owned(plot_id, owner_id)
        if found is None:
            raise NotFoundError("Plot not found")
        # Lock order is always farm -> plot, so concurrent edits cannot deadlock.
        farm = self._farms.get_owned_for_update(found.farm_id, owner_id)
        plot = self._plots.get_owned_for_update(plot_id, owner_id)
        if farm is None or plot is None:
            raise NotFoundError("Plot not found")
        changes = payload.model_dump(exclude_unset=True)

        if "name" in changes and self._plots.name_taken(farm.id, changes["name"], exclude_id=plot.id):
            raise ConflictError("This farm already has a plot with this name", code="plot_name_taken")

        if "area_acres" in changes:
            new_area: Decimal = changes["area_acres"]
            self._check_fits_in_farm(farm, new_area, exclude_plot_id=plot.id)
            self._check_covers_cycles(plot, new_area)

        apply_changes(plot, changes)
        with conflict_on_integrity(self._session, "This farm already has a plot with this name", "plot_name_taken"):
            self._session.commit()
        return PlotRead.model_validate(plot)

    def delete(self, owner_id: uuid.UUID, plot_id: uuid.UUID) -> None:
        plot = self._plots.get_owned(plot_id, owner_id)
        if plot is None:
            raise NotFoundError("Plot not found")
        with conflict_on_integrity(
            self._session,
            "This plot still has crops or field work recorded on it. Archive it instead of deleting it.",
            "plot_not_empty",
        ):
            self._plots.delete(plot)
            self._session.commit()

    # -------------------------------------------------------------- rules

    def _check_fits_in_farm(self, farm: Farm, plot_area: Decimal, *, exclude_plot_id: uuid.UUID | None) -> None:
        """A plot cannot exceed the farm, and all plots together cannot exceed the farm."""
        if plot_area > farm.total_area_acres:
            raise DomainValidationError(
                f"Plot area ({plot_area} acres) cannot exceed the farm area ({farm.total_area_acres} acres)",
                code="plot_area_exceeds_farm",
                details={"field": "area_acres", "farm_area_acres": _acres(farm.total_area_acres)},
            )
        others = self._plots.total_area(farm.id, exclude_id=exclude_plot_id)
        if others + plot_area > farm.total_area_acres:
            raise DomainValidationError(
                f"Plots would total {others + plot_area} acres, more than the farm's {farm.total_area_acres} acres "
                f"({farm.total_area_acres - others} acres still unallocated)",
                code="plots_exceed_farm_area",
                details={
                    "field": "area_acres",
                    "farm_area_acres": _acres(farm.total_area_acres),
                    "other_plots_area_acres": _acres(others),
                },
            )

    def _check_covers_cycles(self, plot: FarmPlot, new_area: Decimal) -> None:
        """Shrinking a plot below the land its crop cycles occupy at once would orphan them."""
        rows = self._cycles.occupancy_for_plot(plot.id)
        peak = peak_concurrent_area(
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
            for r in rows
        )
        if new_area < peak:
            raise DomainValidationError(
                f"Plot area cannot be smaller than the {peak} acres its crop cycles use at the same time",
                code="plot_area_below_cycles",
                details={"field": "area_acres", "peak_cycle_area_acres": _acres(peak)},
            )
