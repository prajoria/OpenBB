"""The ONLY techtrade module that imports ``tuneta`` (#83 L6, L8, Q-G).

Lazy in-body import discipline (mirrors #82's
:mod:`openbb_techtrade.validation.backtest_bridge`):

- :func:`_require_tuneta` lazy-imports :class:`tuneta.tune_ta.TuneTA` and raises
  the reused :class:`TechtradeDependencyError` (introduced by #82) with a
  ready-to-run ``pip install 'openbb-techtrade[tuneta]'`` hint when ``tuneta``
  is not installed.
- :data:`KNOB_TABLE` is the L6 single source of truth: 8 period knobs, each
  paired with its tuneta indicator name and ``(low, high)`` range.
- :func:`parse_tuned_columns` is a pure-Python regex-based parser over tuneta's
  emitted column-name encoding (no ``tuneta`` import -- testable on a bare
  install).
- :func:`fit_segment` is the glue: configures a :class:`TuneTA`, runs
  :meth:`fit`, calls :meth:`transform` to read the chosen periods from the
  resulting column names, and returns the candidate :class:`IndicatorConfig`
  plus the metadata :class:`~openbb_techtrade.models.TuningReport` will record
  (``tuneta_version``, ``fit_seconds``, ``tuned_columns``).

Every other module in this package is safe to import on a bare techtrade install
(no extras). Only this module triggers the ``import tuneta`` chain -- and only
when :func:`_require_tuneta` or :func:`fit_segment` is actually called.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import replace
from typing import Any

import pandas as pd

from openbb_techtrade.engine.indicators import DEFAULT_CONFIG, IndicatorConfig
from openbb_techtrade.validation.backtest_bridge import TechtradeDependencyError

logger = logging.getLogger(__name__)

#: Hint emitted with TechtradeDependencyError (verbatim copy-pasteable).
_PIP_INSTALL_HINT: str = "pip install 'openbb-techtrade[tuneta]'"

#: The L6 8-knob spec: (IndicatorConfig field name, tuneta indicator string, (low, high) range).
#: The order is the order tuneta receives them in :func:`fit_segment` and is also the
#: order tested by ``test_knob_table_has_exactly_eight_period_knobs``.
KNOB_TABLE: tuple[tuple[str, str, tuple[int, int]], ...] = (
    ("macd_fast",    "tta.MACD", (8, 20)),
    ("macd_slow",    "tta.MACD", (20, 40)),
    ("macd_signal",  "tta.MACD", (5, 15)),
    ("adx_length",   "tta.ADX",  (10, 30)),
    ("ema_fast",     "tta.EMA",  (10, 30)),
    ("ema_slow",     "tta.EMA",  (30, 80)),
    ("rsi_length",   "tta.RSI",  (8, 30)),
    ("atr_length",   "tta.ATR",  (10, 30)),
)


# --- lazy guard -------------------------------------------------------------------------------


def _require_tuneta() -> Any:
    """Lazily import ``tuneta``'s :class:`TuneTA`, or raise a clear error.

    Returns the :class:`TuneTA` class so callers can instantiate it. Mirrors
    :func:`openbb_techtrade.validation.backtest_bridge._require_backtest` shape
    for shape.

    Raises
    ------
    TechtradeDependencyError
        When ``tuneta`` is not importable. Message carries
        ``pip install 'openbb-techtrade[tuneta]'``.
    """
    try:
        from tuneta.tune_ta import TuneTA
    except ImportError as exc:
        raise TechtradeDependencyError(
            "obb.techtrade.tune requires the 'tuneta' package, which is not "
            f"installed. Install it with: {_PIP_INSTALL_HINT}"
        ) from exc
    return TuneTA


def _tuneta_version() -> str:
    """Return ``tuneta.__version__`` or ``'unknown'`` (lazy; used by :func:`fit_segment`)."""
    try:
        import tuneta  # noqa: PLC0415 - lazy

        return getattr(tuneta, "__version__", "unknown")
    except ImportError:
        return "unknown"


# --- column-name parser (pure, no tuneta import) -----------------------------------------------


_COLUMN_RX: dict[str, re.Pattern] = {
    "rsi_length":  re.compile(r"^tta_RSI_timeperiod_(\d+)$"),
    "adx_length":  re.compile(r"^tta_ADX_timeperiod_(\d+)$"),
    "atr_length":  re.compile(r"^tta_ATR_timeperiod_(\d+)$"),
    "macd_fast":   re.compile(
        r"^tta_MACD_fastperiod_(\d+)_slowperiod_\d+_signalperiod_\d+$"
    ),
    "macd_slow":   re.compile(
        r"^tta_MACD_fastperiod_\d+_slowperiod_(\d+)_signalperiod_\d+$"
    ),
    "macd_signal": re.compile(
        r"^tta_MACD_fastperiod_\d+_slowperiod_\d+_signalperiod_(\d+)$"
    ),
}
_EMA_RX = re.compile(r"^tta_EMA_timeperiod_(\d+)$")
#: EMA "fast" binding range. Inclusive on both ends -- a period of exactly 30
#: binds to ``ema_fast`` (the lower-bound winner at the (10,30)/(30,80) overlap).
_EMA_FAST_RANGE = (10, 30)
#: EMA "slow" binding range. The lower bound is exclusive so that period 30
#: prefers ``ema_fast``; the upper bound (80) is inclusive.
_EMA_SLOW_RANGE = (30, 80)


def parse_tuned_columns(columns: list[str]) -> IndicatorConfig:
    """Parse tuneta's emitted column names into an :class:`IndicatorConfig` (L6 + EMA binding).

    Recognised single-period columns (RSI / ADX / ATR / MACD bundle) are bound
    by regex. EMAs are bound by **range** (Step 1 sharp edge in design §3.2):
    the period in :data:`_EMA_FAST_RANGE` ``(10, 30)`` becomes ``ema_fast``;
    the period in :data:`_EMA_SLOW_RANGE` ``(30, 80)`` becomes ``ema_slow``.
    A period of exactly ``30`` lies on the overlap and binds to ``ema_fast``
    (the boundary operators are ``<=`` for the fast upper bound and ``<`` for
    the slow lower bound, so ``10 <= 30 <= 30`` wins before
    ``30 < 30`` even fires). Unrecognised columns log at WARNING and leave
    their knob at :data:`DEFAULT_CONFIG`.

    A MACD column matches three regexes (``macd_fast`` / ``macd_slow`` /
    ``macd_signal``); the parser deliberately does not break on the first
    match so all three slots fill from one column.

    Always returns a fully-populated :class:`IndicatorConfig`: the 7 untuned
    knobs (stoch / bb / kc / obv_slope / cmf fields) are copied verbatim from
    :data:`DEFAULT_CONFIG`.
    """
    updates: dict[str, int] = {}
    ema_periods: list[int] = []

    for col in columns:
        matched_any = False
        for field, pattern in _COLUMN_RX.items():
            m = pattern.match(col)
            if m is not None:
                updates[field] = int(m.group(1))
                matched_any = True
                # MACD columns match three patterns -- keep checking so all three slots fill.
        ema_match = _EMA_RX.match(col)
        if ema_match is not None:
            ema_periods.append(int(ema_match.group(1)))
            matched_any = True
        if not matched_any:
            logger.warning("tuneta_adapter: unrecognised column %r -- knob stays at default", col)

    # Bind EMAs by range. 30 binds to ema_fast (see docstring + range docs above).
    for period in ema_periods:
        if _EMA_FAST_RANGE[0] <= period <= _EMA_FAST_RANGE[1]:
            updates["ema_fast"] = period
        elif _EMA_SLOW_RANGE[0] < period <= _EMA_SLOW_RANGE[1]:
            updates["ema_slow"] = period
        else:
            logger.warning(
                "tuneta_adapter: EMA period %d outside (10,30) and (30,80) -- skipping", period
            )

    return replace(DEFAULT_CONFIG, **updates)


# --- fit_segment ------------------------------------------------------------------------------


def fit_segment(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    trials: int = 100,
    early_stop: int = 20,
) -> tuple[IndicatorConfig, dict[str, Any]]:
    """Run :meth:`TuneTA.fit` over the L6 knob set and parse the result.

    The Q-D budget defaults (``trials=100``, ``early_stop=20``) are the tuneta
    README defaults; ``verbose=False`` is forced to keep the techtrade log
    surface clean (tuneta defaults to chatty).

    Parameters
    ----------
    X, y
        From :func:`pool_sector_ohlcv` -- MultiIndex ``(date, symbol)`` OHLCV and
        forward-cumulative-return series, aligned.
    trials, early_stop
        Optuna budget knobs forwarded verbatim to :meth:`TuneTA.fit`.

    Returns
    -------
    tuple[IndicatorConfig, dict]
        ``(candidate, meta)`` where ``meta`` carries ``{"tuneta_version": str,
        "fit_seconds": float, "tuned_columns": list[str]}`` for
        :class:`~openbb_techtrade.models.TuningReport`.

    Raises
    ------
    TechtradeDependencyError
        When ``tuneta`` is not installed (via :func:`_require_tuneta`).
    """
    TuneTA = _require_tuneta()  # noqa: N806 - mirrors tuneta's class name
    indicators = [indicator for _, indicator, _ in KNOB_TABLE]
    ranges = [rng for _, _, rng in KNOB_TABLE]

    start = time.perf_counter()
    tt = TuneTA(n_jobs=4, verbose=False)
    tt.fit(X, y, indicators=indicators, ranges=ranges, trials=trials, early_stop=early_stop)
    transformed = tt.transform(X)
    fit_seconds = time.perf_counter() - start

    columns = list(transformed.columns)
    candidate = parse_tuned_columns(columns)
    meta = {
        "tuneta_version": _tuneta_version(),
        "fit_seconds": fit_seconds,
        "tuned_columns": columns,
    }
    return candidate, meta
