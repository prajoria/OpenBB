"""YFinance options chain fetchers backed by scrape_record snapshots.

**Contrast with ``YFinanceOptionsChainsFetcher``** (in
``options_chains.py``): that fetcher uses the ``yfinance`` Python lib
which scrapes Yahoo at query time and breaks whenever Yahoo drifts.
This fetcher reads from checked-in ``scrape_record`` snapshots — no
live Yahoo, deterministic, offline-capable.

Ships two fetchers:

- ``YFinanceRecordedOptionsChainsFetcher`` — full chain (all strikes,
  all expiries) matching the shape of the live fetcher.
- ``YFinanceAtmIvTermStructureFetcher`` — the primary shape #999
  wants: one row per expiry with the ATM strike + IV for calls + puts.

Snapshots must exist at
``openbb_platform/tools/scrape_record/snapshots/yahoo_options_chain/<SYMBOL>.json``.
Regenerate via::

    scrape-record record yahoo_options_chain --symbol AAPL
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
    """Symbol-keyed query for recorded options endpoints.

    Applies a strict allowlist pattern at pydantic-validation time as
    first-line defense against path-traversal via the ``symbol``
    string reaching ``scrape_record.config.snapshot_path``. The
    downstream ``snapshot_path`` validator re-checks the same rule
    (defense-in-depth); rejecting here just fails faster with a
    better error message.
    """

    symbol: str = Field(
        description="Underlying ticker symbol (e.g. 'AAPL').",
        # Allowlist: uppercase alnum + finance-legit punctuation
        # (. - _ ^ =). Length 1-32 covers real tickers with plenty of
        # headroom.  NO path separators, dots-only, or NUL.
        pattern=r"^[A-Za-z0-9._\-^=]{1,32}$",
    )


class YFinanceRecordedOptionData(Data):
    """One option contract row from a checked-in Yahoo options snapshot."""

    side: str = Field(description="'call' or 'put'.")
    expiration_unix: int = Field(description="Expiration date as unix epoch (seconds).")
    contract_symbol: str | None = Field(
        default=None, description="OCC contract symbol."
    )
    strike: float | None = Field(default=None, description="Strike price.")
    last_price: float | None = Field(default=None, description="Last trade price.")
    bid: float | None = Field(default=None, description="Bid price.")
    ask: float | None = Field(default=None, description="Ask price.")
    volume: int | None = Field(default=None, description="Session volume.")
    open_interest: int | None = Field(default=None, description="Open interest.")
    implied_volatility: float | None = Field(
        default=None, description="Implied volatility (decimal, e.g. 0.2812 = 28.12%)."
    )
    in_the_money: bool | None = Field(default=None, description="ITM indicator.")
    currency: str | None = Field(default=None, description="Currency code.")


class YFinanceAtmIvTermRowData(Data):
    """One row of the ATM-IV term structure: ATM call + ATM put per expiry."""

    model_config = ConfigDict(extra="allow")

    expiration_unix: int = Field(description="Expiration date as unix epoch (seconds).")
    atm_strike: float | None = Field(
        default=None, description="Nearest-to-spot strike."
    )
    call_iv: float | None = Field(default=None, description="ATM call implied vol.")
    put_iv: float | None = Field(default=None, description="ATM put implied vol.")
    call_contract_symbol: str | None = Field(
        default=None, description="ATM call contract symbol."
    )
    put_contract_symbol: str | None = Field(
        default=None, description="ATM put contract symbol."
    )


def _load_extracted(symbol: str) -> dict:
    """Read the checked-in snapshot for ``symbol``; return its ``extracted`` block.

    Raises EmptyDataError with a helpful message if the snapshot doesn't
    exist — this is the user-facing signal to run
    ``scrape-record record yahoo_options_chain --symbol <SYM>``.
    """
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
        env = load_snapshot(cfg, "yahoo_options_chain", symbol)
    except FileNotFoundError as exc:
        raise EmptyDataError(
            f"No recorded snapshot for {symbol}. Run "
            f"`scrape-record record yahoo_options_chain --symbol {symbol}` "
            "first, or use YFinanceOptionsChainsFetcher for live scraping."
        ) from exc

    extracted = env.extracted
    if not extracted:
        # Older snapshot format without extracted block — re-derive on the fly.
        from scrape_record.extract import apply_extractor

        extracted = apply_extractor("yahoo_options_chain", env.raw)
    return extracted


class YFinanceRecordedOptionsChainsFetcher(
    Fetcher[_SymbolQueryParams, list[YFinanceRecordedOptionData]]
):
    """Read full options chain from checked-in scrape_record snapshots."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Load extracted snapshot for the symbol (offline)."""
        return _load_extracted(query.symbol.upper())

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: dict, **kwargs: Any
    ) -> list[YFinanceRecordedOptionData]:
        """Flatten chains-per-expiry into a single flat contract list."""
        rows: list[YFinanceRecordedOptionData] = []
        for chain in data.get("chains", []):
            expiry = int(chain.get("expiration_unix", 0))
            for contract in (*chain.get("calls", []), *chain.get("puts", [])):
                rows.append(
                    YFinanceRecordedOptionData(
                        expiration_unix=expiry,
                        **{
                            k: v
                            for k, v in contract.items()
                            if v is not None or k != "side"
                        },
                    )
                )
        return rows


class YFinanceAtmIvTermStructureFetcher(
    Fetcher[_SymbolQueryParams, list[YFinanceAtmIvTermRowData]]
):
    """Read ATM-IV term structure from checked-in scrape_record snapshots.

    Primary shape #999 (Equity Profile §4B) consumes: one row per
    expiry with the ATM call + put IV. Downstream widget plots IV vs
    days-to-expiry.
    """

    @staticmethod
    def transform_query(params: dict[str, Any]) -> _SymbolQueryParams:
        """Coerce raw params dict into typed symbol-query object."""
        return _SymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: _SymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Load extracted snapshot for the symbol (offline)."""
        return _load_extracted(query.symbol.upper())

    @staticmethod
    def transform_data(
        query: _SymbolQueryParams, data: dict, **kwargs: Any
    ) -> list[YFinanceAtmIvTermRowData]:
        """Collapse extracted atm_iv_term rows into flat term-structure rows."""
        rows: list[YFinanceAtmIvTermRowData] = []
        for entry in data.get("atm_iv_term", []):
            call = entry.get("atm_call") or {}
            put = entry.get("atm_put") or {}
            # Prefer the call's strike (they're the same when symmetric; if not,
            # call side is the standard reference).
            atm_strike = call.get("strike") or put.get("strike")
            rows.append(
                YFinanceAtmIvTermRowData(
                    expiration_unix=int(entry.get("expiration_unix", 0)),
                    atm_strike=atm_strike,
                    call_iv=call.get("impliedVolatility"),
                    put_iv=put.get("impliedVolatility"),
                    call_contract_symbol=call.get("contractSymbol"),
                    put_contract_symbol=put.get("contractSymbol"),
                )
            )
        return rows
