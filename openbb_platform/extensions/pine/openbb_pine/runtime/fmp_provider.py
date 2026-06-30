"""FMP-backed OHLCV provider for the Pine runtime.

Single concrete class -- no Provider protocol, no registry (D2 section 2.3,
PRD section 13.8). PyneCore's ``ScriptRunner`` consumes ``Iterable[OHLCV]``
directly, so we yield ``pynecore.types.ohlcv.OHLCV`` NamedTuples ourselves
rather than subclassing the vendored ``pynecore.providers.Provider`` ABC.

Asset-class dispatch (D2 section 2.2) routes each symbol to the matching
``obb.<asset>.price.historical`` surface:

* ``equity`` -> ``obb.equity.price.historical``
* ``crypto`` -> ``obb.crypto.price.historical``
* ``currency`` (forex) -> ``obb.currency.price.historical``
* ``commodity`` -> ``obb.commodity.price.historical``

Tests mock the ``obb`` call surface so they pass without an FMP API key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Iterator, Literal

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


class FMPOHLCVProvider:
    """Yield bars from FMP / fmp_cached for one ``FMPRequest``.

    The class is intentionally minimal: no retry budget (R4), no
    ``request.security`` plumbing (Phase 2 bead), no syminfo construction
    (handled by the executor in R7). It exists to feed
    ``ScriptRunner.run_iter``.
    """

    def __init__(
        self,
        request: FMPRequest,
        *,
        provider: ProviderName | str,
        settings: Any | None = None,
    ) -> None:
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


__all__ = [
    "AssetClass",
    "FMPOHLCVProvider",
    "FMPRequest",
    "ProviderName",
    "SUPPORTED_PROVIDERS",
    "infer_asset_class",
]
