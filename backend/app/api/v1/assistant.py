"""AI Farm Assistant (controlled tools), voice and crop-health photo analysis. All advisory."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Response, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.api.deps import (
    AssistantServiceDep,
    CropHealthServiceDep,
    CurrentUserDep,
    FarmerDep,
    FarmerOrBuyerDep,
    SpeechServiceDep,
)
from app.api.responses import AUTH_ONLY, ERR, WRITE_ERR
from app.core.errors import DomainValidationError
from app.schemas.assistant import (
    AssistantRequest,
    AssistantResponse,
    CropHealthOut,
    CropValidationReport,
    SpeakRequest,
    ToolInfo,
    ToolRequest,
    ToolResultOut,
    TranscriptOut,
    VoiceIntentRequest,
)

router = APIRouter()
VOICE_503 = {**WRITE_ERR, 503: WRITE_ERR[409]}
UPLOAD_LIMIT = 5 * 1024 * 1024 + 1


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise DomainValidationError("The file is too large", code="file_too_large")
    return data


@router.post(
    "/assistant/chat",
    response_model=AssistantResponse,
    summary="Ask the farm assistant (advisory; English/Kannada)",
    responses=WRITE_ERR,
)
def chat(payload: AssistantRequest, user: CurrentUserDep, assistant: AssistantServiceDep) -> AssistantResponse:
    return assistant.chat(user, payload)


@router.get(
    "/assistant/tools", response_model=list[ToolInfo], summary="Tools the assistant may use for me", responses=AUTH_ONLY
)
def tools(user: CurrentUserDep, assistant: AssistantServiceDep) -> list[ToolInfo]:
    return assistant.list_tools(user)


@router.post(
    "/assistant/tools/{name}",
    response_model=ToolResultOut,
    summary="Run one validated tool (write tools need confirm=true)",
    responses=WRITE_ERR,
)
def call_tool(name: str, payload: ToolRequest, user: CurrentUserDep, assistant: AssistantServiceDep) -> ToolResultOut:
    return assistant.call_tool(user, name, payload)


@router.post(
    "/voice/intent",
    response_model=AssistantResponse,
    summary="Ask by voice: the on-device transcript goes through the same assistant and confirmations as chat",
    responses=WRITE_ERR,
)
def voice_intent(
    payload: VoiceIntentRequest, user: FarmerOrBuyerDep, assistant: AssistantServiceDep
) -> AssistantResponse:
    req = AssistantRequest(
        message=payload.transcript,
        language=payload.language,
        farm_id=payload.farm_id,
        crop_cycle_id=payload.crop_cycle_id,
        history=payload.history,
        alternatives=payload.alternatives,
    )
    return assistant.voice_chat(user, req)


@router.post(
    "/voice/transcribe",
    response_model=TranscriptOut,
    summary="Server speech-to-text (503 when speech runs on the phone)",
    responses=VOICE_503,
)
async def transcribe(
    user: FarmerOrBuyerDep,
    speech: SpeechServiceDep,
    audio: Annotated[UploadFile, File(description="WAV, OGG, FLAC, M4A or WebM, max 2 MB")],
    language: Annotated[Literal["en", "kn"], Form()] = "en",
) -> TranscriptOut:
    return speech.transcribe(await _read_limited(audio, 2 * 1024 * 1024), language)


@router.post(
    "/voice/speak",
    summary="Server text-to-speech (503 when speech runs on the phone)",
    responses=VOICE_503,
    response_class=Response,
)
def speak(payload: SpeakRequest, user: FarmerOrBuyerDep, speech: SpeechServiceDep) -> Response:
    audio = speech.speak(payload.text, payload.language)
    return Response(content=audio.data, media_type=audio.media_type)


@router.post(
    "/crop-health/analyze",
    response_model=CropHealthOut,
    summary="Advisory crop-health photo analysis (not a diagnosis)",
    responses=WRITE_ERR,
)
async def analyze(
    farmer: FarmerDep,
    health: CropHealthServiceDep,
    image: Annotated[UploadFile, File(description="JPEG, PNG or WebP, max 5 MB")],
    crop_cycle_id: Annotated[uuid.UUID | None, Form()] = None,
    language: Annotated[Literal["en", "kn"], Form()] = "en",
    crop_id: Annotated[
        uuid.UUID | None, Form(description="The crop in the photo when it is not one of your crop cycles")
    ] = None,
) -> CropHealthOut:
    data = await _read_limited(image, 5 * 1024 * 1024)
    # the local vision model can take a minute on a CPU: run it off the event loop so other requests keep flowing
    return await run_in_threadpool(health.analyze, farmer.user_id, data, crop_cycle_id, language, crop_id)


@router.get(
    "/crop-health/validation",
    response_model=CropValidationReport,
    summary="Which crops the photo check has been measured on (coverage is not accuracy)",
    responses=AUTH_ONLY,
)
def validation(_user: CurrentUserDep, health: CropHealthServiceDep) -> CropValidationReport:
    return health.validation_report()


@router.get(
    "/crop-health/analyses", response_model=list[CropHealthOut], summary="My past crop-health analyses", responses=ERR
)
def history(
    farmer: FarmerDep, health: CropHealthServiceDep, crop_cycle_id: uuid.UUID | None = None
) -> list[CropHealthOut]:
    return health.history(farmer.user_id, crop_cycle_id)
