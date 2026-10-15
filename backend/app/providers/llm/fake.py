"""LLM test doubles."""

from __future__ import annotations

from app.core.errors import ProviderUnavailableError
from app.providers.llm.base import LLMRequest, LLMResponse


class FakeLLMProvider:
    """Returns a canned reply and records requests for assertions."""

    name = "fake"

    def __init__(self, reply: str = "This is a fake advisory response.") -> None:
        self.reply = reply
        self.requests: list[LLMRequest] = []

    def is_available(self) -> bool:
        return True

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(text=self.reply, model="fake-model", provider=self.name)


class DisabledLLMProvider:
    """Used when no local model is configured; AI features must degrade gracefully."""

    name = "disabled"

    def is_available(self) -> bool:
        return False

    def generate(self, request: LLMRequest) -> LLMResponse:
        raise ProviderUnavailableError("LLM provider is disabled")
