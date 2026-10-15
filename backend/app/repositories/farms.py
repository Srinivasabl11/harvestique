"""Farm and plot persistence. Every `get_owned*` query is scoped to the owning user, so a
caller can never load (or even detect) another farmer's rows."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import exists, func, select

from app.models.farm import Farm, FarmPlot
from app.repositories.base import SQLAlchemyRepository, paginate


class FarmRepository(SQLAlchemyRepository[Farm]):
    model = Farm

    def get_owned(self, farm_id: uuid.UUID, owner_id: uuid.UUID) -> Farm | None:
        return self.session.scalar(select(Farm).where(Farm.id == farm_id, Farm.owner_id == owner_id))

    def get_owned_for_update(self, farm_id: uuid.UUID, owner_id: uuid.UUID) -> Farm | None:
        """Row-locked read: serialises concurrent plot/area changes on one farm."""
        stmt = select(Farm).where(Farm.id == farm_id, Farm.owner_id == owner_id).with_for_update()
        return self.session.scalar(stmt)

    def list_owned(
        self, owner_id: uuid.UUID, *, include_archived: bool, limit: int, offset: int
    ) -> tuple[list[Farm], int]:
        stmt = select(Farm).where(Farm.owner_id == owner_id)
        if not include_archived:
            stmt = stmt.where(Farm.is_active.is_(True))
        return paginate(self.session, stmt.order_by(func.lower(Farm.name), Farm.id), limit=limit, offset=offset)

    def name_taken(self, owner_id: uuid.UUID, name: str, *, exclude_id: uuid.UUID | None = None) -> bool:
        cond = [Farm.owner_id == owner_id, func.lower(Farm.name) == name.lower()]
        if exclude_id is not None:
            cond.append(Farm.id != exclude_id)
        return bool(self.session.scalar(select(exists().where(*cond))))


class PlotRepository(SQLAlchemyRepository[FarmPlot]):
    model = FarmPlot

    def get_owned(self, plot_id: uuid.UUID, owner_id: uuid.UUID) -> FarmPlot | None:
        stmt = (
            select(FarmPlot)
            .join(Farm, Farm.id == FarmPlot.farm_id)
            .where(FarmPlot.id == plot_id, Farm.owner_id == owner_id)
        )
        return self.session.scalar(stmt)

    def get_owned_for_update(self, plot_id: uuid.UUID, owner_id: uuid.UUID) -> FarmPlot | None:
        stmt = (
            select(FarmPlot)
            .join(Farm, Farm.id == FarmPlot.farm_id)
            .where(FarmPlot.id == plot_id, Farm.owner_id == owner_id)
            .with_for_update(of=FarmPlot)
        )
        return self.session.scalar(stmt)

    def list_for_farm(
        self, farm_id: uuid.UUID, *, include_archived: bool, limit: int, offset: int
    ) -> tuple[list[FarmPlot], int]:
        stmt = select(FarmPlot).where(FarmPlot.farm_id == farm_id)
        if not include_archived:
            stmt = stmt.where(FarmPlot.is_active.is_(True))
        return paginate(self.session, stmt.order_by(func.lower(FarmPlot.name), FarmPlot.id), limit=limit, offset=offset)

    def total_area(self, farm_id: uuid.UUID, *, exclude_id: uuid.UUID | None = None) -> Decimal:
        """Area already carved into plots (archived plots still occupy the land)."""
        stmt = select(func.coalesce(func.sum(FarmPlot.area_acres), 0)).where(FarmPlot.farm_id == farm_id)
        if exclude_id is not None:
            stmt = stmt.where(FarmPlot.id != exclude_id)
        return Decimal(self.session.scalar(stmt) or 0)

    def name_taken(self, farm_id: uuid.UUID, name: str, *, exclude_id: uuid.UUID | None = None) -> bool:
        cond = [FarmPlot.farm_id == farm_id, func.lower(FarmPlot.name) == name.lower()]
        if exclude_id is not None:
            cond.append(FarmPlot.id != exclude_id)
        return bool(self.session.scalar(select(exists().where(*cond))))
