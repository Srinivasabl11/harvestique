"""Crop catalog use cases. Readable by every authenticated user; writable by admins only
(the admin check is enforced at the route; inactive crops are hidden from non-admins here)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.enums import CropCategory, UserRole
from app.core.errors import ConflictError, NotFoundError
from app.models.crop import Crop
from app.repositories.crops import CropRepository
from app.schemas.common import Page
from app.schemas.crops import CropCreate, CropRead, CropUpdate
from app.services._common import apply_changes, conflict_on_integrity

NAME_TAKEN = "A crop with this name already exists"


class CropService:
    def __init__(self, *, session: Session, crops: CropRepository) -> None:
        self._session = session
        self._crops = crops

    def list_crops(
        self,
        *,
        role: UserRole,
        search: str | None,
        category: CropCategory | None,
        include_inactive: bool,
        limit: int,
        offset: int,
    ) -> Page[CropRead]:
        active_only = not (include_inactive and role is UserRole.ADMIN)
        items, total = self._crops.list_page(
            search=search.strip() if search else None,
            category=category,
            active_only=active_only,
            limit=limit,
            offset=offset,
        )
        return Page[CropRead](
            items=[CropRead.model_validate(c) for c in items], total=total, limit=limit, offset=offset
        )

    def get_crop(self, crop_id: uuid.UUID, *, role: UserRole) -> CropRead:
        crop = self._crops.get(crop_id)
        if crop is None or (not crop.is_active and role is not UserRole.ADMIN):
            raise NotFoundError("Crop not found")
        return CropRead.model_validate(crop)

    def create_crop(self, payload: CropCreate) -> CropRead:
        if self._crops.name_taken(payload.name):
            raise ConflictError(NAME_TAKEN, code="crop_name_taken")
        crop = Crop(**payload.model_dump())
        with conflict_on_integrity(self._session, NAME_TAKEN, "crop_name_taken"):
            self._crops.add(crop)
            self._session.commit()
        return CropRead.model_validate(crop)

    def update_crop(self, crop_id: uuid.UUID, payload: CropUpdate) -> CropRead:
        crop = self._crops.get(crop_id)
        if crop is None:
            raise NotFoundError("Crop not found")
        changes = payload.model_dump(exclude_unset=True)
        if "name" in changes and self._crops.name_taken(changes["name"], exclude_id=crop.id):
            raise ConflictError(NAME_TAKEN, code="crop_name_taken")
        apply_changes(crop, changes)
        with conflict_on_integrity(self._session, NAME_TAKEN, "crop_name_taken"):
            self._session.commit()
        return CropRead.model_validate(crop)

    def delete_crop(self, crop_id: uuid.UUID) -> None:
        crop = self._crops.get(crop_id)
        if crop is None:
            raise NotFoundError("Crop not found")
        with conflict_on_integrity(
            self._session,
            "This crop is used by farmers' crops or income plans. Deactivate it instead of deleting it.",
            "crop_in_use",
        ):
            self._crops.delete(crop)
            self._session.commit()
