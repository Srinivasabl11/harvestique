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
    "sms_provider": "android_gateway",
    "sms_gateway_url": "http://192.168.1.50:8080",
    "sms_gateway_username": "sms",
    "sms_gateway_password": "a-long-gateway-password",
}


def test_production_accepts_real_secret():
    s = Settings(_env_file=None, **PRODUCTION)
    assert s.app_env == "production"


@pytest.mark.parametrize(
    "override",
    [
        {"sms_provider": "dev_console"},  # would expose one-time codes
        {"llm_provider": "fake"},  # canned "AI" answers
        {"speech_provider": "fake"},
        {"weather_provider": "fake"},  # simulated weather shown as real
        {"notification_channel": "fake"},
    ],
)
def test_production_refuses_development_and_fake_providers(override):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**PRODUCTION, **override})


def test_development_defaults_to_the_labelled_console_otp_mode():
    assert Settings(_env_file=None).sms_provider == "dev_console"


def test_android_gateway_needs_its_address_and_credentials():
    with pytest.raises(ValidationError, match="SMS_GATEWAY_URL"):
        Settings(_env_file=None, sms_provider="android_gateway", sms_gateway_url="http://phone:8080")
