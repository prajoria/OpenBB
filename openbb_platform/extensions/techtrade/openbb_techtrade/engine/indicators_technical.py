"""OpenBB-``technical``-extension -> IndicatorPanel adapter (issue #73, PRD §8/§11).

This is the *reuse* leg of the selector: where OpenBB's first-party ``technical``
extension already implements a PRD §11 indicator, :func:`technical_panel` sources
that indicator from ``obb.technical.*`` rather than recomputing it with the #72
pandas-ta-classic path. The two indicators not covered by ``technical``
(``obv_slope``, ``cmf``) and the candlestick patterns are filled from the #72
helpers, so a single panel is assembled from exactly one source per indicator.

Two facts make the explicit-period contract load-bearing. First, ``technical``'s
command defaults diverge from PRD §11 (``bbands(length=50)``, ``adx(length=50)``,
``kc(scalar=20)``, ``ema(length=50)``), so every covered call passes the §11
period explicitly or parity against classic breaks. Second, the ``mamode`` /
``scalar`` families *do* align with §11 (bbands ``sma``, atr ``rma``, kc ``ema``,
rsi / adx ``scalar=100``), so those are left at their defaults.

Graceful degradation is the safety net: when ``openbb_technical`` is not
importable (as in this checkout), or any technical call raises,
:func:`technical_panel` delegates wholesale to the #72
:func:`~openbb_techtrade.engine.indicators.build_indicator_panel`, preserving the
requested panel selector. ``openbb`` is imported lazily inside the function body,
never at module top level, matching the engine-wide lazy-import convention.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from openbb_techtrade.engine.indicators import (
    DEFAULT_CONFIG,
    IndicatorConfig,
    _compute_candles,
    _compute_volume,
    _df_last_finite,
    build_indicator_panel,
    ohlcv_to_frame,
)
from openbb_techtrade.models import IndicatorPanel

_logger = logging.getLogger(__name__)

#: Synthetic index origin for the ``date`` column technical commands require.
_INDEX_ORIGIN = date(2000, 1, 1)


def _obb_technical_available() -> bool:
    """Return ``True`` iff the OpenBB ``technical`` extension is importable.

    A lazy, side-effect-free probe (via :func:`importlib.util.find_spec`) that
    never imports ``openbb`` and never raises -- any failure is folded to
    ``False`` so callers can branch on availability cheaply. In this checkout the
    ``technical`` extension is not installed, so this returns ``False`` and the
    adapter takes the classic fallback path.

    Returns
    -------
    bool
        ``True`` when ``openbb_technical`` can be located, else ``False``.
    """
    import importlib.util  # pylint: disable=import-outside-toplevel

    try:
        return importlib.util.find_spec("openbb_technical") is not None
    except Exception:  # noqa: BLE001 - any probe failure means "not available"
        return False


def _load_obb() -> Any:
    """Return the live ``openbb.obb`` application object (the injectable obb seam).

    Mirrors the engine-wide DI convention (cf. the ``candidate_fetcher`` /
    ``ohlcv_fetcher`` seams): every live ``obb.*`` access goes through one tiny
    lazy-import function so unit tests can substitute an offline fake -- here by
    passing ``obb_loader`` to :func:`technical_panel` -- and the default suite stays
    hermetic. ``openbb`` is imported inside the body, never at module top level.

    Returns
    -------
    object
        The imported ``openbb.obb`` application object.
    """
    from openbb import obb  # pylint: disable=import-outside-toplevel

    return obb


def _to_data_records(df: Any) -> list[dict]:
    """Add a synthetic ascending ``date`` column and return ``data=[...]`` rows.

    OpenBB ``technical`` commands consume ``data: list[Data]`` and key off an
    ``index`` column (default ``"date"``); the lowercase OHLCV frame carries no
    such column, so a deterministic ascending daily date is inserted (its absolute
    values are irrelevant -- only the ordering and uniqueness matter for the
    rolling indicator math). ``pandas`` is imported lazily.

    Parameters
    ----------
    df : object
        The lowercase OHLCV ``pandas.DataFrame`` from :func:`ohlcv_to_frame`.

    Returns
    -------
    list[dict]
        One record per bar, each carrying ``date`` plus the OHLCV columns.
    """
    out = df.copy()
    dates = [(_INDEX_ORIGIN + timedelta(days=i)).isoformat() for i in range(len(out))]
    out.insert(0, "date", dates)
    return out.to_dict("records")


def _tech_df(result: Any) -> Any:
    """Convert a ``technical`` command result (OBBject) to a ``pandas.DataFrame``.

    Reads ``result.results`` (a ``list[Data]``), dumps each row to a plain dict,
    and frames them so the shared :func:`_df_last_finite` prefix selector can pull
    the appended indicator column. ``pandas`` is imported lazily.

    Parameters
    ----------
    result : object
        The OBBject returned by an ``obb.technical.*`` command.

    Returns
    -------
    pandas.DataFrame
        The result rows (original columns plus the appended indicator columns).
    """
    import pandas as pd  # pylint: disable=import-outside-toplevel

    rows = getattr(result, "results", None) or []
    records = [r.model_dump() if hasattr(r, "model_dump") else dict(r) for r in rows]
    return pd.DataFrame(records)


def _compute_technical_trend(
    obb: Any, records: list[dict], config: IndicatorConfig
) -> dict[str, float]:
    """Compute the trend family from ``obb.technical.*`` with explicit §11 periods.

    Sources ``macd_hist`` / ``adx`` / ``ema_fast`` / ``ema_slow`` (and the derived
    ``ema_cross``) from the first-party technical commands, passing the PRD §11
    periods explicitly because technical's own defaults differ (``adx``/``ema``
    default to 50). Non-finite warm-up values are omitted.

    Parameters
    ----------
    obb : object
        The imported ``openbb.obb`` application object.
    records : list[dict]
        OHLCV rows with a ``date`` index column (see :func:`_to_data_records`).
    config : IndicatorConfig
        Period configuration (PRD §11 defaults).

    Returns
    -------
    dict[str, float]
        Finite trend-indicator values keyed by canonical name.
    """
    out: dict[str, float] = {}

    macd = obb.technical.macd(
        data=records,
        fast=config.macd_fast,
        slow=config.macd_slow,
        signal=config.macd_signal,
    )
    macd_hist = _df_last_finite(_tech_df(macd), "close_MACDh")
    if macd_hist is not None:
        out["macd_hist"] = macd_hist

    adx_value = _df_last_finite(
        _tech_df(obb.technical.adx(data=records, length=config.adx_length)), "ADX_"
    )
    if adx_value is not None:
        out["adx"] = adx_value

    ema_fast = _df_last_finite(
        _tech_df(obb.technical.ema(data=records, length=config.ema_fast)), "close_EMA_"
    )
    if ema_fast is not None:
        out["ema_fast"] = ema_fast

    ema_slow = _df_last_finite(
        _tech_df(obb.technical.ema(data=records, length=config.ema_slow)), "close_EMA_"
    )
    if ema_slow is not None:
        out["ema_slow"] = ema_slow

    if ema_fast is not None and ema_slow is not None:
        out["ema_cross"] = ema_fast - ema_slow

    return out


def _compute_technical_momentum(
    obb: Any, records: list[dict], config: IndicatorConfig
) -> dict[str, float]:
    """Compute the momentum family from ``obb.technical.*`` with explicit §11 periods.

    Sources ``rsi`` and the Stochastic ``stoch_k`` / ``stoch_d`` from the
    technical commands. Stochastic periods map to technical's
    ``fast_k_period`` / ``slow_d_period`` / ``slow_k_period`` arguments.

    Parameters
    ----------
    obb : object
        The imported ``openbb.obb`` application object.
    records : list[dict]
        OHLCV rows with a ``date`` index column.
    config : IndicatorConfig
        Period configuration (PRD §11 defaults).

    Returns
    -------
    dict[str, float]
        Finite momentum-indicator values keyed by canonical name.
    """
    out: dict[str, float] = {}

    rsi = _df_last_finite(
        _tech_df(obb.technical.rsi(data=records, length=config.rsi_length)),
        "close_RSI_",
    )
    if rsi is not None:
        out["rsi"] = rsi

    stoch = _tech_df(
        obb.technical.stoch(
            data=records,
            fast_k_period=config.stoch_k,
            slow_d_period=config.stoch_d,
            slow_k_period=config.stoch_smooth_k,
        )
    )
    stoch_k = _df_last_finite(stoch, "STOCHk")
    if stoch_k is not None:
        out["stoch_k"] = stoch_k
    stoch_d = _df_last_finite(stoch, "STOCHd")
    if stoch_d is not None:
        out["stoch_d"] = stoch_d

    return out


def _compute_technical_volatility(
    obb: Any, records: list[dict], config: IndicatorConfig
) -> dict[str, float]:
    """Compute the volatility family from ``obb.technical.*`` with explicit §11 periods.

    Sources Bollinger ``bb_pctb`` (the ``BBP`` %B column), ``atr``, and the Keltner
    ``kc_upper`` / ``kc_lower`` bands. Bollinger length is passed explicitly (the
    technical default is 50); the ``mamode`` defaults (bbands ``sma``, atr ``rma``,
    kc ``ema``) already match PRD §11.

    Parameters
    ----------
    obb : object
        The imported ``openbb.obb`` application object.
    records : list[dict]
        OHLCV rows with a ``date`` index column.
    config : IndicatorConfig
        Period configuration (PRD §11 defaults).

    Returns
    -------
    dict[str, float]
        Finite volatility-indicator values keyed by canonical name.
    """
    out: dict[str, float] = {}

    bb_pctb = _df_last_finite(
        _tech_df(
            obb.technical.bbands(
                data=records, length=config.bb_length, std=config.bb_std
            )
        ),
        "close_BBP_",
    )
    if bb_pctb is not None:
        out["bb_pctb"] = bb_pctb

    atr = _df_last_finite(
        _tech_df(obb.technical.atr(data=records, length=config.atr_length)), "ATR"
    )
    if atr is not None:
        out["atr"] = atr

    keltner = _tech_df(
        obb.technical.kc(data=records, length=config.kc_length, scalar=config.kc_scalar)
    )
    kc_upper = _df_last_finite(keltner, "KCU")
    if kc_upper is not None:
        out["kc_upper"] = kc_upper
    kc_lower = _df_last_finite(keltner, "KCL")
    if kc_lower is not None:
        out["kc_lower"] = kc_lower

    return out


def technical_panel(
    symbol: str,
    as_of: date,
    ohlcv_rows: list,
    *,
    config: IndicatorConfig = DEFAULT_CONFIG,
    obb_loader: Callable[[], object] | None = None,
    panel_config=None,
) -> IndicatorPanel:
    """Build an :class:`IndicatorPanel` sourcing covered indicators from ``technical``.

    When the OpenBB ``technical`` extension is available, the trend / momentum /
    volatility families are computed via ``obb.technical.*`` (with explicit PRD §11
    periods), while ``volume`` (``obv_slope`` / ``cmf``) and ``candles`` are filled
    from the #72 classic helpers -- one source per indicator. When ``technical`` is
    absent, or any technical call raises, the whole panel is delegated to the #72
    :func:`build_indicator_panel`, preserving ``panel_config``. Classic requests
    remain byte-identical to classic; extended requests retain their extended keys.

    The live ``obb`` object is obtained through the injectable ``obb_loader`` seam
    (default :func:`_load_obb`), mirroring the engine-wide DI convention so unit
    tests drive the technical path with an offline fake and the default suite stays
    hermetic. Injecting an ``obb_loader`` forces the technical path regardless of
    whether the real extension is installed; with the default loader the path is
    taken only when :func:`_obb_technical_available` is true. ``openbb`` /
    ``pandas_ta_classic`` are imported lazily (inside the seam / the body).

    Parameters
    ----------
    symbol : str
        The instrument symbol (echoed onto the panel).
    as_of : date
        Session date the indicators are computed for (the last bar of ``ohlcv_rows``).
    ohlcv_rows : list
        Chronologically ascending OHLCV rows (dict or attribute), through ``as_of``.
    config : IndicatorConfig, optional
        Period configuration. Defaults to :data:`DEFAULT_CONFIG` (PRD §11).
    obb_loader : Callable[[], object] | None, optional
        Zero-arg seam returning the ``obb`` object; defaults to the live
        :func:`_load_obb`. Tests inject a fake to exercise the technical leg offline.

    Returns
    -------
    IndicatorPanel
        The assembled panel with trend / momentum / volatility / volume / candles.

    Raises
    ------
    ValueError
        If ``ohlcv_rows`` is empty (propagated from :func:`ohlcv_to_frame`).
    """
    # Resolve the obb seam: an injected loader forces the technical leg (tests);
    # otherwise use the live loader only when the real extension is importable.
    if obb_loader is None and not _obb_technical_available():
        # bd-7ct.5 (bd-ctt): forward panel_config to the classic fallback.
        # In the fallback path, build_indicator_panel handles dispatch to
        # the _ext stubs; a None panel_config resolves to PANEL_CLASSIC
        # there (double-default is intentional — keeps the fallback path
        # byte-identical to pre-bd-7ct when no kwarg is supplied).
        return build_indicator_panel(
            symbol,
            as_of,
            ohlcv_rows,
            config=config,
            panel_config=panel_config,
        )
    loader = obb_loader or _load_obb

    # bd-7ct.5 caveat: the tech leg below always uses classic panel keys
    # (`_compute_technical_trend/momentum/volatility`). Family PRs
    # (bd-luy/40v/z43) will add `_compute_technical_*_ext` mirrors when
    # they land — until then, callers that pass `panel_config=PANEL_EXTENDED`
    # on a machine with obb.technical installed silently get the classic
    # panel from the tech branch, and the extended stubs from the fallback
    # branch only. Since the stubs are pass-through in bd-7ct, this is
    # observationally identical — but it's a real limitation to close
    # in the family PRs.
    #
    # iter-1 code-reviewer YELLOW (a): emit a WARNING when a caller
    # explicitly requests the extended panel on this branch so future
    # "why is my extended flag doing nothing on my openbb_technical
    # box?" tickets have a hint in the logs. Costs nothing today
    # (stubs pass through so behavior is unchanged) but is the loud
    # signal family PRs need to observe when they partially wire the
    # tech-leg mirrors.
    if panel_config is not None and getattr(panel_config, "panel", None) == "extended":
        _logger.warning(
            "technical_panel: PANEL_EXTENDED requested but tech-leg "
            "mirrors (_compute_technical_*_ext) not yet implemented — "
            "silently downgrading to classic panel for symbol %s. "
            "Family PRs (bd-luy/40v/z43) will address this.",
            symbol,
        )

    # Build the frame here (outside the try) so empty/invalid input raises
    # ValueError cleanly rather than being caught below and mislabelled a
    # "technical failure"; the classic fallback path builds it once internally.
    df = ohlcv_to_frame(ohlcv_rows)

    try:
        import pandas_ta_classic  # noqa: F401  # pylint: disable=import-outside-toplevel,unused-import

        obb = loader()
        records = _to_data_records(df)
        return IndicatorPanel(
            symbol=symbol,
            as_of=as_of,
            trend=_compute_technical_trend(obb, records, config),
            momentum=_compute_technical_momentum(obb, records, config),
            volatility=_compute_technical_volatility(obb, records, config),
            volume=_compute_volume(df, config),
            candles=_compute_candles(df),
        )
    except (
        Exception
    ):  # noqa: BLE001 - any technical failure degrades to the deterministic #72 panel
        _logger.warning(
            "technical_panel for %s degraded to the classic #72 builder after an "
            "openbb.technical failure; the panel is still correct but not technical-sourced.",
            symbol,
            exc_info=True,
        )
        return build_indicator_panel(
            symbol,
            as_of,
            ohlcv_rows,
            config=config,
            panel_config=panel_config,
        )
