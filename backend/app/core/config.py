"""Application settings loaded from environment variables / .env.

All configuration flows through `Settings`. Nothing else in the codebase
reads os.environ directly, so tests can build an isolated Settings object.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_SECRET = "change-me-in-production-0123456789abcdef"  # noqa: S105 - placeholder, rejected in production


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Repo-root .env first, then backend/.env (later files win). Missing files are ignored.
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---
    app_name: str = "Harvestique API"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"  # json in production: one object per line
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # --- Database ---
    database_url: str = "postgresql+psycopg://harvestique:harvestique@localhost:5433/harvestique"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # --- Auth ---
    jwt_secret_key: SecretStr = SecretStr(INSECURE_DEFAULT_SECRET)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "harvestique"
    access_token_expire_minutes: int = Field(default=15, ge=1)
    refresh_token_expire_days: int = Field(default=14, ge=1)
    # Argon2id cost parameters (argon2-cffi defaults). Tests lower these for speed.
    password_hash_time_cost: int = Field(default=3, ge=1)
    password_hash_memory_kib: int = Field(default=65536, ge=8)
    password_hash_parallelism: int = Field(default=4, ge=1)
    # Brute-force protection: N consecutive failures per phone -> locked for the window. Sign-in is password-only
    # (no SMS code), so a second, daily cap also applies: that many failures per phone within 24 hours lock it until
    # the oldest of them is a day old. A correct password or an admin password reset clears both.
    login_max_failed_attempts: int = Field(default=5, ge=1)
    login_lockout_minutes: int = Field(default=15, ge=1)
    login_max_failed_attempts_per_day: int = Field(default=20, ge=1)
    # Flood guard: at most this many new accounts per hour across the whole server (sign-ups past it get 429).
    registrations_max_per_hour: int = Field(default=30, ge=1)

    # Tester access: "pending" makes every NEW sign-up wait until an admin approves it (admin app > Testers, or
    # POST /admin/users/{id}/access). Existing accounts are never changed by this setting.
    new_account_access: Literal["approved", "pending"] = "approved"

    # Fresh installs: fill an EMPTY crop catalog with the standard crops at startup (never in tests, never
    # when any crop already exists). Without crops, farmers cannot add a crop to a plot.
    seed_crop_catalog_on_startup: bool = True

    # --- Providers (replaceable adapters) ---
    weather_provider: Literal["open_meteo", "fake"] = "fake"
    open_meteo_base_url: str = "https://api.open-meteo.com/v1"
    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1"

    weather_timeout_seconds: float = Field(default=10.0, gt=0)
    # Mandi prices: AGMARKNET daily prices via data.gov.in (free; a personal API key from data.gov.in "My Account").
    # "disabled": no live prices, only prices already stored are used and farmers are asked for a price otherwise.
    market_price_provider: Literal["disabled", "data_gov_in", "fake"] = "disabled"
    data_gov_in_api_key: str | None = None
    market_price_timeout_seconds: float = Field(default=15.0, gt=0)
    weather_forecast_max_age_hours: int = Field(default=12, ge=1)  # older cached forecasts are "stale"
    prediction_provider: Literal["rule_based", "demo_scripted"] = "rule_based"  # demo_scripted: demo mode only
    calibration_min_samples: int = Field(default=5, ge=2)

    llm_provider: Literal["ollama", "fake", "disabled"] = "disabled"
    ollama_base_url: str = "http://localhost:11434"
    # Only for a hosted Ollama server (e.g. Ollama Cloud, OLLAMA_BASE_URL=https://ollama.com): sent as a Bearer token.
    ollama_api_key: SecretStr | None = None
    ollama_model: str = "llama3.2:3b"
    llm_timeout_seconds: float = 60.0
    # What the local model may do in the assistant (the answer always comes from controlled tools):
    assistant_llm_intents: bool = True  # pick a tool when the keyword rules do not understand the question
    assistant_llm_general_answers: bool = True  # short general answers (no numbers, labelled, not farm data)
    # Kannada general answers from small local models were garbled in testing (docs/AI_PIPELINE.md), so they are
    # off unless a model that writes good Kannada is configured. Kannada questions about the farmer's own data and
    # Kannada tool routing are not affected.
    assistant_llm_general_answers_kannada: bool = False
    assistant_llm_rewording: bool = False  # reword tool answers; slow on CPU-only machines, so off by default

    notification_channel: Literal["in_app", "fake"] = "in_app"
    speech_provider: Literal["device", "fake"] = "device"  # device: STT/TTS run on the phone (en-IN, kn-IN)
    # ollama_vision: a local vision model (`ollama pull gemma3:4b`, ~3.3 GB, ~6 GB RAM, 30-90 s per photo on a CPU);
    # falls back to the colour heuristic whenever the model is missing or does not answer in time.
    crop_health_classifier: Literal["colour_heuristic", "ollama_vision"] = "colour_heuristic"
    ollama_vision_model: str = "gemma3:4b"
    vision_timeout_seconds: float = Field(default=150.0, gt=0)
    # Report "unknown" instead of a problem when the only sign is generic spots at low confidence. Off by default:
    # on PlantDoc it cut healthy-leaf false alarms (held-out macro F1 0.84 -> 0.94) but 3 of 50 diseased leaves became
    # "unknown" (docs/CROP_HEALTH_EVAL_2026-10-14.md). Turn on only after deciding that trade-off is wanted.
    crop_health_generic_spots_uncertain: bool = False
    # v1: the evaluated production prompt. v2: candidate prompt (normal leaf features are not damage; colour and extent
    # of each sign), see docs/CROP_PHOTO_ANALYSIS_2026-10-15.md for its held-out comparison before switching.
    crop_health_prompt_version: Literal["v1", "v2"] = "v1"
    # AI photo checks (crop health + produce grading proposals) per user per hour: each one holds the vision model for
    # up to a minute and spends the hosted model's free allowance. Counted in memory (one server process).
    ai_photo_checks_per_hour: int = Field(default=30, ge=1, le=1000)

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3_driver(cls, url: str) -> str:
        """Hosted databases (Neon, Render, Heroku) give postgres:// or postgresql:// URLs, which SQLAlchemy maps to
        psycopg2; only psycopg 3 is installed."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @model_validator(mode="after")
    def _reject_insecure_production_config(self) -> Settings:
        if self.app_env == "production":
            secret = self.jwt_secret_key.get_secret_value()
            if secret == INSECURE_DEFAULT_SECRET or len(secret) < 32:
                raise ValueError("JWT_SECRET_KEY must be a strong secret (>= 32 characters) in production")
            if self.debug:
                raise ValueError("DEBUG must be false in production")
            if self.new_account_access != "pending":
                # sign-in is password-only: an admin approving each new account is the identity check
                raise ValueError("NEW_ACCOUNT_ACCESS must be 'pending' in production (password-only sign-in)")
            if self.prediction_provider == "demo_scripted":
                raise ValueError("The demo_scripted prediction provider cannot be used in production")
            for name, value in (
                ("LLM_PROVIDER", self.llm_provider),
                ("SPEECH_PROVIDER", self.speech_provider),
                ("WEATHER_PROVIDER", self.weather_provider),
                ("MARKET_PRICE_PROVIDER", self.market_price_provider),
                ("NOTIFICATION_CHANNEL", self.notification_channel),
            ):
                if value == "fake":
                    raise ValueError(f"{name}=fake returns canned data and cannot be used in production")
        if self.market_price_provider == "data_gov_in" and not self.data_gov_in_api_key:
            raise ValueError("MARKET_PRICE_PROVIDER=data_gov_in needs DATA_GOV_IN_API_KEY (free key from data.gov.in)")
        return self


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings singleton (overridable in tests via dependency_overrides)."""
    return Settings()
