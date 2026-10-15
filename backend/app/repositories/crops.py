"""Crop catalog and crop-cycle persistence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Select, String, cast, exists, func, select

from app.core.enums import CropCategory, CycleStatus
from app.models.crop import Crop, CropCycle
from app.models.farm import Farm, FarmPlot
from app.repositories.base import SQLAlchemyRepository, paginate


class CropRepository(SQLAlchemyRepository[Crop]):
    model = Crop

    def get_by_name(self, name: str) -> Crop | None:
        return self.session.scalar(select(Crop).where(func.lower(Crop.name) == name.lower()))

    def name_taken(self, name: str, *, exclude_id: uuid.UUID | None = None) -> bool:
        cond = [func.lower(Crop.name) == name.lower()]
        if exclude_id is not None:
            cond.append(Crop.id != exclude_id)
        return bool(self.session.scalar(select(exists().where(*cond))))

    def list_page(
        self, *, search: str | None, category: CropCategory | None, active_only: bool, limit: int, offset: int
    ) -> tuple[list[Crop], int]:
        stmt = select(Crop)
        if active_only:
            stmt = stmt.where(Crop.is_active.is_(True))
        if category is not None:
            stmt = stmt.where(Crop.category == category)
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                func.lower(Crop.name).like(like)
                | func.lower(func.coalesce(Crop.local_name, "")).like(like)
                | func.lower(func.coalesce(Crop.scientific_name, "")).like(like)
                | func.lower(cast(Crop.aliases, String)).like(like)  # "ragi" finds Ragi, "finger millet" too
            )
        return paginate(self.session, stmt.order_by(func.lower(Crop.name), Crop.id), limit=limit, offset=offset)


@dataclass(frozen=True, slots=True)
class CycleOccupancyRow:
    area_acres: Decimal
    sowing_date: date
    expected_harvest_date: date | None
    actual_harvest_date: date | None
    typical_duration_days: int


class CropCycleRepository(SQLAlchemyRepository[CropCycle]):
    model = CropCycle

    def _owned(self) -> Select[tuple[CropCycle]]:
        return (
            select(CropCycle).join(FarmPlot, FarmPlot.id == CropCycle.plot_id).join(Farm, Farm.id == FarmPlot.farm_id)
        )

    def get_owned(self, cycle_id: uuid.UUID, owner_id: uuid.UUID) -> CropCycle | None:
        return self.session.scalar(self._owned().where(CropCycle.id == cycle_id, Farm.owner_id == owner_id))

    def get_in_farm(self, cycle_id: uuid.UUID, farm_id: uuid.UUID) -> CropCycle | None:
        stmt = (
            select(CropCycle)
            .join(FarmPlot, FarmPlot.id == CropCycle.plot_id)
            .where(CropCycle.id == cycle_id, FarmPlot.farm_id == farm_id)
        )
        return self.session.scalar(stmt)

    def list_for_plot(
        self, plot_id: uuid.UUID, *, status: CycleStatus | None, limit: int, offset: int
    ) -> tuple[list[CropCycle], int]:
        stmt = select(CropCycle).where(CropCycle.plot_id == plot_id)
        if status is not None:
            stmt = stmt.where(CropCycle.status == status)
        return paginate(
            self.session, stmt.order_by(CropCycle.sowing_date.desc(), CropCycle.id), limit=limit, offset=offset
        )

    def list_for_farm(
        self, farm_id: uuid.UUID, *, status: CycleStatus | None, limit: int, offset: int
    ) -> tuple[list[CropCycle], int]:
        stmt = select(CropCycle).join(FarmPlot, FarmPlot.id == CropCycle.plot_id).where(FarmPlot.farm_id == farm_id)
        if status is not None:
            stmt = stmt.where(CropCycle.status == status)
        return paginate(
            self.session, stmt.order_by(CropCycle.sowing_date.desc(), CropCycle.id), limit=limit, offset=offset
        )

    def occupancy_for_plot(self, plot_id: uuid.UUID, *, exclude_id: uuid.UUID | None = None) -> list[CycleOccupancyRow]:
        """Every non-abandoned cycle on the plot (these use, or used, the land)."""
        stmt = (
            select(
                CropCycle.area_acres,
                CropCycle.sowing_date,
                CropCycle.expected_harvest_date,
                CropCycle.actual_harvest_date,
                Crop.typical_duration_days,
            )
            .join(Crop, Crop.id == CropCycle.crop_id)
            .where(CropCycle.plot_id == plot_id, CropCycle.status != CycleStatus.ABANDONED)
        )
        if exclude_id is not None:
            stmt = stmt.where(CropCycle.id != exclude_id)
        return [CycleOccupancyRow(*row) for row in self.session.execute(stmt).all()]
