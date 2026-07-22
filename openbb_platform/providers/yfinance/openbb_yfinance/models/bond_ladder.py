"""YFinance bond-ladder fetcher backed by scrape_record snapshots.

Closes #1000. Bond issuance + YTM data has no free live JSON API under
the current no-subscription constraint. Yahoo Finance publishes bond
ETF holdings pages that carry: per-bond issuer + maturity + coupon +
weight, plus portfolio-level YTM + duration + sector/credit breakdowns.

This fetcher reads ``scrape_record`` snapshots (checked into
``openbb_platform/tools/scrape_record/snapshots/yahoo_bond_etf_holdings/``)
for well-known bond ETFs (BND, AGG, BSV, VCLT, ...). Users can add
more ETFs by running::

    scrape-record record yahoo_bond_etf_holdings --symbol AGG

The "symbol" here is the ETF ticker, and each row returned is a bond
position inside that ETF — a proxy for the bond ladder the Equity
Profile §6B widget wants.

**Design contrast** with #999's options fetcher: options data is
per-underlying (AAPL, MSFT, ...); this is per-ETF (BND, AGG, ...).
Both share the same offline-snapshot pattern.
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
    """ETF-ticker-keyed query for bond-holdings snapshots.

    Same allowlist pattern as ``recorded_options._SymbolQueryParams``
    — rejects path-traversal at pydantic-validation time. See
    ``scrape_record.config._validate_snapshot_component`` for
    defense-in-depth at the file-I/O layer.
    """

    symbol: str = Field(
        description="Bond ETF ticker symbol (e.g. 'BND', 'AGG', 'BSV').",
        pattern=r"^[A-Za-z0-9._\-^=]{1,32}$",
    )


class YFinanceBondHoldingData(Data):
    """One bond position inside an ETF's holdings snapshot."""

    symbol: str | None = Field(
        default=None,
        description="Bond identifier as reported by the ETF (e.g. CUSIP or 'T 4.5 02/15/36').",
    )
    issuer: str | None = Field(default=None, description="Issuer name.")
    coupon: float | None = Field(default=None, description="Coupon rate (percent).")
    maturity: str | None = Field(
        default=None, description="Maturity date (YYYY-MM-DD)."
    )
    weight: float | None = Field(
        default=None, description="Weight in the ETF portfolio (fraction, 0-1)."
    )
    ytm: float | None = Field(
        default=None, description="Yield to maturity (percent, best-effort per Yahoo)."
    )
    rating: str | None = Field(default=None, description="Credit rating.")


class YFinanceBondLadderData(Data):
    """Portfolio-level roll-up + holdings list for a bond ETF."""

    model_config = ConfigDict(extra="allow")

    etf_symbol: str = Field(description="ETF ticker.")
    etf_name: str | None = Field(default=None, description="Full ETF name.")
    as_of_date: str | None = Field(default=None, description="Holdings snapshot date.")
    portfolio_avg_ytm: float | None = Field(
        default=None, description="Portfolio-average yield to maturity."
    )
    portfolio_duration_years: float | None = Field(
        default=None, description="Portfolio duration in years."
    )
    holdings: list[YFinanceBondHoldingData] = Field(
        default_factory=list, description="Bond positions inside the ETF."
    )
    sector_weights: dict[str, float] = Field(
        default_factory=dict, description="Sector breakdown as {name: fraction}."
    )
    credit_quality_breakdown: dict[str, float] = Field(
        default_factory=dict,
        description="Credit-quality breakdown as {rating: fraction}.",
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
        env = load_snapshot(cfg, "yahoo_bond_etf_holdings", symbol)
    except FileNotFoundError as exc:
        raise EmptyDataError(
            f"No recorded snapshot for bond ETF {symbol}. Run "
            f"`scrape-record record yahoo_bond_etf_holdings --symbol {symbol}` "
            "first. Common ETFs to record: BND, AGG, BSV, VCLT, LQD, HYG."
        ) from exc

    extracted = env.extracted
    if not extracted:
        from scrape_record.extract import apply_extractor

        extracted = apply_extractor("yahoo_bond_etf_holdings", env.raw)
    return extracted


class YFinanceBondLadderFetcher(Fetcher[_EtfSymbolQueryParams, YFinanceBondLadderData]):
    """Read bond ETF holdings + roll-up from checked-in scrape_record snapshots.

    Returns a single ``YFinanceBondLadderData`` (not a list) — the row
    encapsulates the whole portfolio (holdings list + roll-ups).
    """

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _EtfSymbolQueryParams:
        """Coerce raw params dict into typed ETF-symbol query object."""
        return _EtfSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _EtfSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Load extracted bond-holdings snapshot (offline)."""
        return _load_extracted(query.symbol.upper())

    @staticmethod
    def transform_data(
        query: _EtfSymbolQueryParams, data: dict, **kwargs: Any
    ) -> YFinanceBondLadderData:
        """Coerce extracted dict into the typed roll-up + typed holdings list."""
        holdings = [
            YFinanceBondHoldingData(**h)
            for h in (data.get("holdings") or [])
            if isinstance(h, dict)
        ]
        return YFinanceBondLadderData(
            etf_symbol=data.get("etf_symbol") or query.symbol.upper(),
            etf_name=data.get("etf_name"),
            as_of_date=data.get("as_of_date"),
            portfolio_avg_ytm=data.get("portfolio_avg_ytm"),
            portfolio_duration_years=data.get("portfolio_duration_years"),
            holdings=holdings,
            sector_weights=data.get("sector_weights") or {},
            credit_quality_breakdown=data.get("credit_quality_breakdown") or {},
        )
