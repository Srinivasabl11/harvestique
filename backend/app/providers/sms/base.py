"""SMS delivery contract for one-time verification codes.

The auth service builds the text and calls `send`; a provider only delivers it. Providers must never log or return
the message text, with ONE exception: the development console provider, whose whole purpose is to show the code on a
developer's machine. It says so (`exposes_codes`) and the settings refuse it in production.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SmsSender(Protocol):
    name: str
    #: True only for the development console: the API may then return the code, labelled as not sent by SMS.
    exposes_codes: bool

    def is_enabled(self) -> bool: ...

    def send(self, phone: str, text: str) -> None:
        """Deliver `text` to `phone` (E.164). Raise ProviderUnavailableError if it could not be handed over."""
        ...


def mask_phone(phone: str) -> str:
    """+919876543210 -> +91******3210 (safe for logs and API responses)."""
    if len(phone) <= 6:
        return "*" * len(phone)
    return phone[:3] + "*" * (len(phone) - 7) + phone[-4:]
