"""Latest available mandi price for a crop near a farm: refresh from data.gov.in when configured (at most every few
hours per commodity and state), keep every report in `market_prices`, then choose deterministically
(app/domain/market.py). Provider failures never break an estimate: stored reports are used, or the farmer is asked."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.errors import AppError
from app.domain.market import (
    DEFAULT_STATE,
    MAX_AGE_DAYS,
    NEIGHBOURS,
    MandiPrice,
    PriceQuote,
    choose_quote,
    commodity_names,
)
from app.models.intelligence import MarketPrice
from app.providers.market.base import MarketPriceProvider

logger = logging.getLogger(__name__)
REFRESH_HOURS = 6
RETRY_AFTER_FAILURE = timedelta(minutes=10)
# (provider, commodity, state) -> (last attempt, it failed): an empty day is not re-fetched on every question,
# and a failed attempt keeps saying 'did not answer' (not 'no price reported') until it is retried
_ATTEMPTS: dict[tuple[int, str, str | None], tuple[datetime, bool]] = {}
IST = timedelta(hours=5, minutes=30)


@dataclass(frozen=True, slots=True)
class QuoteResult:
    quote: PriceQuote | None
    live: bool  # a provider is configured
    refresh_failed: bool  # it was tried and did not answer


class MarketPriceService:
    def __init__(self, session: Session, provider: MarketPriceProvider, clock: Clock) -> None:
        self._session = session
        self._provider = provider
        self._clock = clock

    def quote(self, crop_name: str, *, state: str | None, district: str | None) -> QuoteResult:
        state = state or DEFAULT_STATE
        names = commodity_names(crop_name)
        failed = False
        if self._provider.enabled:
            for name in names:
                found = self._refresh(name, state)
                if found == 0:  # nothing in the farm's state today: all states, for neighbouring markets
                    found = self._refresh(name, None)
                failed |= found is None
        today = (self._clock.now() + IST).date()
        rows = self._session.scalars(
            select(MarketPrice).where(
                MarketPrice.commodity.in_(names),
                MarketPrice.state.in_((state, *NEIGHBOURS.get(state, ()))),
                MarketPrice.arrival_date >= today - timedelta(days=MAX_AGE_DAYS),
            )
        ).all()
        records = [
            MandiPrice(
                r.state,
                r.district,
                r.market,
                r.commodity,
                r.variety,
                r.grade,
                r.arrival_date,
                r.min_price,
                r.modal_price,
                r.max_price,
            )
            for r in rows
        ]
        return QuoteResult(
            choose_quote(records, state=state, district=district, today=today), self._provider.enabled, failed
        )

    def _refresh(self, commodity: str, state: str | None) -> int | None:
        """Fetch today's reports unless tried recently. Returns how many were stored (-1: skipped, recent), None when
        the provider failed. Attempts are remembered per process so an empty day is not re-fetched on every question."""
        now = self._clock.now()
        key = (id(self._provider), commodity, state)
        last = _ATTEMPTS.get(key)
        if last is not None:
            when, failed = last
            if failed and now - when < RETRY_AFTER_FAILURE:
                return None
            if not failed and now - when < timedelta(hours=REFRESH_HOURS):
                return -1
        try:
            fetched = self._provider.fetch(commodity, state)
        except AppError as exc:
            _ATTEMPTS[key] = (now, True)
            logger.info("market price refresh failed for %s: %s", commodity, exc.message)
            return None
        _ATTEMPTS[key] = (now, False)
        now = self._clock.now()
        for p in fetched:
            stmt = insert(MarketPrice).values(
                state=p.state,
                district=p.district,
                market=p.market,
                commodity=p.commodity,
                variety=p.variety,
                grade=p.grade,
                arrival_date=p.arrival_date,
                min_price=p.min_price,
                modal_price=p.modal_price,
                max_price=p.max_price,
                source=self._provider.name,
                fetched_at=now,
            )
            self._session.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_market_prices_report",
                    set_={
                        "min_price": p.min_price,
                        "modal_price": p.modal_price,
                        "max_price": p.max_price,
                        "fetched_at": now,
                    },
                )
            )
        self._session.commit()
        return len(fetched)
