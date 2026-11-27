"""Read-only market data, fundamentals, news, and account provider backed by synthetic fixtures."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from trading_platform.domain.contracts import (
    AccountSnapshot,
    FundamentalSnapshot,
    NewsItem,
    QuoteSnapshot,
)
from trading_platform.domain.types import ensure_utc, utc_now


class MarketDataProvider:
    """Provides point-in-time synthetic quotes, fundamentals, and news fixtures."""

    def __init__(
        self,
        *,
        quotes: dict[str, QuoteSnapshot],
        fundamentals: dict[str, FundamentalSnapshot],
        news: list[NewsItem],
        initial_account: AccountSnapshot,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._quotes = dict(quotes)
        self._fundamentals = dict(fundamentals)
        self._news = list(news)
        self._initial_account = initial_account
        self._clock = clock or utc_now

    @classmethod
    def from_fixtures(
        cls,
        market_data_path: Path,
        news_feed_path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> MarketDataProvider:
        mkt = json.loads(market_data_path.read_text(encoding="utf-8"))
        news_raw = json.loads(news_feed_path.read_text(encoding="utf-8"))
        as_of = ensure_utc(datetime.fromisoformat(mkt["as_of_utc"].replace("Z", "+00:00")))

        quotes = {
            sym.upper(): QuoteSnapshot.model_validate(q)
            for sym, q in mkt.get("quotes", {}).items()
        }
        fundamentals = {
            sym.upper(): FundamentalSnapshot.model_validate(f)
            for sym, f in mkt.get("fundamentals", {}).items()
        }
        news = [NewsItem.model_validate(item) for item in news_raw.get("items", [])]
        account_data = dict(mkt["account"])
        account_data["as_of_utc"] = as_of
        initial_account = AccountSnapshot.model_validate(account_data)

        effective_clock = clock or (lambda: as_of)
        return cls(
            quotes=quotes,
            fundamentals=fundamentals,
            news=news,
            initial_account=initial_account,
            clock=effective_clock,
        )

    def now(self) -> datetime:
        return ensure_utc(self._clock())

    def set_clock(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    @property
    def initial_account(self) -> AccountSnapshot:
        return self._initial_account

    def get_quote(self, symbol: str) -> QuoteSnapshot | None:
        return self._quotes.get(symbol.upper())

    def set_quote(self, quote: QuoteSnapshot) -> None:
        self._quotes[quote.symbol.upper()] = quote

    def get_all_quotes(self) -> dict[str, QuoteSnapshot]:
        return dict(self._quotes)

    def get_fundamentals(self, symbol: str) -> FundamentalSnapshot | None:
        return self._fundamentals.get(symbol.upper())

    def get_news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        now_utc = self.now()
        matching = [
            item
            for item in self._news
            if item.symbol.upper() == symbol.upper() and item.available_at_utc <= now_utc
        ]
        matching.sort(key=lambda x: x.published_at_utc, reverse=True)
        return matching[:limit]

    def replace_news_from_fixture(self, news_feed_path: Path) -> None:
        raw = json.loads(news_feed_path.read_text(encoding="utf-8"))
        self._news = [NewsItem.model_validate(item) for item in raw.get("items", [])]

    def apply_quote_overrides_from_fixture(self, quote_fixture_path: Path) -> None:
        raw = json.loads(quote_fixture_path.read_text(encoding="utf-8"))
        for sym, q in raw.get("quotes", {}).items():
            self._quotes[sym.upper()] = QuoteSnapshot.model_validate(q)
