"""AI Farm Assistant, voice and crop-health DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.core.enums import CropHealthClass, DataKind
from app.schemas.base import StrictModel

Lang = Literal["en", "kn"]
CropHealthStatus = Literal["healthy", "needs_attention", "retake_photo", "unavailable"]
Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class HistoryTurn(StrictModel):
    """One earlier turn of this conversation, sent back by the app (the server keeps no chat memory)."""

    role: Literal["user", "assistant"]
    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1200)]
    intent: Annotated[str, StringConstraints(max_length=40)] | None = None


History = Annotated[list[HistoryTurn], Field(default_factory=list, max_length=8)]
Alternatives = Annotated[list[Message], Field(default_factory=list, max_length=5)]


class AssistantRequest(StrictModel):
    message: Message
    language: Lang | None = Field(default=None, description="Reply language; Kannada text is detected automatically")
    farm_id: uuid.UUID | None = None
    crop_cycle_id: uuid.UUID | None = None
    history: History = Field(description="Up to 8 earlier turns, oldest first, for follow-up questions")
    alternatives: Alternatives = Field(
        description="Other transcripts the phone's recogniser offered for the same speech (best first)"
    )


class ToolCallOut(BaseModel):
    tool: str
    args: dict[str, Any]
    ok: bool
    error_code: str | None = None


class SourceRef(BaseModel):
    name: str
    kind: DataKind | str


class ProposedAction(BaseModel):
    tool: str
    args: dict[str, Any]
    summary: str


class AssistantResponse(BaseModel):
    language: Lang
    intent: str
    confidence: float = Field(description="Strength of the intent-rule match, not a probability of correctness")
    answer: str
    requires_confirmation: bool
    proposed_action: ProposedAction | None
    tool_calls: list[ToolCallOut]
    sources: list[SourceRef]
    disclaimer: str
    llm_used: bool = Field(description="True only if a local LLM reworded the answer AND it passed the grounding check")
    understood_by: Literal["rules", "alternative", "context", "local_model"] = Field(
        default="rules",
        description="How the question was understood: keyword rules, rules on another recogniser transcript, the "
        "previous turn (follow-up) or the local model",
    )
    heard: str | None = Field(
        default=None, description="The transcript that was understood, when it was not the first one (voice)"
    )
    normalised: str | None = Field(
        default=None,
        description="Voice only: the transcript as the server read it (joiners, punctuation removed; Kannada digits "
        "as 0-9), so the app can show what was understood",
    )
    navigate_to: str | None = Field(
        default=None,
        description="App screen to open (allowlisted key such as 'market', 'my_farm', 'back'); only for spoken or "
        "typed navigation commands, and only screens that exist for the account type",
    )
    answer_kind: Literal["records", "general_ai", "mixed", "guidance"] = Field(
        default="guidance",
        description="records: built from your data by a tool; general_ai: labelled general text from the local model; "
        "guidance: fixed help or a question back",
    )


class ToolRequest(StrictModel):
    args: dict[str, Any] = Field(default_factory=dict)
    confirm: bool = False
    language: Lang = "en"


class ToolResultOut(BaseModel):
    tool: str
    ok: bool
    answer: str
    data: Any
    sources: list[SourceRef]


class ToolInfo(BaseModel):
    name: str
    description: str
    writes: bool
    roles: list[str]


class VoiceIntentRequest(StrictModel):
    transcript: Message
    language: Lang = "en"
    farm_id: uuid.UUID | None = None
    crop_cycle_id: uuid.UUID | None = None
    history: History = Field(description="Up to 8 earlier turns, oldest first, for follow-up questions")
    alternatives: Alternatives = Field(
        description="Other transcripts the phone's recogniser offered (best first); used only when the first "
        "transcript is not understood"
    )


class SpeakRequest(StrictModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
    language: Lang = "en"


class TranscriptOut(BaseModel):
    text: str
    language: Lang
    provider: str


class CropValidationOut(BaseModel):
    crop_id: uuid.UUID
    name: str
    local_name: str | None
    crop_group: str
    main_part: str = Field(description="The part the crop is grown for; the photo check adapts its questions to it")
    validation: dict[str, Any] = Field(description="What has been MEASURED for this crop (verdict + evidence)")


class CropValidationReport(BaseModel):
    crops: list[CropValidationOut]
    summary: dict[str, int]
    rule: str


class CropHealthOut(BaseModel):
    id: uuid.UUID
    crop_cycle_id: uuid.UUID | None
    status: CropHealthStatus = Field(
        description="What the farmer sees: healthy, needs_attention, retake_photo (no health claim: a clearer photo "
        "is needed) or unavailable (the AI check could not run; no health claim)"
    )
    decision: dict[str, Any] = Field(
        description="status, reason, title, summary, confidence (low/medium/high or null), confidence_text, signs, "
        "next_steps; texts in the request's language. Advisory, never a diagnosis."
    )
    label: CropHealthClass = Field(description="Internal model category, kept for evaluations; not shown to farmers")
    probabilities: dict[str, float] = Field(description="Internal, for evaluations; not measured probabilities")
    features: dict[str, Any]
    quality_flags: list[str]
    explanation: str
    advice: str
    model_name: str
    model_version: str
    created_at: datetime
    data_kind: DataKind = DataKind.ESTIMATE
    disclaimer: str
