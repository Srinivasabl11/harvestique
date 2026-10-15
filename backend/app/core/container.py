"""Composition root.

`build_container` is the ONLY place where concrete implementations are chosen.
Everything else depends on Protocols and receives instances through FastAPI
dependencies (app/api/deps.py) or constructor injection in services.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.database import build_engine, build_session_factory, ping_database
from app.core.security import PasswordHasher, TokenCodec
from app.providers.llm.base import LLMProvider
from app.providers.market.base import DisabledMarketPrices, MarketPriceProvider
from app.providers.notifications.base import NotificationChannel
from app.providers.prediction.base import PredictionProvider
from app.providers.registry import (
    build_crop_health_classifier,
    build_llm_provider,
    build_market_price_provider,
    build_notification_channel,
    build_prediction_provider,
    build_speech_provider,
    build_weather_provider,
)
from app.providers.speech.device import FakeSpeech, OnDeviceSpeech
from app.providers.vision.base import ColourHeuristicClassifier, CropHealthClassifier
from app.providers.weather.base import WeatherProvider


@dataclass
class Container:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    weather: WeatherProvider
    llm: LLMProvider
    notifications: NotificationChannel
    passwords: PasswordHasher
    predictor: PredictionProvider
    tokens: TokenCodec
    speech: OnDeviceSpeech | FakeSpeech = field(default_factory=OnDeviceSpeech)
    crop_health: CropHealthClassifier = field(default_factory=ColourHeuristicClassifier)
    market_prices: MarketPriceProvider = field(default_factory=DisabledMarketPrices)
    clock: Clock = field(default_factory=SystemClock)
    db_ping: Callable[[], bool] | None = None

    def check_database(self) -> bool:
        return self.db_ping() if self.db_ping else ping_database(self.engine)

    def shutdown(self) -> None:
        self.engine.dispose()


def build_container(settings: Settings) -> Container:
    engine = build_engine(settings)  # lazy: no connection is opened here
    return Container(
        settings=settings,
        engine=engine,
        session_factory=build_session_factory(engine),
        weather=build_weather_provider(settings),
        llm=build_llm_provider(settings),
        notifications=build_notification_channel(settings),
        predictor=build_prediction_provider(settings),
        speech=build_speech_provider(settings),
        crop_health=build_crop_health_classifier(settings),
        market_prices=build_market_price_provider(settings),
        passwords=PasswordHasher(
            time_cost=settings.password_hash_time_cost,
            memory_kib=settings.password_hash_memory_kib,
            parallelism=settings.password_hash_parallelism,
        ),
        tokens=TokenCodec(
            secret=settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            issuer=settings.jwt_issuer,
            access_ttl=timedelta(minutes=settings.access_token_expire_minutes),
        ),
    )
