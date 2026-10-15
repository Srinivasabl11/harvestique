"""Persistence for expenses, activities and observations (owner-scoped through the farm)."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from app.core.enums import ActivityType, ExpenseCategory
from app.models.crop import CropCycle
from app.models.farm import Farm, FarmPlot
from app.models.farm_records import CropObservation, FarmActivity, FarmExpense
from app.repositories.base import SQLAlchemyRepository, paginate


class ExpenseRepository(SQLAlchemyRepository[FarmExpense]):
    model = FarmExpense

    def get_owned(self, expense_id: uuid.UUID, owner_id: uuid.UUID) -> FarmExpense | None:
        stmt = (
            select(FarmExpense)
            .join(Farm, Farm.id == FarmExpense.farm_id)
            .where(FarmExpense.id == expense_id, Farm.owner_id == owner_id)
        )
        return self.session.scalar(stmt)

    def list_for_farm(
        self,
        farm_id: uuid.UUID,
        *,
        crop_cycle_id: uuid.UUID | None,
        category: ExpenseCategory | None,
        date_from: date | None,
        date_to: date | None,
        limit: int,
        offset: int,
    ) -> tuple[list[FarmExpense], int]:
        stmt = select(FarmExpense).where(FarmExpense.farm_id == farm_id)
        if crop_cycle_id is not None:
            stmt = stmt.where(FarmExpense.crop_cycle_id == crop_cycle_id)
        if category is not None:
            stmt = stmt.where(FarmExpense.category == category)
        if date_from is not None:
            stmt = stmt.where(FarmExpense.expense_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(FarmExpense.expense_date <= date_to)
        stmt = stmt.order_by(FarmExpense.expense_date.desc(), FarmExpense.id)
        return paginate(self.session, stmt, limit=limit, offset=offset)


class ActivityRepository(SQLAlchemyRepository[FarmActivity]):
    model = FarmActivity

    def get_owned(self, activity_id: uuid.UUID, owner_id: uuid.UUID) -> FarmActivity | None:
        stmt = (
            select(FarmActivity)
            .join(Farm, Farm.id == FarmActivity.farm_id)
            .where(FarmActivity.id == activity_id, Farm.owner_id == owner_id)
        )
        return self.session.scalar(stmt)

    def list_for_farm(
        self,
        farm_id: uuid.UUID,
        *,
        plot_id: uuid.UUID | None,
        crop_cycle_id: uuid.UUID | None,
        activity_type: ActivityType | None,
        date_from: date | None,
        date_to: date | None,
        limit: int,
        offset: int,
    ) -> tuple[list[FarmActivity], int]:
        stmt = select(FarmActivity).where(FarmActivity.farm_id == farm_id)
        if plot_id is not None:
            stmt = stmt.where(FarmActivity.plot_id == plot_id)
        if crop_cycle_id is not None:
            stmt = stmt.where(FarmActivity.crop_cycle_id == crop_cycle_id)
        if activity_type is not None:
            stmt = stmt.where(FarmActivity.activity_type == activity_type)
        if date_from is not None:
            stmt = stmt.where(FarmActivity.activity_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(FarmActivity.activity_date <= date_to)
        stmt = stmt.order_by(FarmActivity.activity_date.desc(), FarmActivity.id)
        return paginate(self.session, stmt, limit=limit, offset=offset)


class ObservationRepository(SQLAlchemyRepository[CropObservation]):
    model = CropObservation

    def get_owned(self, observation_id: uuid.UUID, owner_id: uuid.UUID) -> CropObservation | None:
        stmt = (
            select(CropObservation)
            .join(CropCycle, CropCycle.id == CropObservation.crop_cycle_id)
            .join(FarmPlot, FarmPlot.id == CropCycle.plot_id)
            .join(Farm, Farm.id == FarmPlot.farm_id)
            .where(CropObservation.id == observation_id, Farm.owner_id == owner_id)
        )
        return self.session.scalar(stmt)

    def list_for_cycle(self, crop_cycle_id: uuid.UUID, *, limit: int, offset: int) -> tuple[list[CropObservation], int]:
        stmt = (
            select(CropObservation)
            .where(CropObservation.crop_cycle_id == crop_cycle_id)
            .order_by(CropObservation.observed_on.desc(), CropObservation.id)
        )
        return paginate(self.session, stmt, limit=limit, offset=offset)
