"""
OpenBB SDK data helpers — replaces the HTTP proxy OpenBBClient.

All market data is now fetched in-process using the OpenBB Python SDK
(obb.*) rather than making HTTP requests to a separate service on port 6902.

Key design pattern:
    OpenBB SDK calls (obb.*) are synchronous.  They are wrapped in
    asyncio.get_event_loop().run_in_executor() so they do not block
    FastAPI's async event loop.  This mirrors best-practice for sync
    I/O inside async FastAPI endpoints.

Usage:
    from openbb_portfolio import _obb_data as od

    profile_df, quote_df, peers_df = await asyncio.gather(
        od.get_profile_df("MSFT"),
        od.get_quote_df("MSFT"),
        od.get_peers_df("MSFT"),
    )
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_PROVIDER = "fmp_cached"  # primary; OpenBB falls back automatically on miss


# --------------------------------------------------------------------------- #
#  Internal helpers
# --------------------------------------------------------------------------- #

def _obb_to_df(result) -> pd.DataFrame:
    """Convert an OBBject result to a pandas DataFrame."""
    if result is None:
        return pd.DataFrame()
    try:
        df = result.to_df()
        return df if df is not None else pd.DataFrame()
    except Exception as exc:
        logger.debug("OBBject.to_df() failed: %s", exc)
        return pd.DataFrame()


def _run_sync(fn, *args, **kwargs) -> pd.DataFrame:
    """Call a synchronous OpenBB SDK function and return a DataFrame.

    Wraps the call so that any exception is caught and logged, returning
    an empty DataFrame on failure.
    """
    try:
        result = fn(*args, **kwargs)
        return _obb_to_df(result)
    except Exception as exc:
        logger.warning("OpenBB SDK call failed [%s]: %s", fn.__name__ if hasattr(fn, "__name__") else fn, exc)
        return pd.DataFrame()


async def _async_run(fn, *args, **kwargs) -> pd.DataFrame:
    """Execute a synchronous OpenBB SDK call in the default thread-pool executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(fn, *args, **kwargs))


# --------------------------------------------------------------------------- #
#  Profile / quote / peers
# --------------------------------------------------------------------------- #

async def get_profile_df(
    symbol: str,
    provider: str = _DEFAULT_PROVIDER,
) -> pd.DataFrame:
    """Fetch equity company profile."""
    from openbb import obb  # lazy import — avoids startup overhead if not used

    def _fetch():
        return _run_sync(obb.equity.profile, symbol, provider=provider)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


async def get_quote_df(
    symbol: str,
    provider: str = _DEFAULT_PROVIDER,
) -> pd.DataFrame:
    """Fetch equity live quote."""
    from openbb import obb

    def _fetch():
        return _run_sync(obb.equity.price.quote, symbol, provider=provider)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


async def get_peers_df(
    symbol: str,
    provider: str = _DEFAULT_PROVIDER,
) -> pd.DataFrame:
    """Fetch equity peer list."""
    from openbb import obb

    def _fetch():
        return _run_sync(obb.equity.compare.peers, symbol, provider=provider)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


# --------------------------------------------------------------------------- #
#  Price history
# --------------------------------------------------------------------------- #

async def get_historical_df(
    symbol: str,
    start_date: str,
    end_date: str,
    interval: str = "1d",
    provider: str = _DEFAULT_PROVIDER,
    timeout: float = 120.0,
) -> pd.DataFrame:
    """Fetch daily OHLCV price history for one or more comma-separated symbols."""
    from openbb import obb

    def _fetch():
        return _run_sync(
            obb.equity.price.historical,
            symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
            provider=provider,
        )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


# --------------------------------------------------------------------------- #
#  Fundamental statements
# --------------------------------------------------------------------------- #

async def get_income_df(
    symbol: str,
    period: str = "annual",
    limit: int = 5,
    provider: str = _DEFAULT_PROVIDER,
    timeout: float = 90.0,
) -> pd.DataFrame:
    """Fetch income statement data."""
    from openbb import obb

    def _fetch():
        return _run_sync(
            obb.equity.fundamental.income,
            symbol,
            period=period,
            limit=limit,
            provider=provider,
        )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


async def get_balance_df(
    symbol: str,
    period: str = "annual",
    limit: int = 5,
    provider: str = _DEFAULT_PROVIDER,
    timeout: float = 90.0,
) -> pd.DataFrame:
    """Fetch balance sheet data."""
    from openbb import obb

    def _fetch():
        return _run_sync(
            obb.equity.fundamental.balance,
            symbol,
            period=period,
            limit=limit,
            provider=provider,
        )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


async def get_cash_df(
    symbol: str,
    period: str = "annual",
    limit: int = 5,
    provider: str = _DEFAULT_PROVIDER,
    timeout: float = 90.0,
) -> pd.DataFrame:
    """Fetch cash flow statement data."""
    from openbb import obb

    def _fetch():
        return _run_sync(
            obb.equity.fundamental.cash,
            symbol,
            period=period,
            limit=limit,
            provider=provider,
        )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


async def get_ratios_df(
    symbol: str,
    period: str = "annual",
    limit: int = 5,
    provider: str = _DEFAULT_PROVIDER,
    timeout: float = 90.0,
) -> pd.DataFrame:
    """Fetch financial ratios data."""
    from openbb import obb

    def _fetch():
        return _run_sync(
            obb.equity.fundamental.ratios,
            symbol,
            period=period,
            limit=limit,
            provider=provider,
        )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)
