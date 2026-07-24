"""Snapshot-backed yfinance equity-info fetcher.

Part of sub-epic #1374 / PR-1 (#1375). Unblocks #1373 by providing an
offline route for ``EquityInfo`` (company profile) — yfinance's live
``summaryProfile`` module has been returning ``401 Invalid Crumb``.

Reads snapshots at
``openbb_platform/tools/scrape_record/snapshots/yahoo_equity_info/<SYMBOL>.json``.

Refresh path::

    scrape-record record yahoo_equity_info --symbol MSFT

Design mirrors ``recorded_equity_quote`` and ``bond_ladder``.
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
    """Symbol-keyed query for equity-info snapshots."""

    symbol: str = Field(
        description="Equity ticker symbol (e.g. 'MSFT', 'BRK.B').",
        pattern=r"^[A-Za-z0-9._\-^=]{1,32}$",
    )


class YFinanceEquityInfoRecordedData(Data):
    """Company profile row from a checked-in Yahoo snapshot."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    name: str | None = Field(default=None, description="Company name (long name).")
    short_name: str | None = Field(default=None, description="Short display name.")
    sector: str | None = Field(default=None, description="Sector classification.")
    industry: str | None = Field(default=None, description="Industry classification.")
    country: str | None = Field(default=None, description="Country of domicile.")
    website: str | None = Field(default=None, description="Corporate website URL.")
    long_business_summary: str | None = Field(
        default=None, description="Long-form business description."
    )
    full_time_employees: int | None = Field(
        default=None, description="Full-time employee count."
    )
    captured_at: str | None = Field(
        default=None, description="ISO-8601 UTC timestamp of the snapshot."
    )


def _load_extracted(symbol: str) -> dict:
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
        env = load_snapshot(cfg, "yahoo_equity_info", symbol)
    except FileNotFoundError as exc:
        raise EmptyDataError(
            f"No recorded profile snapshot for {symbol}. Run "
            f"`scrape-record record yahoo_equity_info --symbol {symbol}` first."
        ) from exc

    extracted = env.extracted
    if not extracted:
        from scrape_record.extract import apply_extractor

        extracted = apply_extractor("yahoo_equity_info", env.raw)
    return extracted


class YFinanceEquityInfoRecordedFetcher(
    Fetcher[_SymbolQueryParams, YFinanceEquityInfoRecordedData]
):
    """Read company profile from a checked-in scrape_record snapshot."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Load extracted company-profile snapshot (offline)."""
        return _load_extracted(query.symbol.upper())

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: dict, **kwargs: Any
    ) -> YFinanceEquityInfoRecordedData:
        """Coerce extracted dict into typed company-profile row."""
        return YFinanceEquityInfoRecordedData(
            symbol=data.get("symbol") or query.symbol.upper(),
            name=data.get("name"),
            short_name=data.get("short_name"),
            sector=data.get("sector"),
            industry=data.get("industry"),
            country=data.get("country"),
            website=data.get("website"),
            long_business_summary=data.get("long_business_summary"),
            full_time_employees=data.get("full_time_employees"),
            captured_at=data.get("captured_at"),
        )
