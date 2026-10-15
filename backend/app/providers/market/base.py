"""Mandi (APMC) price provider contract. Prices are in INR per quintal, as reported by the market."""

from __future__ import annotations

from typing import Protocol

from app.domain.market import MandiPrice

__all__ = ["DisabledMarketPrices", "FakeMarketPrices", "MandiPrice", "MarketPriceProvider"]


class MarketPriceProvider(Protocol):
    name: str

    @property
    def enabled(self) -> bool: ...

    def fetch(self, commodity: str, state: str | None) -> list[MandiPrice]:
        """Today's reported prices for one commodity (optionally one state). Raises ProviderUnavailableError."""
        ...


class DisabledMarketPrices:
    """No live prices (no data.gov.in API key configured): only prices already stored are used."""

    name = "disabled"
    enabled = False

    def fetch(self, commodity: str, state: str | None) -> list[MandiPrice]:
        return []


class FakeMarketPrices:
    """Test double: returns the records it was given for a commodity."""

    name = "fake"
    enabled = True

    def __init__(self, records: list[MandiPrice] | None = None) -> None:
        self.records = list(records or [])
        self.calls: list[tuple[str, str | None]] = []

    def fetch(self, commodity: str, state: str | None) -> list[MandiPrice]:
        self.calls.append((commodity, state))
        return [r for r in self.records if r.commodity == commodity and (state is None or r.state == state)]
