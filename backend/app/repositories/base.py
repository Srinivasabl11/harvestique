"""Generic repository. Concrete repositories subclass this per aggregate."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.base import Base


class SQLAlchemyRepository[ModelT: Base]:
    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, entity_id: uuid.UUID) -> ModelT | None:
        return self.session.get(self.model, entity_id)

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        self.session.flush()
        return entity

    def delete(self, entity: ModelT) -> None:
        self.session.delete(entity)
        self.session.flush()

    def list(self, *, limit: int = 50, offset: int = 0) -> list[ModelT]:
        stmt = select(self.model).limit(limit).offset(offset)
        return list(self.session.scalars(stmt))


def paginate[T](session: Session, stmt: Select[tuple[T]], *, limit: int, offset: int) -> tuple[list[T], int]:
    """Run an (already ordered) SELECT as one page and return (items, total matching rows)."""
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = list(session.scalars(stmt.limit(limit).offset(offset)))
    return items, total
