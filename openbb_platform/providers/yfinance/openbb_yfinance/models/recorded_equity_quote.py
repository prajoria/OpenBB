"""Snapshot-backed yfinance equity-quote fetcher.

Part of sub-epic #1374 / PR-1 (#1375). Unblocks #1373 by providing an
offline route for ``EquityQuote`` — yfinance's live JSON has been
returning ``401 Invalid Crumb`` and blocks Phase B notebook code
fulfillment for every notebook in the user-guide series.

Reads ``scrape_record`` snapshots at
``openbb_platform/tools/scrape_record/snapshots/yahoo_equity_quote/<SYMBOL>.json``.

Refresh path::

    scrape-record record yahoo_equity_quote --symbol MSFT

Design mirrors ``YFinanceBondLadderFetcher`` (PR #1351):

- Pydantic pattern on ``symbol`` — defense-in-depth path-traversal guard
  before ``scrape_record.config._validate_snapshot_component`` fires
- ``_load_extracted`` re-runs the extractor if the snapshot's ``extracted``
  block is empty (lets an operator update the extractor and re-derive
  from raw without re-scraping)
- EmptyDataError names the exact recording command the operator needs
"""

# pylint: disable=unused-argument,import-outside-toplevel

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import ConfigDict, Field


class _SymbolQueryParams(QueryParams):
    """Symbol-keyed query for equity-quote snapshots.

    Same allowlist pattern as ``bond_ladder._EtfSymbolQueryParams``.
    Rejects path-traversal at the pydantic layer; the file-I/O layer
    (``scrape_record.config._validate_snapshot_component``) is the
    defense-in-depth backstop.
    """

    symbol: str = Field(
        description="Equity ticker symbol (e.g. 'MSFT', 'BRK.B').",
        pattern=r"^[A-Za-z0-9._\-^=]{1,32}$",
    )


class YFinanceEquityQuoteRecordedData(Data):
    """One equity-quote row from a checked-in Yahoo snapshot."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    name: str | None = Field(default=None, description="Company / instrument name.")
    exchange: str | None = Field(default=None, description="Listing exchange.")
    currency: str | None = Field(default=None, description="Quote currency.")
    last_price: float | None = Field(
        default=None, description="Last-trade price at capture time."
    )
    previous_close: float | None = Field(default=None, description="Previous close.")
    open: float | None = Field(default=None, description="Session open.")
    high: float | None = Field(default=None, description="Session high.")
    low: float | None = Field(default=None, description="Session low.")
    volume: int | None = Field(default=None, description="Session volume.")
    market_cap: float | None = Field(
        default=None, description="Market cap at capture time."
    )
    captured_at: str | None = Field(
        default=None,
        description="ISO-8601 UTC timestamp when the snapshot was recorded.",
    )


def _load_extracted(symbol: str) -> dict:
    """Read the checked-in snapshot for ``symbol``; return its ``extracted`` block."""
    try:
        from scrape_record.config import load_config
        from scrape_record.record import load_snapshot
    except ImportError as exc:
        raise EmptyDataError(
            "scrape_record package not installed. Install it via "
            "`pip install -e openbb_platform/tools/scrape_record/`."
        ) from exc

    cfg = load_config()
    try:
        env = load_snapshot(cfg, "yahoo_equity_quote", symbol)
    except FileNotFoundError as exc:
        raise EmptyDataError(
            f"No recorded quote snapshot for {symbol}. Run "
            f"`scrape-record record yahoo_equity_quote --symbol {symbol}` first."
        ) from exc

    extracted = env.extracted
    if not extracted:
        from scrape_record.extract import apply_extractor

        extracted = apply_extractor("yahoo_equity_quote", env.raw)
    return extracted


class YFinanceEquityQuoteRecordedFetcher(
    Fetcher[_SymbolQueryParams, YFinanceEquityQuoteRecordedData]
):
    """Read an equity quote from a checked-in scrape_record snapshot."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol query object."""
        return _SymbolQueryParams(**params)

    @classmethod
    def fetch_from_snapshot(
        cls, symbol: str, **kwargs: Any
    ) -> YFinanceEquityQuoteRecordedData:
        """Public sync shortcut for notebooks / scripts.

        Equivalent to ``asyncio.run(cls.fetch_data(...))`` but works
        inside a Jupyter kernel. Reads the checked-in snapshot via the
        same ``_load_extracted`` path ``aextract_data`` uses, then
        hands off to ``transform_data``. No network, no async.
        """
        query = cls.transform_query({"symbol": symbol, **kwargs})
        raw = _load_extracted(query.symbol.upper())
        return cls.transform_data(query, raw)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Load extracted quote snapshot (offline)."""
        return _load_extracted(query.symbol.upper())

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: dict, **kwargs: Any
    ) -> YFinanceEquityQuoteRecordedData:
        """Coerce extracted dict into typed equity-quote row."""
        return YFinanceEquityQuoteRecordedData(
            symbol=data.get("symbol") or query.symbol.upper(),
            name=data.get("name"),
            exchange=data.get("exchange"),
            currency=data.get("currency"),
            last_price=data.get("last_price"),
            previous_close=data.get("previous_close"),
            open=data.get("open"),
            high=data.get("high"),
            low=data.get("low"),
            volume=data.get("volume"),
            market_cap=data.get("market_cap"),
            captured_at=data.get("captured_at"),
        )
