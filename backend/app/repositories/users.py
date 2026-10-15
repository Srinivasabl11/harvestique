"""User persistence."""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.enums import AccessStatus, UserRole
from app.models.user import User
from app.repositories.base import SQLAlchemyRepository


class UserRepository(SQLAlchemyRepository[User]):
    model = User

    def get_by_phone(self, phone: str) -> User | None:
        return self.session.scalar(select(User).where(User.phone == phone))

    def get_by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(User.email == email.lower()))

    def list_page(
        self, *, limit: int, offset: int, role: UserRole | None = None, access: AccessStatus | None = None
    ) -> tuple[list[User], int]:
        stmt = select(User)
        count_stmt = select(func.count()).select_from(User)
        if role is not None:
            stmt = stmt.where(User.role == role)
            count_stmt = count_stmt.where(User.role == role)
        if access is not None:
            stmt = stmt.where(User.access_status == access)
            count_stmt = count_stmt.where(User.access_status == access)
        items = list(self.session.scalars(stmt.order_by(User.created_at, User.id).limit(limit).offset(offset)))
        return items, self.session.scalar(count_stmt) or 0
