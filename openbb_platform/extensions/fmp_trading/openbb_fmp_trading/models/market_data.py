"""Intraday market-data models (PRD §6.2.3).

Six data classes covering the intraday FMP fetcher payloads shipped in Phase 0:
IntradayBar, Quote, AftermarketQuote, AftermarketTrade, SessionStatus, IndicatorValue.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from openbb_core.provider.abstract.data import Data
from pydantic import Field


class IntradayBar(Data):
    """One intraday OHLCV bar."""

    symbol: str
    interval: Literal["1min", "5min", "15min", "30min", "1hour", "4hour"]
    ts: datetime = Field(description="Bar-start timestamp (tz-aware).")
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    is_extended: bool = Field(
        default=False, description="True if this bar is an extended-hours bar."
    )


class Quote(Data):
    """Real-time (or short-form) quote row. `short` variant omits bid/ask fields."""

    symbol: str
    price: Decimal
    change: Decimal
    change_pct: float
    volume: int
    timestamp: datetime
    # short=False adds these — all optional to accommodate both variants:
    bid: Decimal | None = None
    ask: Decimal | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    day_high: Decimal | None = None
    day_low: Decimal | None = None
    prev_close: Decimal | None = None
    year_high: Decimal | None = None
    year_low: Decimal | None = None
    market_cap: int | None = None
    avg_volume: int | None = None
    pe_ratio: float | None = None
    eps: float | None = None
    shares_outstanding: int | None = None
    price_avg_50: Decimal | None = None
    price_avg_200: Decimal | None = None


class AftermarketQuote(Data):
    """Extended-hours quote (pre-market or post-close)."""

    symbol: str
    price: Decimal
    bid: Decimal
    ask: Decimal
    bid_size: int
    ask_size: int
    volume: int
    timestamp: datetime


class AftermarketTrade(Data):
    """Extended-hours last-print trade."""

    symbol: str
    price: Decimal
    size: int
    timestamp: datetime


class SessionStatus(Data):
    """Exchange session-state snapshot (RTH / pre / post / halted / holiday)."""

    exchange: str
    is_market_open: bool
    is_pre_market: bool
    is_after_market: bool
    is_early_close_day: bool
    next_open: datetime
    next_close: datetime


class IndicatorValue(Data):
    """One (symbol, indicator, bar) reading — FMP's server-computed indicator."""

    symbol: str
    indicator: str
    ts: datetime
    value: float | None = Field(
        default=None,
        description="None during the lookback warm-up window at session start.",
    )
    period_length: int
    timeframe: str
