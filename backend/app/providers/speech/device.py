"""Speech adapters: on-device (default, no server engine) and a fake for tests."""

from __future__ import annotations

from app.core.errors import ProviderUnavailableError
from app.providers.speech.base import Language, SpeechAudio, Transcript


class OnDeviceSpeech:
    """No server speech engine: the app uses the phone's recogniser and voice. Calls fail clearly."""

    name = "device"

    def transcribe(self, audio: bytes, media_type: str, language: Language) -> Transcript:
        raise ProviderUnavailableError(
            "Speech recognition runs on the phone; no server speech engine is configured", code="speech_on_device"
        )

    def synthesize(self, text: str, language: Language) -> SpeechAudio:
        raise ProviderUnavailableError(
            "Text-to-speech runs on the phone; no server speech engine is configured", code="speech_on_device"
        )


class FakeSpeech:
    name = "fake"

    def __init__(self, transcript: str = "what is the weather") -> None:
        self.transcript = transcript
        self.calls: list[tuple[str, Language]] = []

    def transcribe(self, audio: bytes, media_type: str, language: Language) -> Transcript:
        self.calls.append(("stt", language))
        return Transcript(self.transcript, language, self.name)

    def synthesize(self, text: str, language: Language) -> SpeechAudio:
        self.calls.append(("tts", language))
        return SpeechAudio(b"RIFF\x00\x00\x00\x00WAVEfake", "audio/wav")
