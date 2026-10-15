"""Local Ollama adapter (optional, free, runs on your own machine). The assistant uses it only to choose a tool when
its keyword rules do not understand a question, for short labelled general answers, and (optionally) to reword a tool
answer. Every use is validated by the caller: a tool name must be in the allowed list and any wording must pass the
grounding check (no numbers that are not in the facts)."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from app.core.errors import ProviderUnavailableError
from app.providers.llm.base import LLMRequest, LLMResponse

AVAILABILITY_TTL_SECONDS = 30.0  # re-check a down (or recovered) server instead of remembering forever
KEEP_ALIVE = "30m"  # keep the model in memory between questions: loading it can take ~20 s on a CPU


class OllamaLLMProvider:
    name = "ollama"

    def __init__(
        self,
        *,
        client: httpx.Client,
        base_url: str,
        model: str,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._model = model
        self._now = monotonic
        self._available: bool | None = None
        self._checked_at = 0.0

    @property
    def model(self) -> str:
        return self._model

    def is_available(self) -> bool:
        if self._available is None or self._now() - self._checked_at >= AVAILABILITY_TTL_SECONDS:
            try:
                resp = self._client.get(f"{self._base}/api/tags", timeout=2.0)
                names = {m.get("name") for m in resp.json().get("models", [])} if resp.status_code == 200 else set()
                # the server being up is not enough: the configured model must be installed (`ollama pull <model>`)
                self._available = self._model in names or f"{self._model}:latest" in names
            except (httpx.HTTPError, ValueError, AttributeError):
                self._available = False
            self._checked_at = self._now()
        return self._available

    def generate(self, request: LLMRequest) -> LLMResponse:
        body: dict[str, object] = {
            "model": self._model,
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "options": {"temperature": request.temperature, "num_predict": request.max_tokens},
        }
        if request.json_mode:
            body["format"] = "json"
        try:
            resp = self._client.post(f"{self._base}/api/chat", json=body)
            resp.raise_for_status()
            text = resp.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            self._available, self._checked_at = False, self._now()  # retried after the TTL, not never
            raise ProviderUnavailableError("The local language model did not answer") from exc
        if not isinstance(text, str):
            raise ProviderUnavailableError("The local language model returned an invalid answer")
        return LLMResponse(text=text, model=self._model, provider=self.name)
