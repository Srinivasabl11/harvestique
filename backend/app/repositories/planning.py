"""Crop plan persistence. Every lookup is scoped to the owning user."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import exists, func, select

from app.models.planning import CropPlan, CropPlanItem
from app.repositories.base import SQLAlchemyRepository, paginate


class CropPlanRepository(SQLAlchemyRepository[CropPlan]):
    model = CropPlan

    def get_owned(self, plan_id: uuid.UUID, owner_id: uuid.UUID) -> CropPlan | None:
        return self.session.scalar(select(CropPlan).where(CropPlan.id == plan_id, CropPlan.owner_id == owner_id))

    def get_owned_for_update(self, plan_id: uuid.UUID, owner_id: uuid.UUID) -> CropPlan | None:
        """Row-locked read: serialises concurrent item additions (the 30-item cap, positions)."""
        stmt = select(CropPlan).where(CropPlan.id == plan_id, CropPlan.owner_id == owner_id).with_for_update()
        return self.session.scalar(stmt)

    def get_many_owned(self, plan_ids: Sequence[uuid.UUID], owner_id: uuid.UUID) -> list[CropPlan]:
        stmt = select(CropPlan).where(CropPlan.id.in_(plan_ids), CropPlan.owner_id == owner_id)
        return list(self.session.scalars(stmt))

    def list_owned(
        self, owner_id: uuid.UUID, *, farm_id: uuid.UUID | None, limit: int, offset: int
    ) -> tuple[list[CropPlan], int]:
        stmt = select(CropPlan).where(CropPlan.owner_id == owner_id)
        if farm_id is not None:
            stmt = stmt.where(CropPlan.farm_id == farm_id)
        stmt = stmt.order_by(CropPlan.updated_at.desc(), CropPlan.id)
        return paginate(self.session, stmt, limit=limit, offset=offset)

    def name_taken(self, owner_id: uuid.UUID, name: str, *, exclude_id: uuid.UUID | None = None) -> bool:
        cond = [CropPlan.owner_id == owner_id, func.lower(CropPlan.name) == name.lower()]
        if exclude_id is not None:
            cond.append(CropPlan.id != exclude_id)
        return bool(self.session.scalar(select(exists().where(*cond))))


class CropPlanItemRepository(SQLAlchemyRepository[CropPlanItem]):
    model = CropPlanItem

    def get_owned(self, item_id: uuid.UUID, owner_id: uuid.UUID) -> CropPlanItem | None:
        stmt = (
            select(CropPlanItem)
            .join(CropPlan, CropPlan.id == CropPlanItem.plan_id)
            .where(CropPlanItem.id == item_id, CropPlan.owner_id == owner_id)
        )
        return self.session.scalar(stmt)
