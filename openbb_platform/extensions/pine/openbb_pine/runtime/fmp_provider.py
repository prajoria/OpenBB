"""FMP-backed OHLCV provider for the Pine runtime.

Post-E3.2: inherits :class:`pynecore.providers.Provider` (mode-2 per
Pine Extraction Design §5.2 / §6.2). The class is still constructed
via ``FMPRequest`` so the existing ``executor_shell`` call path is
untouched, but it now IS-A ``Provider`` and exposes the spec §5
``stream()`` / ``fetch()`` contract so ``pyne_compiler`` runtime code
can consume it polymorphically through the ABC.

Asset-class dispatch (D2 section 2.2) routes each symbol to the matching
``obb.<asset>.price.historical`` surface:

* ``equity`` -> ``obb.equity.price.historical``
* ``crypto`` -> ``obb.crypto.price.historical``
* ``currency`` (forex) -> ``obb.currency.price.historical``
* ``commodity`` -> ``obb.commodity.price.historical``

Tests mock the ``obb`` call surface so they pass without an FMP API key.

Clean-room note: I have not viewed TradingView or PyneComp source code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Iterator, Literal

# Trigger the openbb_pine sys.path bridge so ``pynecore`` resolves against
# the vendored submodule before the base-class import below.
import openbb_pine  # noqa: F401

from pynecore.core.syminfo import SymInfoInterval, SymInfoSession
from pynecore.providers.provider import Provider

from openbb_pine.runtime.provider_selection import (
    ProviderName,
    SUPPORTED_PROVIDERS,
    resolve_provider,
)

if TYPE_CHECKING:  # pragma: no cover -- imports for type-checking only
    from pynecore.types.ohlcv import OHLCV


AssetClass = Literal["equity", "crypto", "currency", "commodity"]
_ASSET_CLASSES: tuple[AssetClass, ...] = ("equity", "crypto", "currency", "commodity")


# --- Asset-class inference ----------------------------------------------------

# Currency pair: explicit slash (``EUR/USD``) or 6-letter major (``EURUSD``).
_CURRENCY_PAIR_RX = re.compile(r"^[A-Z]{3}/[A-Z]{3}$")
_CURRENCY_FLAT_RX = re.compile(
    r"^("
    r"AUD|CAD|CHF|EUR|GBP|JPY|NZD|USD|"
    r"BRL|CNY|HKD|INR|KRW|MXN|NOK|RUB|SEK|SGD|TRY|ZAR"
    r"){2}$"
)
# Crypto: ``BTC-USD``, ``ETH-USDT``, the legacy CME ``XBTUSD`` slug, and the
# ``BTCUSD`` / ``ETHUSD`` shorthand used by FMP/CCXT-style feeds. Suffix list
# stays narrow so we don't capture forex pairs like ``USDJPY``.
_CRYPTO_DASH_RX = re.compile(r"^[A-Z0-9]{2,10}-(USD|USDT|USDC|BTC|ETH|EUR)$")
_CRYPTO_FLAT_RX = re.compile(r"^(XBT|BTC|ETH|SOL|XRP|ADA|DOGE|LTC|BCH|DOT|MATIC|AVAX|LINK)USD[T]?$")
# Commodity / futures: TradingView root-ticker glyphs ``GC1!``, ``CL1!``;
# Yahoo Finance ``GC=F`` / ``CL=F``; index-prefixed ``^GSPC``.
_FUTURES_ROOT_RX = re.compile(r"^[A-Z]{1,3}\d!$")
_FUTURES_YH_RX = re.compile(r"^[A-Z]{1,3}=F$")


def infer_asset_class(symbol: str) -> AssetClass:
    """Heuristic per D2 section 2.2. Returns the best-effort asset class.

    Order matters: currency-pair patterns are checked before the crypto
    shorthand so ``EURUSD`` does not get classified as crypto.
    """
    sym = symbol.upper().strip()
    if _CURRENCY_PAIR_RX.match(sym):
        return "currency"
    if _CRYPTO_DASH_RX.match(sym):
        return "crypto"
    if _CRYPTO_FLAT_RX.match(sym):
        return "crypto"
    if _CURRENCY_FLAT_RX.match(sym):
        return "currency"
    if _FUTURES_ROOT_RX.match(sym) or _FUTURES_YH_RX.match(sym) or sym.startswith("^"):
        return "commodity"
    return "equity"


# --- Request dataclass --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FMPRequest:
    """Inputs for a single ``FMPOHLCVProvider`` instance.

    ``interval`` is the Pine timeframe string (``"1D"``, ``"60"``, ``"5"``).
    It is translated to FMP's ``"1d" / "1h" / "5m"`` form before the call.
    ``start`` / ``end`` are tz-aware UTC datetimes; ``None`` means OpenBB's
    default window (1y back to today).
    """

    symbol: str
    interval: str
    start: date | datetime | None = None
    end: date | datetime | None = None
    asset_class: AssetClass | None = None


# --- Pine interval -> FMP interval --------------------------------------------

_PINE_TO_FMP_INTERVAL: dict[str, str] = {
    "1": "1m",
    "5": "5m",
    "15": "15m",
    "30": "30m",
    "60": "1h",
    "240": "4h",
    "1D": "1d",
    "D": "1d",
    "1W": "1d",  # FMP has no weekly; ScriptRunner resamples upward
    "W": "1d",
    "1M": "1d",
    "M": "1d",
}


def _translate_interval(pine_interval: str) -> str:
    """Translate a Pine timeframe string to FMP's interval enum.

    Falls back to the lowercased Pine value when the symbol already matches
    FMP's own ``{1m,5m,15m,30m,1h,4h,1d}`` set (e.g. callers passing ``"1d"``
    directly through the REST surface).
    """
    if pine_interval in _PINE_TO_FMP_INTERVAL:
        return _PINE_TO_FMP_INTERVAL[pine_interval]
    lowered = pine_interval.lower()
    if lowered in {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}:
        return lowered
    # Unknown -- pass through and let FMP's standard model raise.
    return pine_interval


# --- Lazy obb import ----------------------------------------------------------

def _import_obb() -> Any:
    """Lazy ``from openbb import obb`` so tests can patch this.

    Kept as a module-level function specifically so tests can do
    ``patch("openbb_pine.runtime.fmp_provider._import_obb", return_value=...)``
    without pulling the full ``openbb`` package into the test session.
    """
    from openbb import obb  # noqa: PLC0415  -- intentional lazy import
    return obb


# --- Timestamp coercion -------------------------------------------------------

def _ts_to_utc_seconds(ts: Any) -> int:
    """Coerce a pandas ``Timestamp`` / ``date`` / ``datetime`` to int seconds UTC.

    Daily bars are anchored at UTC midnight so the resulting integer is stable
    across rerun (matches PyneCore's ``_set_lib_properties`` which builds
    ``_datetime`` via ``datetime.fromtimestamp(ts, tz)``).
    """
    # Avoid importing pandas at module load.
    try:
        import pandas as pd  # noqa: PLC0415
    except ImportError:  # pragma: no cover -- pandas is a hard dep
        pd = None  # type: ignore[assignment]

    if pd is not None and isinstance(ts, pd.Timestamp):
        if ts.tzinfo is None:
            ts = ts.tz_localize(timezone.utc)
        return int(ts.timestamp())
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return int(ts.timestamp())
    if isinstance(ts, date):
        dt = datetime(ts.year, ts.month, ts.day, tzinfo=timezone.utc)
        return int(dt.timestamp())
    raise TypeError(f"Cannot coerce {type(ts).__name__} to UTC seconds")


def _make_ohlcv(timestamp: int, open_: float, high: float, low: float,
                close: float, volume: float) -> "OHLCV":
    """Construct a PyneCore OHLCV NamedTuple.

    The import lives here (lazily) rather than at module load so the
    extension's ``sys.path`` bridge (``openbb_pine/__init__.py``) has run
    before the import is attempted.
    """
    from pynecore.types.ohlcv import OHLCV  # noqa: PLC0415

    return OHLCV(
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


# --- The provider class -------------------------------------------------------


class FMPOHLCVProvider(Provider):
    """Yield bars from FMP / fmp_cached for one ``FMPRequest``.

    Post-E3.2: inherits :class:`pynecore.providers.Provider` (mode-2 per
    spec §5.2 / §6.2). Construction still takes ``FMPRequest`` — the
    request's ``symbol`` / ``interval`` become the mode-2 "default"
    that :meth:`stream` and :meth:`fetch` accept as call-time
    parameters (mode-2 accepts arbitrary symbol/timeframe at each call;
    we forward them into the FMP request builder). The existing
    ``executor_shell`` construction path is preserved verbatim so this
    refactor is behavior-preserving for M1 while unlocking polymorphic
    consumption through the ``Provider`` ABC in ``pyne_compiler``.

    The class is intentionally minimal: no retry budget (R4 — the
    envelope lives in ``executor_shell`` post-hoist), no
    ``request.security`` plumbing (Phase 2 bead — dispatcher owns it),
    no syminfo construction (out of scope for M1 — the abstract methods
    below are minimal stubs that either delegate or ``NotImplementedError``).
    """

    # --- Provider base-class configuration ------------------------------------

    # Base ``Provider.__init__`` calls ``load_config()`` which reads a
    # ``providers.toml`` from disk — irrelevant for FMP (credentials come
    # from OpenBB's ``user_settings.json``). ``config_keys`` is retained
    # for schema symmetry only.
    config_keys = {
        "# FMP credentials live in ~/.openbb_platform/user_settings.json": "",
    }

    def __init__(
        self,
        request: FMPRequest,
        *,
        provider: ProviderName | str,
        settings: Any | None = None,
    ) -> None:
        # Deliberately skip ``super().__init__``: the base constructor
        # requires an ``ohlv_dir`` / ``config_dir`` and eagerly opens a
        # ``providers.toml``, neither of which applies here. FMP is a
        # mode-2 REST provider that talks directly to the OpenBB call
        # surface, no on-disk .ohlcv round-trip. Setting the base-class
        # attributes explicitly keeps ``isinstance(x, Provider)`` +
        # attribute reads (``x.symbol``, ``x.timeframe``) well-defined.
        self.symbol = request.symbol
        self.timeframe = request.interval
        self.xchg_timeframe = _translate_interval(request.interval)
        self.ohlcv_path = None
        self.ohlcv_file = None
        self.config_dir = None
        self.config = {}

        self.request = request
        # ``resolve_provider`` enforces SUPPORTED_PROVIDERS -- a bad value
        # raises PineProviderError here, satisfying the
        # ``test_invalid_provider_raises_at_construction`` test.
        self.provider: ProviderName = resolve_provider(provider, settings=settings)
        self.provider_used: ProviderName = self.provider
        self._asset_class: AssetClass = request.asset_class or infer_asset_class(
            request.symbol
        )
        self._endpoint: Callable[..., Any] | None = None
        self.bars_consumed: int = 0

    # --- Provider ABC method implementations ---------------------------------
    #
    # These satisfy the abstract-method contract enough for
    # ``issubclass(FMPOHLCVProvider, Provider)`` + instantiation to work;
    # the M1 execution path exercises only stream()/fetch() (below) and
    # the pre-existing iter_ohlcv().

    @classmethod
    def to_tradingview_timeframe(cls, timeframe: str) -> str:
        """FMP's Pine-form timeframe already matches TV — pass through."""
        return timeframe

    @classmethod
    def to_exchange_timeframe(cls, timeframe: str) -> str:
        """Translate Pine timeframe -> FMP interval enum (D2 section 2.4)."""
        return _translate_interval(timeframe)

    def get_list_of_symbols(self, *args, **kwargs) -> list[str]:  # noqa: D401
        """FMP is mode-2; construction pins one symbol. Return it."""
        assert self.symbol is not None
        return [self.symbol]

    def update_symbol_info(self):  # pragma: no cover -- SymInfo out of M1 scope
        raise NotImplementedError(
            "FMPOHLCVProvider does not synthesize SymInfo in M1; the "
            "syminfo pipeline is executor-owned (see D2 §7 / bd-r7)."
        )

    def get_opening_hours_and_sessions(self) -> tuple[
        list[SymInfoInterval], list[SymInfoSession], list[SymInfoSession]
    ]:
        """No exchange calendar synthesized for M1 — dispatcher-owned."""
        return [], [], []

    def load_config(self) -> None:
        """No-op: FMP credentials come from OpenBB ``user_settings.json``."""
        self.config = {}

    def download_ohlcv(  # type: ignore[override]
        self,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
        on_progress: Callable[[datetime], None] | None = None,
        limit: int | None = None,
    ) -> None:
        """No-op: mode-2 provider queries REST directly in stream()/fetch();
        no ``.ohlcv`` file round-trip needed."""
        return

    # --- Public surface -------------------------------------------------------

    @property
    def asset_class(self) -> AssetClass:
        return self._asset_class

    def iter_ohlcv(self) -> Iterator["OHLCV"]:
        """Yield ``OHLCV`` NamedTuples in time-ascending order.

        Increments ``self.bars_consumed`` per yield. Single-pass (does not
        rewind the underlying DataFrame).
        """
        df = self._fetch()
        for ts, row in df.iterrows():
            self.bars_consumed += 1
            yield _make_ohlcv(
                timestamp=_ts_to_utc_seconds(ts),
                open_=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume") or 0.0),
            )

    # --- Internals ------------------------------------------------------------

    def _fetch(self) -> Any:
        """Call the asset-class-appropriate endpoint and return a DataFrame."""
        obb = _import_obb()
        endpoint = self._endpoint_for(self._asset_class, obb)
        obbj = endpoint(
            symbol=self.request.symbol,
            start_date=self.request.start,
            end_date=self.request.end,
            interval=_translate_interval(self.request.interval),
            provider=self.provider,
        )
        # OpenBB's OBBject exposes ``to_df`` (older) and ``to_dataframe``
        # (current). Prefer ``to_df`` because it matches the existing
        # techtrade engine call and is what tests mock.
        to_df = getattr(obbj, "to_df", None) or getattr(obbj, "to_dataframe", None)
        if to_df is None:  # pragma: no cover -- defensive
            raise TypeError(
                "OBBject lacks to_df / to_dataframe -- cannot translate to OHLCV"
            )
        return to_df()

    @staticmethod
    def _endpoint_for(asset_class: AssetClass, obb: Any) -> Callable[..., Any]:
        """Asset-class dispatch table -- D2 section 2.2."""
        if asset_class == "equity":
            return obb.equity.price.historical
        if asset_class == "crypto":
            return obb.crypto.price.historical
        if asset_class == "currency":
            return obb.currency.price.historical
        if asset_class == "commodity":
            return obb.commodity.price.historical
        raise ValueError(f"unknown asset class {asset_class!r}")

    # --- Provider.stream / Provider.fetch overrides (spec §5) ----------------

    def stream(  # type: ignore[override]
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        include_gaps: bool = False,
    ) -> Iterator["OHLCV"]:
        """Yield OHLCV bars for ``(symbol, timeframe)`` via the FMP REST call.

        Mode-2 (spec §5.2): ``symbol`` and ``timeframe`` are call-time
        parameters, and a call-time value that differs from the request's
        construction-time value rebuilds the ``FMPRequest`` for the call.
        This lets ``pyne_compiler``'s ``request.security`` path reuse a
        single provider instance across secondaries without allocating a
        fresh REST client each call.

        Behavioral contract (spec §5 / conformance suite E1.4):
          * ``start`` / ``end`` inclusive; naive datetimes raise ``TypeError``.
          * ``start > end`` yields nothing (SQL-consistent).
          * Yielded ``OHLCV.timestamp`` values are UTC epoch seconds (int).
          * ``include_gaps`` is accepted for API parity; FMP bars carry no
            gap-fill sentinel, so it is a no-op here.
        """
        del include_gaps  # FMP has no gap sentinels; accepted for API parity.

        # Guard: naive datetimes are ambiguous cross-machine (spec §5).
        if start is not None and start.tzinfo is None:
            raise TypeError(
                "start must be a timezone-aware datetime (spec §5); "
                "got naive datetime which is ambiguous across timezones."
            )
        if end is not None and end.tzinfo is None:
            raise TypeError(
                "end must be a timezone-aware datetime (spec §5); "
                "got naive datetime which is ambiguous across timezones."
            )

        # Guard: reversed range -> empty (spec §5.4 check #4).
        if start is not None and end is not None and start > end:
            return

        # Mode-2 rebind: build a per-call FMPRequest so call-time
        # (symbol, timeframe) wins over the construction-time defaults.
        # ``start`` / ``end`` also override the construction-time window
        # so ``request.security`` can query a different range without
        # touching the base FMPRequest.
        call_request = FMPRequest(
            symbol=symbol,
            interval=timeframe,
            start=start if start is not None else self.request.start,
            end=end if end is not None else self.request.end,
            asset_class=infer_asset_class(symbol),
        )

        # Snapshot + temporarily rebind so ``_fetch()`` picks up the
        # call-time values without a wider refactor of ``iter_ohlcv``.
        # Restoring in the ``finally`` keeps the provider instance
        # stateless across calls (spec §5.4 check #7).
        saved_request = self.request
        saved_asset_class = self._asset_class
        self.request = call_request
        self._asset_class = call_request.asset_class or infer_asset_class(symbol)
        try:
            # ``iter_ohlcv`` already handles OBBject -> OHLCV NamedTuple
            # conversion and bars_consumed accounting; delegate to it.
            for bar in self.iter_ohlcv():
                yield bar
        finally:
            self.request = saved_request
            self._asset_class = saved_asset_class

    def fetch(  # type: ignore[override]
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        include_gaps: bool = False,
    ) -> list["OHLCV"]:
        """Materialize :meth:`stream` as a list. Spec §5.1 equivalence."""
        return list(self.stream(
            symbol, timeframe, start=start, end=end, include_gaps=include_gaps,
        ))


__all__ = [
    "AssetClass",
    "FMPOHLCVProvider",
    "FMPRequest",
    "ProviderName",
    "SUPPORTED_PROVIDERS",
    "infer_asset_class",
]
