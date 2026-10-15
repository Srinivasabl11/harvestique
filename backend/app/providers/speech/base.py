"""Speech provider contracts (English `en`, Kannada `kn`).

Default deployment: speech runs ON THE PHONE (Android speech recognition and text-to-speech, both of which support
en-IN and kn-IN), so the server needs no paid speech service. A server-side engine can be plugged in by
implementing these protocols.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

Language = Literal["en", "kn"]


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: Language
    provider: str


@dataclass(frozen=True, slots=True)
class SpeechAudio:
    data: bytes
    media_type: str


@runtime_checkable
class SpeechToTextProvider(Protocol):
    name: str

    def transcribe(self, audio: bytes, media_type: str, language: Language) -> Transcript: ...


@runtime_checkable
class TextToSpeechProvider(Protocol):
    name: str

    def synthesize(self, text: str, language: Language) -> SpeechAudio: ...
