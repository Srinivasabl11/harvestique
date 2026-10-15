import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_are_safe_for_dev():
    s = Settings(_env_file=None)
    assert s.app_env == "development"
    assert s.llm_provider == "disabled"


def test_production_rejects_default_secret():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production")


PRODUCTION = {
    "app_env": "production",
    "jwt_secret_key": "x" * 48,
    "weather_provider": "open_meteo",
    "new_account_access": "pending",
}


def test_production_accepts_real_secret():
    s = Settings(_env_file=None, **PRODUCTION)
    assert s.app_env == "production"


@pytest.mark.parametrize(
    "override",
    [
        {"new_account_access": "approved"},  # open sign-up without SMS: anyone could use the app
        {"llm_provider": "fake"},  # canned "AI" answers
        {"speech_provider": "fake"},
        {"weather_provider": "fake"},  # simulated weather shown as real
        {"notification_channel": "fake"},
    ],
)
def test_production_refuses_development_and_fake_providers(override):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**PRODUCTION, **override})


def test_stale_sms_settings_are_ignored_and_auth_limits_have_safe_defaults():
    """Old SMS_* variables left on a server must not stop it from starting (SMS sign-in codes were removed)."""
    s = Settings(_env_file=None, **PRODUCTION, sms_provider="android_gateway", sms_gateway_password="x")
    assert not hasattr(s, "sms_provider")
    limits = (s.login_max_failed_attempts, s.login_max_failed_attempts_per_day, s.registrations_max_per_hour)
    assert limits == (5, 20, 30)


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgres://u:p@h/db?sslmode=require", "postgresql+psycopg://u:p@h/db?sslmode=require"),
        ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ],
)
def test_hosted_database_urls_use_psycopg3(given, expected):
    assert Settings(_env_file=None, database_url=given).database_url == expected
