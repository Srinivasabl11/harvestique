"""Crop-health heuristic (synthetic images), image/audio validation, Ollama adapter, speech and demo providers."""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import httpx
import numpy as np
import pytest
from PIL import Image

from app.core.enums import CropHealthClass as C
from app.core.enums import CycleStatus, DataKind, IrrigationType, PredictionStatus
from app.core.errors import DomainValidationError, ProviderUnavailableError
from app.domain.vision import MAX_PROBABILITY, assess
from app.providers.llm.base import LLMMessage, LLMRequest
from app.providers.llm.ollama import OllamaLLMProvider
from app.providers.speech.device import FakeSpeech, OnDeviceSpeech
from app.services.media import SpeechService, audio_kind, decode_image, image_kind

RNG = np.random.default_rng(0)


def img(colour, noise=25, n=128):
    a = np.full((n, n, 3), colour, dtype=np.float64) + RNG.normal(0, noise, (n, n, 3))
    return np.clip(a, 0, 255).astype(np.uint8)


def leaf_with_spots(n=128):
    a = img((50, 140, 40), n=n)
    r = max(4, n // 20)
    for fy, fx in [(0.15, 0.15), (0.5, 0.7), (0.8, 0.3), (0.25, 0.8), (0.7, 0.8)]:
        cy, cx = int(fy * n), int(fx * n)
        a[cy - r : cy + r, cx - r : cx + r] = (110, 70, 30)
    return a


def half_dry(n=128):
    a = img((50, 140, 40), n=n)
    a[:, n // 2 :] = img((130, 85, 40), n=n)[:, n // 2 :]
    return a


@pytest.mark.parametrize(
    ("make", "label"),
    [
        (lambda: img((50, 140, 40)), C.HEALTHY),
        (lambda: img((200, 190, 40)), C.POSSIBLE_DEFICIENCY),
        (leaf_with_spots, C.POSSIBLE_DISEASE),
        (half_dry, C.STRESS),
        (lambda: img((128, 128, 128)), C.UNKNOWN),  # not a plant
        (lambda: img((120, 170, 230)), C.UNKNOWN),  # sky
        (lambda: img((120, 90, 60), noise=8), C.UNKNOWN),  # bare soil: no green tissue, no guess
        (lambda: img((10, 15, 10), noise=3), C.UNKNOWN),  # too dark
        (lambda: img((250, 250, 250), noise=2), C.UNKNOWN),  # blown out
    ],
)
def test_synthetic_cases(make, label):
    r = assess(make())
    assert r.label is label
    assert abs(sum(r.probabilities.values()) - 1) < 0.01
    assert max(r.probabilities.values()) <= MAX_PROBABILITY + 1e-9  # never claims certainty
    assert set(r.probabilities) == {c.value for c in C}
    assert r.explanation and r.advice


def test_poor_photos_are_flagged():
    assert "too_dark" in assess(img((10, 15, 10), noise=3)).quality_flags
    assert "little_plant_visible" in assess(img((128, 128, 128))).quality_flags
    blurred = np.full((128, 128, 3), (50, 140, 40), dtype=np.uint8)
    assert "blurry" in assess(blurred).quality_flags


def test_kannada_explanations():
    r = assess(img((50, 140, 40)), "kn")
    assert any("ಀ" <= ch <= "೿" for ch in r.explanation)


def test_rejects_non_rgb_or_tiny_input():
    with pytest.raises(ValueError):
        assess(np.zeros((10, 10, 3), dtype=np.uint8))
    with pytest.raises(ValueError):
        assess(np.zeros((64, 64), dtype=np.uint8))


# ------------------------------------------------------------- file validation
def encode(a: np.ndarray, fmt: str = "PNG", **kw) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(a).save(buf, format=fmt, **kw)
    return buf.getvalue()


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_accepted_formats_decode_and_downscale(fmt):
    data = encode(img((50, 140, 40), n=800), fmt)
    assert image_kind(data) == fmt
    assert max(decode_image(data).shape[:2]) == 768  # the vision model needs detail; the heuristic downsizes again


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "empty_file"),
        (b"GIF89a" + b"\x00" * 100, "unsupported_file_type"),
        (b"%PDF-1.7 not an image", "unsupported_file_type"),
        (b"\x89PNG\r\n\x1a\n" + b"garbage" * 20, "invalid_image"),  # PNG magic, corrupt body
        (b"\xff\xd8\xff" + b"\x00" * 6 * 1024 * 1024, "file_too_large"),
    ],
)
def test_rejected_files(data, code):
    with pytest.raises(DomainValidationError) as e:
        decode_image(data)
    assert e.value.code == code


def test_rejects_tiny_and_huge_dimensions():
    with pytest.raises(DomainValidationError) as e:
        decode_image(encode(img((50, 140, 40), n=32)))
    assert e.value.code == "bad_dimensions"


def test_rejects_animated_webp():
    frames = [Image.fromarray(img((50, 140, 40))) for _ in range(2)]
    buf = io.BytesIO()
    frames[0].save(buf, format="WEBP", save_all=True, append_images=frames[1:])
    with pytest.raises(DomainValidationError) as e:
        decode_image(buf.getvalue())
    assert e.value.code == "unsupported_file_type"


def test_decompression_bomb_is_refused():
    big = Image.new("1", (6000, 6000))  # 36 MP > 25 MP limit, tiny file
    buf = io.BytesIO()
    big.save(buf, format="PNG")
    with pytest.raises(DomainValidationError) as e:
        decode_image(buf.getvalue())
    assert e.value.code in ("invalid_image", "bad_dimensions")


