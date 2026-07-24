"""Snapshot-backed yfinance ETF-holdings fetcher.

Part of sub-epic #1374 / PR-1 (#1375). Unblocks #1373 by providing an
offline route for ``EtfHoldings`` — yfinance's live
``topHoldings/fundOwnership`` module has been returning ``401 Invalid
Crumb``.

This is the fetcher NB03's basket x-ray (``look_through``) will call
under the hood for every ETF in the through-line basket. Contrast with
``bond_ladder``: that one is bond-ETF-specific and returns a single
row of roll-ups + holdings; this one is equity-ETF-general and returns
one row per underlying position.

Reads snapshots at
``openbb_platform/tools/scrape_record/snapshots/yahoo_etf_holdings/<SYMBOL>.json``.

Refresh path::

    scrape-record record yahoo_etf_holdings --symbol QQQ
"""

# pylint: disable=unused-argument,import-outside-toplevel

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import ConfigDict, Field


class _EtfSymbolQueryParams(QueryParams):
    """ETF-ticker-keyed query for holdings snapshots."""

    symbol: str = Field(
        description="ETF ticker symbol (e.g. 'QQQ', 'VTI').",
        pattern=r"^[A-Za-z0-9._\-^=]{1,32}$",
    )


class YFinanceEtfHoldingRecordedData(Data):
    """One holding row inside a recorded ETF-holdings snapshot."""

    model_config = ConfigDict(extra="allow")

    symbol: str | None = Field(
        default=None, description="Underlying ticker (may be missing for cash/other)."
    )
    name: str | None = Field(default=None, description="Underlying instrument name.")
    weight: float | None = Field(
        default=None, description="Weight in the ETF portfolio (fraction, 0-1)."
    )


class YFinanceEtfHoldingsRecordedFetcher(
    Fetcher[_EtfSymbolQueryParams, list[YFinanceEtfHoldingRecordedData]]
):
    """Read ETF holdings from a checked-in scrape_record snapshot.

    Returns a list of ``YFinanceEtfHoldingRecordedData`` rows — one per
    holding position in the ETF (the ``top_holdings`` list Yahoo
    publishes; typically 10-25 rows depending on the ETF).
    """

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _EtfSymbolQueryParams:
        return _EtfSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _EtfSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
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
            env = load_snapshot(cfg, "yahoo_etf_holdings", query.symbol.upper())
        except FileNotFoundError as exc:
            raise EmptyDataError(
                f"No recorded holdings snapshot for ETF {query.symbol}. Run "
                f"`scrape-record record yahoo_etf_holdings --symbol {query.symbol}` first."
            ) from exc

        extracted = env.extracted
        if not extracted:
            from scrape_record.extract import apply_extractor

            extracted = apply_extractor("yahoo_etf_holdings", env.raw)
        return extracted

    @staticmethod
    def transform_data(
        query: _EtfSymbolQueryParams, data: dict, **kwargs: Any
    ) -> list[YFinanceEtfHoldingRecordedData]:
        holdings = data.get("holdings") or []
        return [
            YFinanceEtfHoldingRecordedData(
                symbol=h.get("symbol"),
                name=h.get("name"),
                weight=h.get("weight"),
            )
            for h in holdings
            if isinstance(h, dict)
        ]
