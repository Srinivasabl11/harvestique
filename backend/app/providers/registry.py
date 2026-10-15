"""Provider factory: maps configuration values to concrete implementations.

Real adapters are added in the phase that first needs them:
  * open_meteo -> weather / prediction work
  * in_app     -> DB-backed notification feed
  * ollama     -> advisory explanations
(Sequencing: docs/PROGRESS.md and docs/ARCHITECTURE.md section 10.)
Selecting one before it exists fails fast at startup with a clear message.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.core.errors import ProviderUnavailableError
from app.domain.prediction.engine import RuleBasedPredictor
from app.providers.llm.base import LLMProvider
from app.providers.llm.fake import DisabledLLMProvider, FakeLLMProvider
from app.providers.llm.ollama import OllamaLLMProvider
from app.providers.market.base import DisabledMarketPrices, FakeMarketPrices, MarketPriceProvider
from app.providers.market.data_gov_in import DataGovInMarketPrices
from app.providers.notifications.base import NotificationChannel
from app.providers.notifications.fake import FakeNotificationChannel, InAppNotificationChannel
from app.providers.prediction.base import PredictionProvider
from app.providers.prediction.demo import DemoScriptedPredictor
from app.providers.speech.device import FakeSpeech, OnDeviceSpeech
from app.providers.vision.base import ColourHeuristicClassifier, CropHealthClassifier
from app.providers.vision.ollama import OllamaVisionClassifier
from app.providers.weather.base import WeatherProvider
from app.providers.weather.fake import FakeWeatherProvider
from app.providers.weather.open_meteo import OpenMeteoWeatherProvider

logger = logging.getLogger(__name__)


def _hosted_ollama_without_key(settings: Settings) -> bool:
    """Ollama Cloud lists its models publicly but answers nothing without a key: treat that as "not configured"
    (health shows it, the assistant and photo check use their non-AI paths) instead of a server that looks ready."""
    host = urlparse(settings.ollama_base_url).hostname or ""
    hosted = host == "ollama.com" or host.endswith(".ollama.com")
    if hosted and settings.ollama_api_key is None:
        logger.warning("OLLAMA_BASE_URL is Ollama Cloud but OLLAMA_API_KEY is not set: AI features are off")
        return True
    return False


def _not_yet(kind: str, value: str, phase: str) -> ProviderUnavailableError:
    return ProviderUnavailableError(f"{kind} provider '{value}' is planned for {phase} and is not implemented yet")


def build_weather_provider(settings: Settings, http: httpx.Client | None = None) -> WeatherProvider:
    if settings.weather_provider == "fake":
        return FakeWeatherProvider()
    return OpenMeteoWeatherProvider(
        client=http or httpx.Client(timeout=settings.weather_timeout_seconds),
        base_url=settings.open_meteo_base_url,
        archive_url=settings.open_meteo_archive_url,
    )


def build_market_price_provider(settings: Settings, http: httpx.Client | None = None) -> MarketPriceProvider:
    if settings.market_price_provider == "data_gov_in" and settings.data_gov_in_api_key:
        return DataGovInMarketPrices(
            client=http or httpx.Client(timeout=settings.market_price_timeout_seconds),
            api_key=settings.data_gov_in_api_key,
        )
    if settings.market_price_provider == "fake":
        return FakeMarketPrices()
    return DisabledMarketPrices()


def build_prediction_provider(settings: Settings) -> PredictionProvider:
    """Only the transparent rule model exists today; a trained model would be selected here by name."""
    if settings.prediction_provider == "rule_based":
        return RuleBasedPredictor()
    if settings.prediction_provider == "demo_scripted":
        return DemoScriptedPredictor()
    raise _not_yet("Prediction", settings.prediction_provider, "a future trained model")


def _ollama_client(settings: Settings, timeout: float) -> httpx.Client:
    """A hosted Ollama server (Ollama Cloud) needs its API key; a local one needs nothing."""
    key = settings.ollama_api_key.get_secret_value() if settings.ollama_api_key else None
    return httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {key}"} if key else None)


def build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "disabled":
        return DisabledLLMProvider()
    if settings.llm_provider == "fake":
        return FakeLLMProvider()
    if _hosted_ollama_without_key(settings):
        return DisabledLLMProvider()
    return OllamaLLMProvider(
        client=_ollama_client(settings, settings.llm_timeout_seconds),
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
    )


def build_notification_channel(settings: Settings) -> NotificationChannel:
    if settings.notification_channel == "fake":
        return FakeNotificationChannel()
    return InAppNotificationChannel()


def build_speech_provider(settings: Settings) -> OnDeviceSpeech | FakeSpeech:
    """One object implements both SpeechToTextProvider and TextToSpeechProvider."""
    return FakeSpeech() if settings.speech_provider == "fake" else OnDeviceSpeech()


def build_crop_health_classifier(settings: Settings) -> CropHealthClassifier:
    if settings.crop_health_classifier == "ollama_vision" and not _hosted_ollama_without_key(settings):
        return OllamaVisionClassifier(
            client=_ollama_client(settings, settings.vision_timeout_seconds),
            base_url=settings.ollama_base_url,
            model=settings.ollama_vision_model,
            generic_spots_uncertain=settings.crop_health_generic_spots_uncertain,
            prompt_version=settings.crop_health_prompt_version,
            fallback=ColourHeuristicClassifier(),
        )
    return ColourHeuristicClassifier()
