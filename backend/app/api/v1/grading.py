"""Produce quality grading (A/B/C) of a recorded harvest: optional AI photo proposal, farmer review and confirmation.
Indicative grades by the farmer, not official AGMARK grades; the hub's measured quality check decides acceptance."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.api.deps import FarmerDep, GradingServiceDep
from app.api.responses import ERR, WRITE_ERR
from app.api.v1.assistant import _read_limited
from app.schemas.grading import GradeConfirmIn, ProduceGradingOut

router = APIRouter()


@router.get(
    "/crop-cycles/{cycle_id}/grading",
    response_model=ProduceGradingOut,
    summary="The harvest's quality grade, the checks behind it and any AI proposal waiting for review",
    responses=ERR,
)
def get_grading(
    cycle_id: uuid.UUID,
    farmer: FarmerDep,
    grading: GradingServiceDep,
    language: Annotated[Literal["en", "kn"], Query()] = "en",
) -> ProduceGradingOut:
    return grading.get(farmer.user_id, cycle_id, language)


@router.post(
    "/crop-cycles/{cycle_id}/grading/photo",
    response_model=ProduceGradingOut,
    summary="Propose ratings from a photo of the harvested produce (advisory; the farmer reviews and confirms)",
    responses=WRITE_ERR,
)
async def propose_from_photo(
    cycle_id: uuid.UUID,
    farmer: FarmerDep,
    grading: GradingServiceDep,
    image: Annotated[UploadFile, File(description="JPEG, PNG or WebP, max 5 MB")],
    language: Annotated[Literal["en", "kn"], Form()] = "en",
) -> ProduceGradingOut:
    data = await _read_limited(image, 5 * 1024 * 1024)
    # the vision model can take a minute: run it off the event loop so other requests keep flowing
    return await run_in_threadpool(grading.propose_from_photo, farmer.user_id, cycle_id, data, language)


@router.put(
    "/crop-cycles/{cycle_id}/grading",
    response_model=ProduceGradingOut,
    summary="Confirm the grade from your ratings of every check (manual, or after reviewing an AI proposal)",
    responses=WRITE_ERR,
)
def confirm_grading(
    cycle_id: uuid.UUID, payload: GradeConfirmIn, farmer: FarmerDep, grading: GradingServiceDep
) -> ProduceGradingOut:
    return grading.confirm(farmer.user_id, cycle_id, payload)
