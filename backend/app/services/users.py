"""Read use cases over users and role profiles."""

from __future__ import annotations

import uuid

from app.core.enums import AccessStatus, UserRole
from app.core.errors import NotFoundError
from app.repositories.users import UserRepository
from app.schemas.auth import BuyerProfileRead, BuyerProfileUpdate, FarmerProfileRead, FarmerProfileUpdate, UserRead
from app.schemas.common import Page


class UserService:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    def get_user(self, user_id: uuid.UUID) -> UserRead:
        user = self._users.get(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return UserRead.model_validate(user)

    def get_farmer_profile(self, user_id: uuid.UUID) -> FarmerProfileRead:
        user = self._users.get(user_id)
        if user is None or user.farmer_profile is None:
            raise NotFoundError("Farmer profile not found")
        return FarmerProfileRead.model_validate(user.farmer_profile)

    def get_buyer_profile(self, user_id: uuid.UUID) -> BuyerProfileRead:
        user = self._users.get(user_id)
        if user is None or user.buyer_profile is None:
            raise NotFoundError("Buyer profile not found")
        return BuyerProfileRead.model_validate(user.buyer_profile)

    def update_farmer_profile(self, user_id: uuid.UUID, payload: FarmerProfileUpdate) -> FarmerProfileRead:
        user = self._users.get(user_id)
        if user is None or user.farmer_profile is None:
            raise NotFoundError("Farmer profile not found")
        for k, v in payload.model_dump(exclude_unset=True).items():
            setattr(user.farmer_profile, k, v)
        self._users.session.commit()
        return FarmerProfileRead.model_validate(user.farmer_profile)

    def update_buyer_profile(self, user_id: uuid.UUID, payload: BuyerProfileUpdate) -> BuyerProfileRead:
        user = self._users.get(user_id)
        if user is None or user.buyer_profile is None:
            raise NotFoundError("Buyer profile not found")
        for k, v in payload.model_dump(exclude_unset=True).items():
            setattr(user.buyer_profile, k, v)
        self._users.session.commit()
        return BuyerProfileRead.model_validate(user.buyer_profile)

    def list_users(
        self, *, limit: int, offset: int, role: UserRole | None, access: AccessStatus | None = None
    ) -> Page[UserRead]:
        items, total = self._users.list_page(limit=limit, offset=offset, role=role, access=access)
        return Page[UserRead](
            items=[UserRead.model_validate(u) for u in items], total=total, limit=limit, offset=offset
        )
