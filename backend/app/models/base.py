"""Declarative base, naming conventions and shared column mixins."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Any, ClassVar

from sqlalchemy import DateTime, Enum, MetaData, Numeric, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names -> stable, reviewable Alembic migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: DateTime(timezone=True),
        Decimal: Numeric(14, 3),  # quantities in kg with gram precision
    }


def enum_column(enum_cls: type[PyEnum], *, name: str, length: int) -> Enum:
    """Portable enum column: VARCHAR + CHECK constraint (no native PG enum type), storing values."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        length=length,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now(), nullable=False)


class VersionedMixin:
    """Optimistic locking for rows edited concurrently (pools, allocations)."""

    version: Mapped[int] = mapped_column(nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012
