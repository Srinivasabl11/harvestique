"""Helpers shared by services."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, DomainValidationError
from app.domain.planning.models import PlanningInputError


@contextmanager
def conflict_on_integrity(session: Session, message: str, code: str) -> Iterator[None]:
    """Translate a database integrity failure (lost race on a unique key, or deleting a row that
    still has dependants under a RESTRICT foreign key) into a clean 409."""
    try:
        yield
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(message, code=code) from exc


def apply_changes(entity: object, changes: dict[str, Any]) -> None:
    for field, value in changes.items():
        setattr(entity, field, value)


@contextmanager
def planning_errors() -> Iterator[None]:
    """Translate the pure planning engine's input errors into the API's 422 envelope."""
    try:
        yield
    except PlanningInputError as exc:
        raise DomainValidationError(
            exc.message, code=exc.code, details={"field": exc.field} if exc.field else None
        ) from exc


def to_jsonable(value: Any) -> Any:
    """Dataclasses/Decimals/dates/enums -> JSON-safe values (Decimals as strings: exact, never float-rounded)."""
    import dataclasses
    from datetime import date
    from decimal import Decimal
    from enum import Enum

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(v) for v in value]
    return value
