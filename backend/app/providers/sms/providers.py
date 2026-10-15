"""SMS providers: the development console, your own Android phone as a gateway, disabled, and a test recorder."""

from __future__ import annotations

import logging

import httpx

from app.core.errors import ProviderUnavailableError
from app.providers.sms.base import mask_phone

logger = logging.getLogger(__name__)


class DevConsoleSms:
    """DEVELOPMENT ONLY. Sends nothing: the code is written to the server log and returned by the API with a label
    saying it was not sent by SMS. Refused when APP_ENV=production."""

    name = "dev_console"
    exposes_codes = True

    def is_enabled(self) -> bool:
        return True

    def send(self, phone: str, text: str) -> None:
        logger.warning("DEVELOPMENT OTP MODE - no SMS was sent to %s. Message: %s", mask_phone(phone), text)


class AndroidGatewaySms:
    """Sends through an Android phone running the open-source 'SMS Gateway for Android' app (Apache-2.0,
    https://github.com/capcom6/android-sms-gateway) in Local Server mode: POST http://<phone>:8080/message with Basic
    authentication. Its free Cloud Server mode works the same way at https://api.sms-gate.app/3rdparty/v1/messages, so
    the phone needs only mobile data. No SMS company account is needed, but every message is a normal SMS from that
    phone's SIM, so the mobile plan's SMS charges and daily limits apply. The phone must be on and online.
    """

    name = "android_gateway"
    exposes_codes = False

    def __init__(
        self, *, client: httpx.Client, base_url: str, username: str, password: str, message_path: str = "/message"
    ) -> None:
        self._client = client
        self._url = base_url.rstrip("/") + "/" + message_path.lstrip("/")
        self._auth = (username, password)

    def is_enabled(self) -> bool:
        return True

    def send(self, phone: str, text: str) -> None:
        body = {"textMessage": {"text": text}, "phoneNumbers": [phone]}
        try:
            resp = self._client.post(self._url, json=body, auth=self._auth)
        except httpx.HTTPError as exc:
            logger.warning("SMS gateway unreachable for %s: %s", mask_phone(phone), type(exc).__name__)
            raise ProviderUnavailableError("The SMS gateway phone could not be reached") from exc
        if resp.status_code >= 300:
            # never log the body we sent (it contains the code); the gateway's status is enough to diagnose
            logger.warning("SMS gateway refused the message for %s: HTTP %s", mask_phone(phone), resp.status_code)
            raise ProviderUnavailableError("The SMS gateway did not accept the message")


class DisabledSms:
    name = "disabled"
    exposes_codes = False

    def is_enabled(self) -> bool:
        return False

    def send(self, phone: str, text: str) -> None:
        raise ProviderUnavailableError("SMS sending is disabled on this server")


class RecordingSms:
    """Test double: records what would have been sent (like a phone's inbox). Not selectable by configuration."""

    name = "recording"
    exposes_codes = False

    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = fail

    def is_enabled(self) -> bool:
        return True

    def send(self, phone: str, text: str) -> None:
        if self.fail:
            raise ProviderUnavailableError("recording SMS set to fail")
        self.sent.append((phone, text))

    def last_code(self, phone: str) -> str:
        import re

        for to, text in reversed(self.sent):
            if to == phone and (m := re.search(r"\b(\d{6,8})\b", text)):
                return m.group(1)
        raise LookupError(f"no code was sent to {phone}")
