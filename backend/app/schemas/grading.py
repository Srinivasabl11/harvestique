"""Produce quality grading (A/B/C) of a recorded harvest: farmer-facing request and response models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.core.enums import QualityGrade
from app.schemas.base import StrictModel

GradingStatus = Literal["not_graded", "needs_review", "graded"]
ProposalStatus = Literal["proposed", "needs_more_evidence", "retake_photo", "unavailable"]


class GradingProposalOut(BaseModel):
    status: ProposalStatus = Field(
        description="proposed (every check rated from the photo; review it), needs_more_evidence (some checks are "
        "open: rate them yourself), retake_photo (the photo could not be used) or unavailable (AI not reachable: "
        "grade with the checklist)"
    )
    reason: str
    message: str = Field(description="What happened, in the request's language")
    levels: dict[str, int] = Field(description="Check id -> 0 best, 1 middle, 2 worst; only what the photo showed")
    open_checks: list[str] = Field(description="Checks the photo could not rate; the farmer must rate them")
    proposed_grade: QualityGrade | None = Field(description="Only when every check was rated; never final")
    confidence: str | None
    description: str = Field(description="What the AI saw (may be wrong)")
    model: str
    proposed_at: datetime


class ProduceGradingOut(BaseModel):
    crop_cycle_id: uuid.UUID
    harvest_actual_id: uuid.UUID
    crop_name: str
    harvested_kg: float
    status: GradingStatus = Field(
        description="not_graded, needs_review (an AI proposal waits for the farmer) or graded (confirmed)"
    )
    status_text: str
    criteria: dict[str, Any] = Field(description="The checks, their levels, the grade rule and the not-official note")
    proposal: GradingProposalOut | None
    levels: dict[str, int] | None = Field(description="The farmer's confirmed ratings")
    criteria_grade: QualityGrade | None = Field(description="The grade the confirmed ratings support")
    grade: QualityGrade | None = Field(description="The confirmed grade (may be lower than criteria_grade)")
    grade_text: str | None
    grade_source: Literal["manual", "photo_confirmed", "photo_corrected"] | None
    corrected_checks: list[str] = Field(description="Checks where the farmer changed the AI proposal")
    override_reason: str | None
    confirmed_at: datetime | None
    locked: bool = Field(description="Produce reached a collection hub: the hub's measured check now decides")
    lot_expected_grade: QualityGrade | None = Field(description="The grade buyers and pooling see for this lot")
    warnings: list[str]
    is_official: Literal[False] = False


class GradeConfirmIn(StrictModel):
    """The farmer's ratings for every check (0 best .. 2 worst). `grade` defaults to what they support; it may be
    lower (give a reason), never higher."""

    levels: dict[str, int] = Field(min_length=1, max_length=10)
    grade: QualityGrade | None = None
    reason: Annotated[str, StringConstraints(min_length=3, max_length=255)] | None = None
    language: Literal["en", "kn"] = "en"

    @model_validator(mode="after")
    def _levels_in_range(self) -> GradeConfirmIn:
        for key, value in self.levels.items():
            if value not in (0, 1, 2):
                raise ValueError(f"levels.{key} must be 0, 1 or 2")
        return self
