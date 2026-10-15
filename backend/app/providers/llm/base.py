"""LLM provider contract.

The LLM is an *advisory text generator only*. It receives a pre-assembled,
user-scoped context string built by a service and returns text. It never gets
a database session, repository, or the ability to execute queries or writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class LLMRequest:
    messages: tuple[LLMMessage, ...]
    temperature: float = 0.2
    max_tokens: int = 512
    json_mode: bool = False  # ask the model for JSON; caller still validates with Pydantic
    metadata: dict[str, str] = field(default_factory=dict)  # e.g. prompt template id/version


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str
    provider: str


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def is_available(self) -> bool: ...

    def generate(self, request: LLMRequest) -> LLMResponse: ...
