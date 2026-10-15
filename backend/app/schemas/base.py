"""Shared schema building blocks for request/response DTOs."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints, ValidationInfo, field_validator


class StrictModel(BaseModel):
    """Request base: trims strings and rejects unknown fields (e.g. a smuggled `owner_id`)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class PatchModel(StrictModel):
    """PATCH body: every field optional; explicit `null` is allowed only for nullable columns.

    Subclasses list their required (non-nullable) columns in `non_nullable`, so
    `{"name": null}` is a 422 on that field instead of a database error.
    """

    non_nullable: ClassVar[frozenset[str]] = frozenset()

    @field_validator("*", mode="before")
    @classmethod
    def _reject_null_for_required(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None and info.field_name in cls.non_nullable:
            raise ValueError("This field cannot be null")
        return value


# JSON numbers (not strings) for decimals so mobile clients can parse them directly. Values are
# validated and stored as exact Decimals; only the *output* is converted to a JSON number.
_AS_JSON_NUMBER = PlainSerializer(float, return_type=float, when_used="json")

# Output-only: any Decimal rendered as a JSON number.
JsonNumber = Annotated[Decimal, _AS_JSON_NUMBER]

Acres = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=3), _AS_JSON_NUMBER]
Money = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2), _AS_JSON_NUMBER]
Percent = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2), _AS_JSON_NUMBER]
Latitude = Annotated[Decimal, Field(ge=-90, le=90, max_digits=9, decimal_places=6), _AS_JSON_NUMBER]
Longitude = Annotated[Decimal, Field(ge=-180, le=180, max_digits=9, decimal_places=6), _AS_JSON_NUMBER]

Name120 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Name100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Name80 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Text255 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
