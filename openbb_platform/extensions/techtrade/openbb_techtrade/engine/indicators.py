"""Pure pandas-ta-classic -> IndicatorPanel adapter (issue #72, PRD §11).

This module is a *pure* adapter: :func:`build_indicator_panel` takes a symbol, an
``as_of`` session date, and that symbol's OHLCV history and returns an
:class:`~openbb_techtrade.models.IndicatorPanel` carrying the five indicator
families (trend / momentum / volatility / volume / candles). It performs no
network I/O -- the live OHLCV fetch sits behind the injectable
``_default_ohlcv_fetcher`` seam consumed by the thin wrapper
:func:`build_panel_for_symbol`, exactly mirroring the DI seam in
``openbb_techtrade.engine.movers`` so unit tests stay fully offline.

The default periods are the PRD §11 set, frozen in :class:`IndicatorConfig`
(``DEFAULT_CONFIG``) and overridable per call. Determinism rests on three legs:
fixed periods, the commit-pinned pandas-ta-classic submodule (#71-guarded), and
``talib=False`` on every ``df.ta.*`` call that accepts it -- this forces the
native, cross-machine-stable math path rather than an optional TA-Lib C backend
that may or may not be installed. Indicator *values* are plain Python ``float``
(candle signals are ``int`` in ``{-1, 0, 1}``); volume that arrives as ``Decimal``
is coerced to ``float`` only while building the working frame.

DataFrame-returning indicators are selected by column *prefix* (e.g. ``MACDh``),
never by exact name, because the numeric suffix formatting (``_2`` vs ``_2.0``) is
unstable across the library. Warm-up bars yield NaN; only a finite value on the
``as_of`` (last) bar is stored, so the panel carries only populated indicators and
a too-short history simply omits the long-period keys rather than raising.

``pandas`` and ``pandas_ta_classic`` are imported lazily inside the function
bodies (not at module top level) to keep importing this module light, matching the
lazy-import convention used throughout the techtrade engine.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from openbb_techtrade.models import IndicatorPanel


@dataclass(frozen=True)
class IndicatorConfig:
    """Indicator periods for the panel builder (PRD §11 defaults).

    A frozen, hashable bundle of the lookback periods / multipliers each
    ``df.ta.*`` call is parameterised with. The defaults are the PRD §11 set;
    pass a customised instance to :func:`build_indicator_panel` to override them.

    Parameters
    ----------
    macd_fast : int
        MACD fast EMA length (default ``12``).
    macd_slow : int
        MACD slow EMA length (default ``26``).
    macd_signal : int
        MACD signal EMA length (default ``9``).
    adx_length : int
        ADX smoothing length (default ``14``).
    ema_fast : int
        Fast trend-EMA length (default ``20``).
    ema_slow : int
        Slow trend-EMA length (default ``50``).
    rsi_length : int
        RSI length (default ``14``).
    stoch_k : int
        Stochastic ``%K`` length (default ``14``).
    stoch_d : int
        Stochastic ``%D`` smoothing length (default ``3``).
    stoch_smooth_k : int
        Stochastic ``%K`` smoothing length (default ``3``).
    bb_length : int
        Bollinger Bands length (default ``20``).
    bb_std : float
        Bollinger Bands standard-deviation multiple (default ``2.0``).
    atr_length : int
        Average True Range length (default ``14``).
    kc_length : int
        Keltner Channel length (default ``20``).
    kc_scalar : float
        Keltner Channel ATR multiple (default ``2.0``).
    obv_slope_length : int
        Look-back over which the OBV slope is measured (default ``10``).
    cmf_length : int
        Chaikin Money Flow length (default ``20``).
    """

    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    adx_length: int = 14
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_length: int = 14
    stoch_k: int = 14
    stoch_d: int = 3
    stoch_smooth_k: int = 3
    bb_length: int = 20
    bb_std: float = 2.0
    atr_length: int = 14
    kc_length: int = 20
    kc_scalar: float = 2.0
    obv_slope_length: int = 10
    cmf_length: int = 20


#: The PRD §11 default indicator configuration used when no override is supplied.
DEFAULT_CONFIG = IndicatorConfig()


def _get(row: object, key: str) -> object:
    """Read ``key`` from an OHLCV row exposing either dict keys or attributes.

    OHLCV rows arrive as provider data objects (attribute access) in the live path
    and as plain dicts in unit tests; this normalises both, mirroring the reader in
    ``openbb_techtrade.engine.movers``.

    Parameters
    ----------
    row : object
        A mapping or an object exposing ``open/high/low/close/volume``.
    key : str
        The field name to read.

    Returns
    -------
    object
        The field value, or ``None`` when the key / attribute is absent.
    """
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def ohlcv_to_frame(rows: list) -> object:
    """Build a lowercase float OHLCV ``DataFrame`` from raw rows (pure).

    Produces the canonical ``open/high/low/close/volume`` float columns the
    ``df.ta.*`` accessor expects, in input (chronological) order. ``Decimal``
    volume (and any ``Decimal`` price) is coerced to ``float`` here so the rest of
    the pipeline only ever sees floats. ``pandas`` is imported lazily.

    Parameters
    ----------
    rows : list
        Chronologically ascending OHLCV rows, each exposing ``open``, ``high``,
        ``low``, ``close`` and ``volume`` via dict key or attribute.

    Returns
    -------
    pandas.DataFrame
        A frame with columns ``["open", "high", "low", "close", "volume"]``.

    Raises
    ------
    ValueError
        If ``rows`` is empty (no frame can be built).
    """
    import pandas as pd

    rows = list(rows)
    if not rows:
        raise ValueError("ohlcv_rows is empty; cannot build an indicator frame.")

    data = {
        "open": [float(_get(r, "open")) for r in rows],
        "high": [float(_get(r, "high")) for r in rows],
        "low": [float(_get(r, "low")) for r in rows],
        "close": [float(_get(r, "close")) for r in rows],
        "volume": [float(_get(r, "volume")) for r in rows],
    }
    return pd.DataFrame(data, columns=["open", "high", "low", "close", "volume"])


def _col(df: object, prefix: str) -> str | None:
    """Return the first column of ``df`` whose name starts with ``prefix``.

    DataFrame-returning indicators are addressed by prefix rather than exact name
    because the numeric suffix formatting (``_2`` vs ``_2.0``) is unstable. When
    ``df`` is not a populated ``DataFrame`` (e.g. an indicator degraded on too few
    bars and returned the original OHLCV frame), no indicator column matches and
    ``None`` is returned.

    Parameters
    ----------
    df : object
        The indicator result, expected to be a ``pandas.DataFrame``.
    prefix : str
        The column-name prefix to search for (e.g. ``"MACDh"``).

    Returns
    -------
    str | None
        The first matching column name, or ``None`` when none matches.
    """
    import pandas as pd

    if not isinstance(df, pd.DataFrame):
        return None
    for name in df.columns:
        if str(name).startswith(prefix):
            return name
    return None


def _last_finite(series: object) -> float | None:
    """Return the ``as_of`` (last) bar value of a Series, if finite.

    The last bar is the requested ``as_of`` session; its value is returned as a
    ``float`` only when it is finite. Warm-up bars are NaN (early in the series),
    so a too-short history leaves the last bar NaN and yields ``None`` -- which the
    callers translate into an omitted key. When ``series`` is not a ``pandas.Series``
    (an indicator degraded to the original frame on too few bars), ``None`` is
    returned as well.

    Parameters
    ----------
    series : object
        The indicator result, expected to be a ``pandas.Series``.

    Returns
    -------
    float | None
        The finite last-bar value, or ``None`` when unavailable / non-finite.
    """
    import pandas as pd

    if not isinstance(series, pd.Series) or series.empty:
        return None
    value = series.iloc[-1]
    if value is None:
        return None
    fvalue = float(value)
    return fvalue if math.isfinite(fvalue) else None


def _df_last_finite(df: object, prefix: str) -> float | None:
    """Last finite value of the ``prefix``-matched column of ``df``.

    Convenience that combines :func:`_col` (prefix column selection) with
    :func:`_last_finite` (finite last-bar extraction) for DataFrame-returning
    indicators such as MACD, ADX, Stochastics, Bollinger %B, and Keltner.

    Parameters
    ----------
    df : object
        The indicator result, expected to be a ``pandas.DataFrame``.
    prefix : str
        The column-name prefix identifying the wanted series.

    Returns
    -------
    float | None
        The finite last-bar value of the matched column, or ``None``.
    """
    col = _col(df, prefix)
    if col is None:
        return None
    return _last_finite(df[col])


def _sign(value: float) -> int:
    """Normalise a value to its unit sign ``-1`` / ``0`` / ``+1``.

    Used to fold TA-Lib's candlestick magnitudes (``±100`` / ``±80`` / ``0``) into
    a directional flag.

    Parameters
    ----------
    value : float
        The value to take the sign of.

    Returns
    -------
    int
        ``1`` if ``value > 0``, ``-1`` if ``value < 0``, else ``0``.
    """
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _compute_trend(df: object, config: IndicatorConfig) -> dict[str, float]:
    """Compute the trend family on the ``as_of`` bar (omitting non-finite values).

    Populates ``macd_hist`` (MACD histogram), ``adx``, ``ema_fast``, ``ema_slow``
    and the derived ``ema_cross`` (``ema_fast - ema_slow``, present only when both
    EMAs are). Every ``df.ta.*`` call passes ``talib=False`` for deterministic
    native math; DataFrame results are addressed by column prefix.

    Parameters
    ----------
    df : object
        The lowercase OHLCV ``pandas.DataFrame``.
    config : IndicatorConfig
        Period configuration.

    Returns
    -------
    dict[str, float]
        Finite trend-indicator values keyed by canonical name.
    """
    out: dict[str, float] = {}

    macd = df.ta.macd(fast=config.macd_fast, slow=config.macd_slow, signal=config.macd_signal, talib=False)
    macd_hist = _df_last_finite(macd, "MACDh")
    if macd_hist is not None:
        out["macd_hist"] = macd_hist

    adx = df.ta.adx(length=config.adx_length, talib=False)
    adx_value = _df_last_finite(adx, "ADX_")
    if adx_value is not None:
        out["adx"] = adx_value

    ema_fast = _last_finite(df.ta.ema(length=config.ema_fast, talib=False))
    if ema_fast is not None:
        out["ema_fast"] = ema_fast

    ema_slow = _last_finite(df.ta.ema(length=config.ema_slow, talib=False))
    if ema_slow is not None:
        out["ema_slow"] = ema_slow

    if ema_fast is not None and ema_slow is not None:
        out["ema_cross"] = ema_fast - ema_slow

    return out


def _compute_momentum(df: object, config: IndicatorConfig) -> dict[str, float]:
    """Compute the momentum family on the ``as_of`` bar (omitting non-finite values).

    Populates ``rsi`` plus the Stochastic ``stoch_k`` / ``stoch_d``. All calls use
    ``talib=False``; the Stochastic DataFrame is addressed by column prefix.

    Parameters
    ----------
    df : object
        The lowercase OHLCV ``pandas.DataFrame``.
    config : IndicatorConfig
        Period configuration.

    Returns
    -------
    dict[str, float]
        Finite momentum-indicator values keyed by canonical name.
    """
    out: dict[str, float] = {}

    rsi = _last_finite(df.ta.rsi(length=config.rsi_length, talib=False))
    if rsi is not None:
        out["rsi"] = rsi

    stoch = df.ta.stoch(k=config.stoch_k, d=config.stoch_d, smooth_k=config.stoch_smooth_k, talib=False)
    stoch_k = _df_last_finite(stoch, "STOCHk")
    if stoch_k is not None:
        out["stoch_k"] = stoch_k
    stoch_d = _df_last_finite(stoch, "STOCHd")
    if stoch_d is not None:
        out["stoch_d"] = stoch_d

    return out


def _compute_volatility(df: object, config: IndicatorConfig) -> dict[str, float]:
    """Compute the volatility family on the ``as_of`` bar (omitting non-finite values).

    Populates Bollinger ``bb_pctb`` (%B), ``atr``, and the Keltner ``kc_upper`` /
    ``kc_lower`` bands. All calls use ``talib=False``; the Bollinger and Keltner
    DataFrames are addressed by column prefix.

    Parameters
    ----------
    df : object
        The lowercase OHLCV ``pandas.DataFrame``.
    config : IndicatorConfig
        Period configuration.

    Returns
    -------
    dict[str, float]
        Finite volatility-indicator values keyed by canonical name.
    """
    out: dict[str, float] = {}

    bbands = df.ta.bbands(length=config.bb_length, std=config.bb_std, talib=False)
    bb_pctb = _df_last_finite(bbands, "BBP_")
    if bb_pctb is not None:
        out["bb_pctb"] = bb_pctb

    atr = _last_finite(df.ta.atr(length=config.atr_length, talib=False))
    if atr is not None:
        out["atr"] = atr

    keltner = df.ta.kc(length=config.kc_length, scalar=config.kc_scalar, talib=False)
    # Match "KCU"/"KCL" (not "KCUe"/"KCLe"): the trailing mamode letter is derived
    # from kc()'s mamode (``e`` for the default EMA), so a shorter prefix stays
    # correct if that ever changes while remaining unambiguous (basis is "KCB").
    kc_upper = _df_last_finite(keltner, "KCU")
    if kc_upper is not None:
        out["kc_upper"] = kc_upper
    kc_lower = _df_last_finite(keltner, "KCL")
    if kc_lower is not None:
        out["kc_lower"] = kc_lower

    return out


def _compute_volume(df: object, config: IndicatorConfig) -> dict[str, float]:
    """Compute the volume family on the ``as_of`` bar (omitting non-finite values).

    Populates ``obv_slope`` (the slope of On-Balance Volume over the configured
    look-back) and ``cmf`` (Chaikin Money Flow). All calls use ``talib=False``; the
    OBV slope feeds the OBV Series into ``df.ta.slope``.

    Parameters
    ----------
    df : object
        The lowercase OHLCV ``pandas.DataFrame``.
    config : IndicatorConfig
        Period configuration.

    Returns
    -------
    dict[str, float]
        Finite volume-indicator values keyed by canonical name.
    """
    out: dict[str, float] = {}

    obv = df.ta.obv(talib=False)
    obv_slope = _last_finite(df.ta.slope(close=obv, length=config.obv_slope_length, talib=False))
    if obv_slope is not None:
        out["obv_slope"] = obv_slope

    cmf = _last_finite(df.ta.cmf(length=config.cmf_length, talib=False))
    if cmf is not None:
        out["cmf"] = cmf

    return out


def _compute_candles(df: object) -> dict[str, int]:
    """Detect candlestick patterns firing on the ``as_of`` (last) bar.

    Runs ``df.ta.cdl_pattern(name="all")`` (no ``talib`` kwarg -- that call does not
    accept one), inspects only the last bar, keeps the columns whose TA-Lib value is
    non-zero, and folds each magnitude into a unit sign via :func:`_sign`. Pattern
    names are lowercased. On too few bars ``cdl_pattern`` can raise, so the call is
    guarded and degrades to an empty mapping.

    Parameters
    ----------
    df : object
        The lowercase OHLCV ``pandas.DataFrame``.

    Returns
    -------
    dict[str, int]
        ``{pattern_name_lowercased: sign}`` for the patterns that fired (sign in
        ``{-1, 1}``); empty when none fire or detection is unavailable.
    """
    import pandas as pd

    try:
        cdl = df.ta.cdl_pattern(name="all")
    except Exception:  # noqa: BLE001 - too few bars / detector unavailable -> no candles
        return {}

    if not isinstance(cdl, pd.DataFrame) or cdl.empty:
        return {}

    last = cdl.iloc[-1]
    out: dict[str, int] = {}
    for name, value in last.items():
        if value is None:
            continue
        fvalue = float(value)
        if not math.isfinite(fvalue) or fvalue == 0.0:
            continue
        out[str(name).lower()] = _sign(fvalue)
    return out


def build_indicator_panel(
    symbol: str,
    as_of: date,
    ohlcv_rows: list,
    *,
    config: IndicatorConfig | None = None,
) -> IndicatorPanel:
    """Build a per-symbol :class:`IndicatorPanel` from OHLCV history (pure, no network).

    Converts ``ohlcv_rows`` to a lowercase float frame and computes the five
    indicator families on the ``as_of`` (last) bar via the pandas-ta-classic ``.ta``
    accessor, all with ``talib=False`` for deterministic native math. Importing
    ``pandas_ta_classic`` here registers the ``.ta`` accessor for the compute
    helpers and is the module's only dependency on the vendored submodule. Non-finite
    warm-up values are omitted, so a short history simply yields fewer populated
    keys instead of raising.

    Parameters
    ----------
    symbol : str
        The instrument symbol (echoed onto the panel).
    as_of : date
        Session date the indicators are computed for (the last bar of ``ohlcv_rows``).
    ohlcv_rows : list
        Chronologically ascending OHLCV rows (dict or attribute), through the last
        ``as_of`` bar.
    config : IndicatorConfig | None, optional
        Indicator periods. ``None`` (default, **keyword-only**, #83 L9): consult
        ``~/.openbb_platform/techtrade_tuned.json`` for ``symbol``'s GICS sector via
        :func:`openbb_techtrade.tuning.tuned_defaults.lookup_tuned_for_symbol` and
        use the tuned :class:`IndicatorConfig` if a robust entry is present for
        that sector; otherwise fall back to :data:`DEFAULT_CONFIG` (PRD §11). Pass
        ``config=X`` explicitly to bypass the auto-load (caller intent wins --
        useful for golden / regression tests).

    Returns
    -------
    IndicatorPanel
        The assembled panel with trend / momentum / volatility / volume / candles.

    Raises
    ------
    ValueError
        If ``ohlcv_rows`` is empty (propagated from :func:`ohlcv_to_frame`).

    Notes
    -----
    The auto-load adds one ``os.stat`` per call on the hot path (the
    :func:`~openbb_techtrade.tuning.tuned_defaults._read_tuned_cached` ``lru_cache``
    is keyed on ``(path, mtime_ns, st_size)`` so the parse cost is paid once per
    file write, not per symbol). The lookup module imports neither ``tuneta`` nor
    ``openbb_backtest``, so it is safe to call on a bare techtrade install.
    """
    import pandas_ta_classic  # noqa: F401 - registers the pandas ``.ta`` accessor

    if config is None:
        # Lazy import: avoids a hot-path import cycle if any future tuning module
        # needs to import indicators (none does today; cheap insurance).
        from openbb_techtrade.tuning.tuned_defaults import lookup_tuned_for_symbol  # noqa: PLC0415
        config = lookup_tuned_for_symbol(symbol) or DEFAULT_CONFIG

    df = ohlcv_to_frame(ohlcv_rows)
    return IndicatorPanel(
        symbol=symbol,
        as_of=as_of,
        trend=_compute_trend(df, config),
        momentum=_compute_momentum(df, config),
        volatility=_compute_volatility(df, config),
        volume=_compute_volume(df, config),
        candles=_compute_candles(df),
    )


def _default_ohlcv_fetcher(
    symbol: str,
    as_of: date,
    *,
    lookback: int = 260,
    calendar: str = "XNYS",
) -> list:
    """Fetch a symbol's recent OHLCV history from live fmp_cached (integration-only).

    Pulls daily bars from ``obb.equity.price.historical`` ending on ``as_of`` and
    returns the trailing ``lookback`` rows. The ``start_date`` reaches back roughly
    ``2 * lookback`` calendar days so that, after weekends and holidays drop out,
    at least ``lookback`` trading sessions are available to warm up the long-period
    indicators. ``openbb`` is imported lazily and ``fmp_cached`` is the only provider
    used, mirroring the engine's no-fallback contract.

    Parameters
    ----------
    symbol : str
        The instrument symbol to fetch.
    as_of : date
        Resolved session date bounding ``end_date`` (no look-ahead).
    lookback : int, optional
        Number of trailing OHLCV bars to keep. Defaults to ``260``.
    calendar : str, optional
        Exchange-calendar code (accepted for a uniform fetcher signature; the daily
        history endpoint does not need it). Defaults to ``"XNYS"``.

    Returns
    -------
    list
        The last ``lookback`` OHLCV result rows (possibly fewer if history is short).
    """
    from openbb import obb

    start = (as_of - timedelta(days=lookback * 2)).isoformat()
    history = obb.equity.price.historical(
        symbol=symbol,
        start_date=start,
        end_date=as_of.isoformat(),
        provider="fmp_cached",
    )
    return (history.results or [])[-lookback:]


def build_panel_for_symbol(
    symbol: str,
    *,
    as_of: date | str | None = None,
    calendar: str = "XNYS",
    ohlcv_fetcher: Callable[..., list] | None = None,
    lookback: int = 260,
    config: IndicatorConfig = DEFAULT_CONFIG,
) -> IndicatorPanel:
    """Build a symbol's :class:`IndicatorPanel` over live (or injected) OHLCV history.

    Thin live wrapper around :func:`build_indicator_panel`: it snaps ``as_of`` to the
    most recent trading session via ``resolve_session`` (no look-ahead), fetches the
    OHLCV history through the injectable ``ohlcv_fetcher`` seam, then delegates to the
    pure core. The default fetcher is the live :func:`_default_ohlcv_fetcher`
    (fmp_cached); unit tests inject an offline fake. The fetcher is invoked as
    ``fetcher(symbol, session, lookback=..., calendar=...)``, so injected fakes
    should accept ``**kwargs`` (tests use ``def fake(symbol, as_of, **kwargs)``).

    Parameters
    ----------
    symbol : str
        The instrument symbol to build the panel for.
    as_of : date | str | None, optional
        Requested date, snapped to a session. Defaults to today when ``None``.
    calendar : str, optional
        Exchange-calendar code for session snapping. Defaults to ``"XNYS"``.
    ohlcv_fetcher : Callable[..., list] | None, optional
        OHLCV-fetcher seam; defaults to the live :func:`_default_ohlcv_fetcher`.
    lookback : int, optional
        Number of trailing OHLCV bars to request. Defaults to ``260``.
    config : IndicatorConfig, optional
        Period configuration. Defaults to :data:`DEFAULT_CONFIG` (PRD §11).

    Returns
    -------
    IndicatorPanel
        The panel for ``symbol`` on the resolved session.
    """
    from openbb_techtrade.engine.movers import resolve_session

    session = resolve_session(as_of, calendar)
    fetcher = ohlcv_fetcher or _default_ohlcv_fetcher
    rows = fetcher(symbol, session, lookback=lookback, calendar=calendar)
    return build_indicator_panel(symbol, session, rows, config=config)
