"""Expense, activity and observation use cases.

All three are owner-scoped through their farm. Cross-references are validated against the
*same* farm, so a record can never point at another farmer's plot or crop cycle.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.enums import ActivityType, ExpenseCategory
from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.domain.farming import is_in_future
from app.models.farm import Farm
from app.models.farm_records import CropObservation, FarmActivity, FarmExpense
from app.repositories.crops import CropCycleRepository
from app.repositories.farm_records import ActivityRepository, ExpenseRepository, ObservationRepository
from app.repositories.farms import FarmRepository, PlotRepository
from app.schemas.common import Page
from app.schemas.farm_records import (
    ActivityCreate,
    ActivityRead,
    ActivityUpdate,
    ExpenseCreate,
    ExpenseRead,
    ExpenseUpdate,
    ObservationCreate,
    ObservationRead,
    ObservationUpdate,
)
from app.services._common import apply_changes


def _invalid(message: str, code: str, field: str) -> DomainValidationError:
    return DomainValidationError(message, code=code, details={"field": field})


def _require_farm(farms: FarmRepository, owner_id: uuid.UUID, farm_id: uuid.UUID) -> Farm:
    farm = farms.get_owned(farm_id, owner_id)
    if farm is None:
        raise NotFoundError("Farm not found")
    return farm


def _require_active(farm: Farm) -> None:
    if not farm.is_active:
        raise ConflictError("This farm is archived; un-archive it to add records", code="farm_archived")


def _check_not_future(day: date, today: date, field: str, label: str) -> None:
    if is_in_future(day, today):
        raise _invalid(f"{label} cannot be in the future", f"{field}_in_future", field)


# ================================================================== expenses


class ExpenseService:
    def __init__(
        self,
        *,
        session: Session,
        farms: FarmRepository,
        cycles: CropCycleRepository,
        expenses: ExpenseRepository,
        clock: Clock,
    ) -> None:
        self._session = session
        self._farms = farms
        self._cycles = cycles
        self._expenses = expenses
        self._clock = clock

    def create(self, owner_id: uuid.UUID, farm_id: uuid.UUID, payload: ExpenseCreate) -> ExpenseRead:
        farm = _require_farm(self._farms, owner_id, farm_id)
        _require_active(farm)
        _check_not_future(payload.expense_date, self._clock.now().date(), "expense_date", "Expense date")
        self._check_cycle(farm.id, payload.crop_cycle_id)
        expense = FarmExpense(farm_id=farm.id, **payload.model_dump())
        self._expenses.add(expense)
        self._session.commit()
        return ExpenseRead.model_validate(expense)

    def list_for_farm(
        self,
        owner_id: uuid.UUID,
        farm_id: uuid.UUID,
        *,
        crop_cycle_id: uuid.UUID | None,
        category: ExpenseCategory | None,
        date_from: date | None,
        date_to: date | None,
        limit: int,
        offset: int,
    ) -> Page[ExpenseRead]:
        _require_farm(self._farms, owner_id, farm_id)
        items, total = self._expenses.list_for_farm(
            farm_id,
            crop_cycle_id=crop_cycle_id,
            category=category,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        return Page[ExpenseRead](
            items=[ExpenseRead.model_validate(e) for e in items], total=total, limit=limit, offset=offset
        )

    def get(self, owner_id: uuid.UUID, expense_id: uuid.UUID) -> ExpenseRead:
        return ExpenseRead.model_validate(self._require(owner_id, expense_id))

    def update(self, owner_id: uuid.UUID, expense_id: uuid.UUID, payload: ExpenseUpdate) -> ExpenseRead:
        expense = self._require(owner_id, expense_id)
        changes = payload.model_dump(exclude_unset=True)
        if "expense_date" in changes:
            _check_not_future(changes["expense_date"], self._clock.now().date(), "expense_date", "Expense date")
        if "crop_cycle_id" in changes:
            self._check_cycle(expense.farm_id, changes["crop_cycle_id"])
        apply_changes(expense, changes)
        self._session.commit()
        return ExpenseRead.model_validate(expense)

    def delete(self, owner_id: uuid.UUID, expense_id: uuid.UUID) -> None:
        self._expenses.delete(self._require(owner_id, expense_id))
        self._session.commit()

    def _require(self, owner_id: uuid.UUID, expense_id: uuid.UUID) -> FarmExpense:
        expense = self._expenses.get_owned(expense_id, owner_id)
        if expense is None:
            raise NotFoundError("Expense not found")
        return expense

    def _check_cycle(self, farm_id: uuid.UUID, cycle_id: uuid.UUID | None) -> None:
        if cycle_id is not None and self._cycles.get_in_farm(cycle_id, farm_id) is None:
            raise _invalid("Crop cycle not found on this farm", "crop_cycle_not_in_farm", "crop_cycle_id")


# ================================================================ activities


class ActivityService:
    def __init__(
        self,
        *,
        session: Session,
        farms: FarmRepository,
        plots: PlotRepository,
        cycles: CropCycleRepository,
        activities: ActivityRepository,
        clock: Clock,
    ) -> None:
        self._session = session
        self._farms = farms
        self._plots = plots
        self._cycles = cycles
        self._activities = activities
        self._clock = clock

    def create(self, owner_id: uuid.UUID, farm_id: uuid.UUID, payload: ActivityCreate) -> ActivityRead:
        farm = _require_farm(self._farms, owner_id, farm_id)
        _require_active(farm)
        _check_not_future(payload.activity_date, self._clock.now().date(), "activity_date", "Activity date")
        self._check_links(farm.id, payload.plot_id, payload.crop_cycle_id)
        activity = FarmActivity(farm_id=farm.id, **payload.model_dump())
        self._activities.add(activity)
        self._session.commit()
        return ActivityRead.model_validate(activity)

    def list_for_farm(
        self,
        owner_id: uuid.UUID,
        farm_id: uuid.UUID,
        *,
        plot_id: uuid.UUID | None,
        crop_cycle_id: uuid.UUID | None,
        activity_type: ActivityType | None,
        date_from: date | None,
        date_to: date | None,
        limit: int,
        offset: int,
    ) -> Page[ActivityRead]:
        _require_farm(self._farms, owner_id, farm_id)
        items, total = self._activities.list_for_farm(
            farm_id,
            plot_id=plot_id,
            crop_cycle_id=crop_cycle_id,
            activity_type=activity_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        return Page[ActivityRead](
            items=[ActivityRead.model_validate(a) for a in items], total=total, limit=limit, offset=offset
        )

    def get(self, owner_id: uuid.UUID, activity_id: uuid.UUID) -> ActivityRead:
        return ActivityRead.model_validate(self._require(owner_id, activity_id))

    def update(self, owner_id: uuid.UUID, activity_id: uuid.UUID, payload: ActivityUpdate) -> ActivityRead:
        activity = self._require(owner_id, activity_id)
        changes = payload.model_dump(exclude_unset=True)
        if "activity_date" in changes:
            _check_not_future(changes["activity_date"], self._clock.now().date(), "activity_date", "Activity date")
        if "plot_id" in changes or "crop_cycle_id" in changes:
            self._check_links(
                activity.farm_id,
                changes.get("plot_id", activity.plot_id),
                changes.get("crop_cycle_id", activity.crop_cycle_id),
            )
        apply_changes(activity, changes)
        self._session.commit()
        return ActivityRead.model_validate(activity)

    def delete(self, owner_id: uuid.UUID, activity_id: uuid.UUID) -> None:
        self._activities.delete(self._require(owner_id, activity_id))
        self._session.commit()

    def _require(self, owner_id: uuid.UUID, activity_id: uuid.UUID) -> FarmActivity:
        activity = self._activities.get_owned(activity_id, owner_id)
        if activity is None:
            raise NotFoundError("Activity not found")
        return activity

    def _check_links(self, farm_id: uuid.UUID, plot_id: uuid.UUID | None, cycle_id: uuid.UUID | None) -> None:
        if plot_id is not None:
            plot = self._plots.get(plot_id)
            if plot is None or plot.farm_id != farm_id:
                raise _invalid("Plot not found on this farm", "plot_not_in_farm", "plot_id")
        if cycle_id is not None:
            cycle = self._cycles.get_in_farm(cycle_id, farm_id)
            if cycle is None:
                raise _invalid("Crop cycle not found on this farm", "crop_cycle_not_in_farm", "crop_cycle_id")
            if plot_id is not None and cycle.plot_id != plot_id:
                raise _invalid("This crop cycle is on a different plot", "cycle_plot_mismatch", "crop_cycle_id")


# =============================================================== observations


class ObservationService:
    def __init__(
        self,
        *,
        session: Session,
        cycles: CropCycleRepository,
        observations: ObservationRepository,
        clock: Clock,
    ) -> None:
        self._session = session
        self._cycles = cycles
        self._observations = observations
        self._clock = clock

    def create(self, owner_id: uuid.UUID, cycle_id: uuid.UUID, payload: ObservationCreate) -> ObservationRead:
        cycle = self._cycles.get_owned(cycle_id, owner_id)
        if cycle is None:
            raise NotFoundError("Crop cycle not found")
        self._check_date(payload.observed_on, cycle.sowing_date)
        observation = CropObservation(crop_cycle_id=cycle.id, **payload.model_dump())
        self._observations.add(observation)
        self._session.commit()
        return ObservationRead.model_validate(observation)

    def list_for_cycle(
        self, owner_id: uuid.UUID, cycle_id: uuid.UUID, *, limit: int, offset: int
    ) -> Page[ObservationRead]:
        if self._cycles.get_owned(cycle_id, owner_id) is None:
            raise NotFoundError("Crop cycle not found")
        items, total = self._observations.list_for_cycle(cycle_id, limit=limit, offset=offset)
        return Page[ObservationRead](
            items=[ObservationRead.model_validate(o) for o in items], total=total, limit=limit, offset=offset
        )

    def get(self, owner_id: uuid.UUID, observation_id: uuid.UUID) -> ObservationRead:
        return ObservationRead.model_validate(self._require(owner_id, observation_id))

    def update(self, owner_id: uuid.UUID, observation_id: uuid.UUID, payload: ObservationUpdate) -> ObservationRead:
        observation = self._require(owner_id, observation_id)
        changes = payload.model_dump(exclude_unset=True)
        if "observed_on" in changes:
            cycle = self._cycles.get(observation.crop_cycle_id)
            if cycle is None:  # unreachable: FK RESTRICT guarantees the parent exists
                raise NotFoundError("Crop cycle not found")
            self._check_date(changes["observed_on"], cycle.sowing_date)
        apply_changes(observation, changes)
        self._session.commit()
        return ObservationRead.model_validate(observation)

    def delete(self, owner_id: uuid.UUID, observation_id: uuid.UUID) -> None:
        self._observations.delete(self._require(owner_id, observation_id))
        self._session.commit()

    def _require(self, owner_id: uuid.UUID, observation_id: uuid.UUID) -> CropObservation:
        observation = self._observations.get_owned(observation_id, owner_id)
        if observation is None:
            raise NotFoundError("Observation not found")
        return observation

    def _check_date(self, observed_on: date, sowing_date: date) -> None:
        if observed_on < sowing_date:
            raise _invalid(
                "An observation cannot be dated before the crop was sown", "observation_before_sowing", "observed_on"
            )
        _check_not_future(observed_on, self._clock.now().date(), "observed_on", "Observation date")
