"""AGMARKNET daily mandi prices through the Government of India Open Data API (data.gov.in).

Dataset: "Current Daily Price of Various Commodities from Various Markets (Mandi)", Ministry of Agriculture and
Farmers Welfare. It holds the CURRENT day's reports only (older days are kept by Harvestique in `market_prices`).
Needs a free personal API key (register at data.gov.in, "My Account"). Prices are INR per quintal.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

import httpx

from app.core.errors import ProviderUnavailableError
from app.providers.market.base import MandiPrice

logger = logging.getLogger(__name__)
DEFAULT_RESOURCE = "9ef84268-d588-465a-a308-a864a43d0070"
# api.data.gov.in silently drops requests with httpx's default User-Agent (measured 2026-10-14: no reply within
# 60 s, while any other agent was answered in 0.5 s), so the client identifies itself
USER_AGENT = "Harvestique/1.0 (farm assistant)"


class DataGovInMarketPrices:
    name = "data_gov_in"
    enabled = True

    def __init__(self, client: httpx.Client, api_key: str, resource: str = DEFAULT_RESOURCE) -> None:
        self._client = client
        self._key = api_key
        self._url = f"https://api.data.gov.in/resource/{resource}"

    def fetch(self, commodity: str, state: str | None) -> list[MandiPrice]:
        params = {"api-key": self._key, "format": "json", "limit": "500", "filters[commodity]": commodity}
        if state:
            params["filters[state.keyword]"] = state
        try:
            resp = self._client.get(self._url, params=params, headers={"User-Agent": USER_AGENT})
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderUnavailableError("The market price service did not answer") from exc
        if resp.status_code != 200 or "records" not in body:
            # never log the key; the body says e.g. "Rate limit exceeded" or "Authorization field missing"
            raise ProviderUnavailableError(
                f"The market price service refused the request ({body.get('error', resp.status_code)})"
            )
        return [p for r in body["records"] if (p := parse_record(r)) is not None]


def parse_record(r: dict[str, object]) -> MandiPrice | None:
    """One API record -> MandiPrice; None when a field is missing or malformed (skipped, never guessed)."""
    try:
        day = datetime.strptime(str(r["arrival_date"]), "%d/%m/%Y").date()
        prices = [Decimal(str(r[k])) for k in ("min_price", "modal_price", "max_price")]
    except (KeyError, ValueError, InvalidOperation):
        return None
    if any(p <= 0 for p in prices) or not prices[0] <= prices[1] <= prices[2]:
        return None
    return MandiPrice(
        state=str(r.get("state", "")),
        district=str(r.get("district", "")),
        market=str(r.get("market", "")),
        commodity=str(r.get("commodity", "")),
        variety=str(r.get("variety", "")),
        grade=str(r.get("grade", "")),
        arrival_date=day,
        min_price=prices[0],
        modal_price=prices[1],
        max_price=prices[2],
    )
