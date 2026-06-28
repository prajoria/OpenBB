"""Reuse-first indicator source selector (issue #73, PRD §8).

PRD §8 requires *reuse-first*: each indicator is computed from exactly one source,
never twice. This module is that decision made explicit. :data:`INDICATOR_SOURCE`
is the static audit record mapping every panel key to ``"technical"`` (served by
OpenBB's first-party ``technical`` extension via the #73 adapter) or ``"classic"``
(served by the #72 pandas-ta-classic builder). The trend / momentum / volatility
keys are technical-covered; ``obv_slope``, ``cmf`` and the candlestick patterns are
classic-only.

:func:`build_panel` is the single entry point. ``source="auto"`` (the default)
prefers the technical adapter when the extension is installed and silently falls
back to the classic builder otherwise -- so a machine without ``technical`` (this
checkout) yields the exact #72 panel. ``source="classic"`` and ``source="technical"``
force a leg; an unknown source raises ``ValueError``.

:func:`build_panels_bulk` computes panels for many symbols in one call, returning a
result contractually *identical* to calling :func:`build_panel` once per symbol.
Because that exact-equality contract demands the same code path per symbol, the
bulk path iterates the per-symbol builder rather than running a single fused
``ta.Strategy``: the per-call ``df.ta.*`` accessor used by the #72 builder is
single-indicator and synchronous, so it never spawns the multiprocessing ``Pool``
that ``ta.Strategy`` would (the Windows fork-bomb is a ``.strategy()`` hazard, not a
single-call one). The batch is therefore single-process and fork-bomb-safe by
construction, with byte-identical output.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from openbb_techtrade.engine.indicators import (
    DEFAULT_CONFIG,
    IndicatorConfig,
    build_indicator_panel,
)
from openbb_techtrade.engine.indicators_technical import technical_panel
from openbb_techtrade.models import IndicatorPanel

#: One-source-per-indicator audit map (PRD §8). ``"technical"`` keys are served by
#: the OpenBB ``technical`` extension when available (else classic in ``auto``);
#: ``"classic"`` keys are only ever served by the #72 pandas-ta-classic builder.
INDICATOR_SOURCE: dict[str, str] = {
    # trend
    "macd_hist": "technical",
    "adx": "technical",
    "ema_fast": "technical",
    "ema_slow": "technical",
    "ema_cross": "technical",
    # momentum
    "rsi": "technical",
    "stoch_k": "technical",
    "stoch_d": "technical",
    # volatility
    "bb_pctb": "technical",
    "atr": "technical",
    "kc_upper": "technical",
    "kc_lower": "technical",
    # volume (not covered by technical)
    "obv_slope": "classic",
    "cmf": "classic",
    # candlestick patterns (not covered by technical)
    "candles": "classic",
}

#: Accepted ``source`` selectors for :func:`build_panel`.
Source = Literal["auto", "classic", "technical"]
_VALID_SOURCES = frozenset({"auto", "classic", "technical"})


def build_panel(
    symbol: str,
    as_of: date,
    ohlcv_rows: list,
    *,
    config: IndicatorConfig = DEFAULT_CONFIG,
    source: Source = "auto",
) -> IndicatorPanel:
    """Assemble one :class:`IndicatorPanel` from the selected indicator source.

    Routes by ``source``: ``"auto"`` and ``"technical"`` both use the technical
    adapter, which self-guards -- it sources covered indicators from
    ``obb.technical.*`` when the extension is importable and silently degrades to
    the classic #72 builder otherwise; ``"classic"`` always uses the #72 builder.
    This is the reuse-first entry point -- callers never compute an indicator twice.

    Parameters
    ----------
    symbol : str
        The instrument symbol (echoed onto the panel).
    as_of : date
        Session date the indicators are computed for (last bar of ``ohlcv_rows``).
    ohlcv_rows : list
        Chronologically ascending OHLCV rows (dict or attribute), through ``as_of``.
    config : IndicatorConfig, optional
        Period configuration. Defaults to :data:`DEFAULT_CONFIG` (PRD §11).
    source : str, optional
        One of ``"auto"`` (default), ``"classic"`` or ``"technical"``.

    Returns
    -------
    IndicatorPanel
        The assembled panel for ``symbol`` on ``as_of``.

    Raises
    ------
    ValueError
        If ``source`` is not one of ``"auto"``, ``"classic"`` or ``"technical"``.
    """
    if source not in _VALID_SOURCES:
        raise ValueError(f"unknown source {source!r}; expected one of {sorted(_VALID_SOURCES)}")

    if source == "classic":
        return build_indicator_panel(symbol, as_of, ohlcv_rows, config=config)
    # auto / technical: the adapter self-guards and degrades to classic when the
    # technical extension is unavailable, so both share one path (no extra probe).
    return technical_panel(symbol, as_of, ohlcv_rows, config=config)


def build_panels_bulk(
    frames: dict[str, list],
    as_of: date,
    *,
    config: IndicatorConfig = DEFAULT_CONFIG,
    source: Source = "auto",
) -> dict[str, IndicatorPanel]:
    """Build an :class:`IndicatorPanel` for each symbol in ``frames`` (batch).

    ``frames`` maps each symbol to its OHLCV rows; the return maps each symbol to
    its panel. The result is contractually identical to calling :func:`build_panel`
    once per symbol with the same ``source``. The per-symbol classic leg runs
    single-indicator ``df.ta.*`` calls (synchronous, no multiprocessing ``Pool``),
    so iterating the per-symbol builder keeps the batch single-process and
    fork-bomb-safe on Windows while preserving byte-identical output -- a fused
    ``ta.Strategy`` is deliberately avoided because its spawn ``Pool`` is the
    fork-bomb hazard and it would not guarantee exact per-symbol equality.

    Parameters
    ----------
    frames : dict[str, list]
        ``{symbol: ohlcv_rows}`` for every symbol in the batch.
    as_of : date
        Session date all panels are computed for.
    config : IndicatorConfig, optional
        Period configuration. Defaults to :data:`DEFAULT_CONFIG` (PRD §11).
    source : str, optional
        One of ``"auto"`` (default), ``"classic"`` or ``"technical"``; applied to
        every symbol.

    Returns
    -------
    dict[str, IndicatorPanel]
        ``{symbol: IndicatorPanel}`` for every symbol in ``frames``.

    Raises
    ------
    ValueError
        If ``source`` is invalid (propagated from :func:`build_panel`).
    """
    return {
        symbol: build_panel(symbol, as_of, rows, config=config, source=source)
        for symbol, rows in frames.items()
    }