def test_type_spoofing_png_bytes_are_judged_by_content_not_by_name():
    data = encode(img((50, 140, 40)), "PNG")
    assert image_kind(data) == "PNG"  # whatever the upload claimed to be


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", "audio/wav"),
        (b"OggS\x00\x02", "audio/ogg"),
        (b"fLaC\x00", "audio/flac"),
        (b"\x00\x00\x00\x18ftypM4A ", "audio/mp4"),
        (b"\x1a\x45\xdf\xa3\x01", "audio/webm"),
        (b"ID3\x03mp3", None),
    ],
)
def test_audio_magic(data, kind):
    assert audio_kind(data) == kind


def test_speech_service_validates_before_the_provider():
    fake = FakeSpeech("ನಾಳೆ ಮಳೆ")
    svc = SpeechService(stt=fake, tts=fake)
    with pytest.raises(DomainValidationError):
        svc.transcribe(b"ID3 not supported", "kn")
    with pytest.raises(DomainValidationError):
        svc.transcribe(b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * (2 * 1024 * 1024), "kn")
    assert fake.calls == []
    assert svc.transcribe(b"RIFF\x00\x00\x00\x00WAVEdata", "kn").text == "ನಾಳೆ ಮಳೆ"


def test_on_device_speech_reports_unavailable_clearly():
    with pytest.raises(ProviderUnavailableError) as e:
        OnDeviceSpeech().transcribe(b"x", "audio/wav", "en")
    assert e.value.code == "speech_on_device"
    with pytest.raises(ProviderUnavailableError):
        OnDeviceSpeech().synthesize("hello", "kn")


# --------------------------------------------------------------------- Ollama
def _ollama(handler):
    return OllamaLLMProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)), base_url="http://ollama:11434/", model="m"
    )


REQ = LLMRequest(messages=(LLMMessage("user", "hi"),))


def test_ollama_success_and_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "m:latest"}]})
        seen["body"] = request.read()
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "ok"}})

    p = _ollama(handler)
    assert p.is_available() and p.generate(REQ).text == "ok"
    body = seen["body"].replace(b" ", b"")
    assert b'"stream":false' in body and b'"keep_alive":"30m"' in body and b'"format"' not in body
    p.generate(LLMRequest(messages=REQ.messages, json_mode=True))
    assert b'"format":"json"' in seen["body"].replace(b" ", b"")


def test_ollama_without_the_configured_model_is_unavailable():
    p = _ollama(lambda r: httpx.Response(200, json={"models": [{"name": "other:7b"}]}))
    assert p.is_available() is False  # `ollama pull <model>` has not been run: do not pretend


def test_ollama_availability_is_rechecked_after_a_while():
    clock = {"t": 0.0}
    state = {"up": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if not state["up"]:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"models": [{"name": "m"}]})

    p = OllamaLLMProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="http://ollama:11434",
        model="m",
        monotonic=lambda: clock["t"],
    )
    assert p.is_available() is False
    state["up"] = True
    clock["t"] = 10
    assert p.is_available() is False  # still within the re-check interval
    clock["t"] = 31
    assert p.is_available() is True  # Ollama started later: picked up without a server restart


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, json={"bad": 1}),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={"message": {"content": 5}}),
    ],
)
def test_ollama_failures_are_provider_unavailable(response):
    p = _ollama(lambda r: response)
    with pytest.raises(ProviderUnavailableError):
        p.generate(REQ)


def test_ollama_unreachable_is_unavailable():
    def boom(r):
        raise httpx.ConnectError("down")

    assert _ollama(boom).is_available() is False


# ------------------------------------------------------------- demo predictor
def test_demo_predictor_echoes_the_estimate_and_labels_it_simulated():
    from app.core.enums import CropCategory
    from app.domain.prediction.models import CropProfile, CycleFacts, PredictionInput, Range
    from app.domain.weather import WeatherContext
    from app.providers.prediction.demo import DemoScriptedPredictor

    inp = PredictionInput(
        crop=CropProfile("Tomato", CropCategory.VEGETABLE, 100, None, None, None),
        cycle=CycleFacts(
            Decimal("1.5"), date(2026, 8, 1), CycleStatus.GROWING, date(2026, 11, 10), IrrigationType.DRIP
        ),
        today=date(2026, 10, 8),
        history=(),
        observations=(),
        weather=WeatherContext.unavailable("test"),
        farmer_estimate=Range(Decimal(300), Decimal(300), Decimal(300)),
        calibration=None,
    )
    r = DemoScriptedPredictor().predict(inp)
    assert r.status is PredictionStatus.OK and r.quantity_kg is not None
    assert (r.quantity_kg.p10, r.quantity_kg.p50, r.quantity_kg.p90) == (Decimal(450), Decimal(450), Decimal(450))
    assert r.output_kind is DataKind.SIMULATED and all(s.kind is DataKind.SIMULATED for s in r.sources)
    assert r.model_name == "demo-scripted" and any("DEMO MODE" in w for w in r.warnings)


def test_demo_predictor_is_refused_in_production():
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError, match="demo_scripted"):
        Settings(_env_file=None, app_env="production", jwt_secret_key="x" * 40, prediction_provider="demo_scripted")  # type: ignore[call-arg]
