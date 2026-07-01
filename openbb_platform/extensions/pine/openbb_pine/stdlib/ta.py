"""Pine ``ta.*`` namespace bridges (S-beads 0e9.5.16-51).

Each function here is a **thin delegating wrapper** over the vendored
``pynecore.lib.ta`` implementation. PyneCore owns the numerics; we own the
compile-time signature (see :mod:`openbb_pine.compiler.builtin_signatures`)
and the runtime dispatch shape returned into the ``@pyne`` machinery.

Wave organisation: each parallel-dispatch subagent appends its own block
delimited by the ``# ---- Wave 5B-N: <topic> ----`` banner. Do NOT
interleave blocks — the 3-way merge relies on block-append order for a
clean automatic union. Place new blocks at the END of the file, after any
existing block from a sibling subagent.

Every bridge:

* takes and returns the shapes declared by ``BUILTIN_SIGNATURES``,
* delegates to ``pynecore.lib.ta.<name>`` with the same argument names,
* does NO error handling (C3's type checker enforces qualifiers at
  compile time; runtime type errors surface as PyneCore ``assert``s).

When a new bridge lands its corresponding ``BUILTIN_SIGNATURES`` entry's
``notes`` field flips from ``"STUB"`` to ``"IMPLEMENTED"`` and the name is
added to :data:`openbb_pine._coverage_manifest.BUILTINS_IMPLEMENTED` so the
L0.5 wild-corpus coverage metric ticks up.
"""

from __future__ import annotations

from pynecore.lib import ta as _pyne_ta

__all__: list[str] = []


# ==============================================================================
# ---- Wave 5B-1: moving averages ----
# Owns: ta.sma, ta.ema, ta.wma, ta.rma, ta.macd
# ==============================================================================


def sma(source, length: int):
    """Pine ``ta.sma(source, length)`` — Simple Moving Average.

    Delegates to :func:`pynecore.lib.ta.sma`. The output series equals the
    arithmetic mean of the last ``length`` values of ``source``; the first
    ``length-1`` bars are ``NA`` per Pine's warm-up convention.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is ``(src: series<float>, length: simple<int>) -> series<float>``.
    """
    return _pyne_ta.sma(source, length)


def ema(source, length: int):
    """Pine ``ta.ema(source, length)`` — Exponential Moving Average.

    Delegates to :func:`pynecore.lib.ta.ema`. Warm-up phase (first
    ``length-1`` bars) returns ``NA``; the first warmed bar seeds with
    ``SMA(source, length)``; subsequent bars use
    ``α·source + (1-α)·prev`` with ``α = 2/(length+1)``.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is ``(src: series<float>, length: simple<int>) -> series<float>``.
    """
    return _pyne_ta.ema(source, length)


def wma(source, length: int):
    """Pine ``ta.wma(source, length)`` — Weighted Moving Average.

    Delegates to :func:`pynecore.lib.ta.wma`. Linear-weighted average of
    the last ``length`` bars: the most recent bar carries weight ``length``,
    the oldest weight ``1``; denominator is ``length*(length+1)/2``.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is ``(src: series<float>, length: simple<int>) -> series<float>``.
    """
    return _pyne_ta.wma(source, length)


def rma(source, length: int):
    """Pine ``ta.rma(source, length)`` — Wilder's / Running Moving Average.

    Delegates to :func:`pynecore.lib.ta.rma`. Equivalent to
    ``ema(source, length, α=1/length)`` — the smoothing factor Wilder used
    for RSI's built-in average-gain / average-loss channels.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is ``(src: series<float>, length: simple<int>) -> series<float>``.
    """
    return _pyne_ta.rma(source, length)


def macd(source, fastlen: int, slowlen: int, siglen: int):
    """Pine ``ta.macd(source, fastlen, slowlen, siglen)`` — MACD triple.

    Delegates to :func:`pynecore.lib.ta.macd`. Returns a 3-tuple
    ``(macd_line, signal_line, histogram)`` where:

    * ``macd_line = ema(source, fastlen) - ema(source, slowlen)``
    * ``signal_line = ema(macd_line, siglen)``
    * ``histogram = macd_line - signal_line``

    Warm-up bars where any component is ``NA`` propagate ``NA`` through the
    downstream components.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(src: series<float>, fastlen: simple<int>, slowlen: simple<int>,
    siglen: simple<int>) -> tuple[series<float>, series<float>, series<float>]``.
    """
    return _pyne_ta.macd(source, fastlen, slowlen, siglen)


__all__ += ["sma", "ema", "wma", "rma", "macd"]


# ==============================================================================
# ---- Wave 5B-2: momentum + oscillators ----
# Owns: ta.rsi, ta.stoch, ta.cci, ta.adx, ta.mfi
# ==============================================================================


def rsi(source, length: int):
    """Pine ``ta.rsi(source, length)`` — Relative Strength Index.

    Delegates to :func:`pynecore.lib.ta.rsi`. Uses Wilder's smoothing
    (``rma`` over up-moves / down-moves) internally; warm-up returns
    ``NA`` until ``length`` bars have been observed, then produces a
    value in ``[0, 100]``.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is ``(src: series<float>, length: simple<int>) -> series<float>``.
    PyneCore names the first arg ``source``; the C3 registry names it
    ``src`` (the shorter Pine-reference name). Positional dispatch keeps
    both sides interoperable — the bridge never binds by name.
    """
    return _pyne_ta.rsi(source, length)


def stoch(source, high, low, length: int):
    """Pine ``ta.stoch(source, high, low, length)`` — Stochastic %K.

    Delegates to :func:`pynecore.lib.ta.stoch`. Returns only the fast %K
    component; the %D signal line is a separate ``ta.sma(ta.stoch(...), 3)``
    application in Pine (see TradingView Pine reference — %D is user-side
    smoothing, not part of the ``ta.stoch`` primitive).

    Warm-up returns ``NA`` until ``length`` bars of both ``high`` and
    ``low`` history are available; the output is clamped to ``[0, 100]``.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(src: series<float>, high: series<float>, low: series<float>,
    length: simple<int>) -> series<float>``. The C3 registry uses ``src``
    where PyneCore uses ``source`` — positional dispatch keeps them
    aligned; see :func:`rsi` for the same convention.
    """
    return _pyne_ta.stoch(source, high, low, length)


def cci(source, length: int):
    """Pine ``ta.cci(source, length)`` — Commodity Channel Index.

    Delegates to :func:`pynecore.lib.ta.cci`. Computes
    ``(source - sma(source, length)) / (0.015 * mean_dev)`` where
    ``mean_dev`` is the mean absolute deviation of ``source`` over the
    same window; warm-up returns ``NA`` until the window is full.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is ``(src: series<float>, length: simple<int>) -> series<float>``.
    """
    return _pyne_ta.cci(source, length)


def adx(dilen: int, adxlen: int):
    """Pine ``ta.adx(dilen, adxlen)`` — Average Directional Index.

    Delegates to :func:`pynecore.lib.ta.dmi` and returns the third element
    of the ``(+DI, -DI, ADX)`` triple. **PyneCore does NOT expose a
    standalone ``adx`` function** — the Pine reference documents
    ``ta.adx(dilen, adxlen)`` as a convenience over the full DMI
    computation, so the bridge synthesises it by projecting ``dmi()[2]``.

    Both parameters gate warm-up: the true-range machinery inside
    ``ta.dmi`` needs ``dilen`` bars for the +DI / -DI channels, and
    ``adxlen`` further bars for the ADX smoothing (Wilder's RMA) on top.
    Returns ``NA`` throughout warm-up.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is ``(dilen: simple<int>, adxlen: simple<int>) -> series<float>``.
    ``ta.adx`` is NOT one of the 29 PRD §3.2 Phase-1 builtins; Wave 5B-2
    added its registry entry alongside this bridge because the parent
    bead spec ``0e9.5.26`` names it explicitly.
    """
    return _pyne_ta.dmi(dilen, adxlen)[2]


def mfi(source, length: int):
    """Pine ``ta.mfi(source, length)`` — Money Flow Index.

    Delegates to :func:`pynecore.lib.ta.mfi`. Volume-weighted RSI: the
    up / down "money flow" is ``volume * source`` gated by whether
    ``ta.change(source)`` is positive or negative, then folded through
    ``100 - 100/(1 + upper/lower)`` (analogous to RSI but without the
    Wilder smoothing).

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is ``(src: series<float>, length: simple<int>) -> series<float>``.
    Requires ``volume`` to be present on the OHLCV stream — the executor's
    ``BYODataProvider`` validation catches missing-volume up front.
    """
    return _pyne_ta.mfi(source, length)


__all__ += ["rsi", "stoch", "cci", "adx", "mfi"]


# ==============================================================================
# ---- Wave 5B-4: signals + transforms + rolling utilities ----
# Owns: ta.crossover, ta.crossunder, ta.highest, ta.lowest, ta.change,
#       ta.mom, ta.roc, ta.linreg, ta.median,
#       ta.percentile_linear_interpolation, ta.cum, ta.barssince
# ==============================================================================


def crossover(source1, source2):
    """Pine ``ta.crossover(source1, source2)`` — crossover detector.

    Delegates to :func:`pynecore.lib.ta.crossover`. Returns ``True`` on the
    bar where ``source1`` transitions from below-or-equal to strictly above
    ``source2`` (i.e. ``source1 > source2 and source1[1] <= source2[1]``),
    else ``False``. Persistent state carries the prior bar's comparison
    across bar boundaries per PyneCore's implementation.

    NA-gap handling matches TradingView: bars where either input is ``NA``
    do NOT reset the persistent state — the comparison resumes against the
    last bar where both inputs were defined (PyneCore's implementation at
    ``ta.py:454`` explicitly documents this).

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(source1: series<float>, source2: series<float>) -> series<bool>``.
    """
    return _pyne_ta.crossover(source1, source2)


def crossunder(source1, source2):
    """Pine ``ta.crossunder(source1, source2)`` — crossunder detector.

    Delegates to :func:`pynecore.lib.ta.crossunder`. Returns ``True`` on the
    bar where ``source1`` transitions from above-or-equal to strictly below
    ``source2`` (i.e. ``source1 < source2 and source1[1] >= source2[1]``),
    else ``False``. Symmetric to :func:`crossover`; same NA-gap posture.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(source1: series<float>, source2: series<float>) -> series<bool>``.
    """
    return _pyne_ta.crossunder(source1, source2)


def highest(source, length: int):
    """Pine ``ta.highest(source, length)`` — rolling maximum.

    Delegates to :func:`pynecore.lib.ta.highest`. Returns the highest value
    of ``source`` over the last ``length`` bars including the current bar;
    the first ``length-1`` bars are ``NA`` per Pine's warm-up convention.

    PyneCore also defines a second overload ``ta.highest(length)`` that
    defaults ``source`` to ``high``; the bridge exposes only the
    explicit-source form since sugar-form calls compile through codegen's
    arg-fill (Phase-2 concern), not through the bridge shape.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(source: series<float>, length: simple<int>) -> series<float>``.
    """
    return _pyne_ta.highest(source, length)


def lowest(source, length: int):
    """Pine ``ta.lowest(source, length)`` — rolling minimum.

    Delegates to :func:`pynecore.lib.ta.lowest`. Returns the lowest value
    of ``source`` over the last ``length`` bars including the current bar;
    the first ``length-1`` bars are ``NA``. Symmetric to :func:`highest`;
    same second-overload posture — the bridge exposes only the
    explicit-source form.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(source: series<float>, length: simple<int>) -> series<float>``.
    """
    return _pyne_ta.lowest(source, length)


def change(source, length: int = 1):
    """Pine ``ta.change(source, length=1)`` — bar-over-bar difference.

    Delegates to :func:`pynecore.lib.ta.change`. Returns
    ``source - source[length]`` for numeric ``source`` (int/float); for
    boolean ``source`` returns ``source != source[length]``. ``length``
    defaults to ``1`` per Pine's public signature; PyneCore's implementation
    ``assert``s ``length > 0``.

    Warm-up: ``NA`` when ``source[length]`` is not yet defined (first
    ``length`` bars).

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(source: series<float>, length: simple<int>) -> series<float>``.
    The ``length=1`` default lives in the bridge only — C3's stub registry
    does not model per-arg defaults; the type checker's ``_check_call_args``
    tolerates a missing trailing positional (see ``type_checker.py:812``).
    """
    return _pyne_ta.change(source, length)


def mom(source, length: int):
    """Pine ``ta.mom(source, length)`` — momentum.

    Delegates to :func:`pynecore.lib.ta.mom`. Semantically identical to
    ``ta.change(source, length)`` — PyneCore's implementation is literally
    a one-line delegation ``return change(source, length)``
    (``ta.py:1068``). Kept as a distinct Pine builtin so user-facing script
    intent stays readable.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(source: series<float>, length: simple<int>) -> series<float>``.
    """
    return _pyne_ta.mom(source, length)


def roc(source, length: int):
    """Pine ``ta.roc(source, length)`` — rate of change (percentage).

    Delegates to :func:`pynecore.lib.ta.roc`. Returns
    ``100 * (source - source[length]) / source[length]``. Warm-up (first
    ``length`` bars where ``source[length]`` is ``NA``) returns ``NA``.

    Divide-by-zero: PyneCore does not guard the divisor; a
    ``source[length]`` of exactly ``0.0`` propagates a Python
    ``ZeroDivisionError`` from PyneCore's ``ta.roc``. TradingView's
    reference emits ``+inf`` / ``-inf`` (or ``NaN`` for ``0/0``) —
    matching this exactly is a PyneCore concern and out of scope for the
    bridge.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(source: series<float>, length: simple<int>) -> series<float>``.
    """
    return _pyne_ta.roc(source, length)


def linreg(source, length: int, offset: int):
    """Pine ``ta.linreg(source, length, offset)`` — linear regression value.

    Delegates to :func:`pynecore.lib.ta.linreg`. Fits an OLS line to the
    last ``length`` bars of ``source`` and returns
    ``intercept + slope * ((length - 1) - offset)``.

    ``offset`` is a REQUIRED positional argument (no default), matching
    PyneCore's signature and the Pine reference manual — the common
    "current-bar value" call is ``ta.linreg(source, length, 0)``.
    Warm-up (bars before the window is filled) returns ``NA``; ``length=1``
    is a short-circuit that returns ``source`` unchanged.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(source: series<float>, length: simple<int>, offset: simple<int>)
    -> series<float>``.
    """
    return _pyne_ta.linreg(source, length, offset)


def median(source, length: int):
    """Pine ``ta.median(source, length)`` — rolling median.

    Delegates to :func:`pynecore.lib.ta.median`. Returns the median of the
    last ``length`` values of ``source``. PyneCore uses a two-heap
    (max-heap of low half, min-heap of high half) rolling-median which is
    O(log length) per bar. Warm-up bars (first ``length-1``) return
    ``NA``; ``length == 1`` is a short-circuit that returns ``source``
    unchanged.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(source: series<float>, length: simple<int>) -> series<float>``.
    """
    return _pyne_ta.median(source, length)


def percentile_linear_interpolation(source, length: int, percentage):
    """Pine ``ta.percentile_linear_interpolation(source, length, percentage)``
    — percentile with linear interpolation.

    Delegates to :func:`pynecore.lib.ta.percentile_linear_interpolation`.
    numpy-style ``linear`` interpolation percentile of the last ``length``
    values of ``source``. ``percentage`` is on the ``0..100`` scale (Pine's
    convention — NOT the ``0..1`` scale numpy accepts).

    Naming deviation flagged: PyneCore names the third arg ``percentage``
    (not ``percentile``). The prompt referred to it as ``percentile``; we
    follow PyneCore's actual name so keyword-form calls resolve correctly
    through the bridge.

    Warm-up (first ``length-1`` bars) returns ``NA``.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(source: series<float>, length: simple<int>,
    percentage: simple<float>) -> series<float>``.
    """
    return _pyne_ta.percentile_linear_interpolation(source, length, percentage)


def cum(source):
    """Pine ``ta.cum(source)`` — cumulative sum since series start.

    Delegates to :func:`pynecore.lib.ta.cum`. Running total of ``source``
    from the first bar onward — no ``length`` argument. NA-safe: if
    ``source`` is ``NA`` on a given bar the return is ``NA`` for that bar;
    PyneCore keeps the persistent accumulator un-mutated across NA bars so
    the running total resumes cleanly on the next non-NA bar.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is ``(source: series<float>) -> series<float>``.
    """
    return _pyne_ta.cum(source)


def barssince(condition):
    """Pine ``ta.barssince(condition)`` — bars since condition was last true.

    Delegates to :func:`pynecore.lib.ta.barssince`. Counts bars since
    ``condition`` was last true: ``0`` on the bar where ``condition`` is
    true, then ``1``, ``2``, ``3``, ... on subsequent bars. Returns
    ``NA(int)`` until ``condition`` has been true at least once
    (PyneCore stores the persistent counter as ``-1`` sentinel for the
    "never-fired" state and returns ``NA(int)`` explicitly on that path).

    PyneCore parameter name is ``condition``; the bridge preserves it so
    keyword-form calls resolve.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is ``(condition: series<bool>) -> series<int>``.
    """
    return _pyne_ta.barssince(condition)


__all__ += [
    "crossover",
    "crossunder",
    "highest",
    "lowest",
    "change",
    "mom",
    "roc",
    "linreg",
    "median",
    "percentile_linear_interpolation",
    "cum",
    "barssince",
]


# ==============================================================================
# ---- Wave 5B-3: bands + volatility + volume ----
# Owns: ta.bb, ta.atr, ta.tr, ta.stdev, ta.obv, ta.vwap, ta.sar
# ==============================================================================


def bb(source, length: int, mult):
    """Pine ``ta.bb(source, length, mult)`` — Bollinger Bands triple.

    Delegates to :func:`pynecore.lib.ta.bb`. Returns a 3-tuple
    ``(basis, upper, lower)`` where:

    * ``basis = ta.sma(source, length)``
    * ``upper = basis + mult * ta.stdev(source, length)``
    * ``lower = basis - mult * ta.stdev(source, length)``

    ``mult`` is a float multiplier — PyneCore accepts ``float | int`` and
    the assert-guard ``mult > 0`` is enforced at runtime by PyneCore itself.
    Warm-up (first ``length-1`` bars) returns ``(NA, NA, NA)`` for all
    three components since both ``sma`` and ``stdev`` need a full window.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(src: series<float>, length: simple<int>, mult: simple<float>) ->
    tuple[series<float>, series<float>, series<float>]``. The C3 registry
    names the first arg ``src`` (Pine's short form) where PyneCore names it
    ``source`` — positional dispatch keeps them interoperable, matching the
    same convention as Wave 5B-2's ``rsi``/``stoch``/``cci``.
    """
    return _pyne_ta.bb(source, length, mult)


def atr(length: int):
    """Pine ``ta.atr(length)`` — Wilder's Average True Range.

    Delegates to :func:`pynecore.lib.ta.atr`. Signature deviation from the
    rest of the ``ta.*`` moving-average family: ``atr`` takes NO ``source``
    parameter — it computes ``rma(tr(handle_na=True), length)`` internally,
    reading ``high``/``low``/``close`` directly from the OHLCV stream.

    PyneCore calls ``tr(handle_na=True)``, which makes the first bar's TR
    equal to ``high - low`` (rather than NA), so the Wilder RMA seed forms
    at bar ``length - 1``. Warm-up: NA for the first ``length - 1`` bars.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is ``(length: simple<int>) -> series<float>``.
    """
    return _pyne_ta.atr(length)


def tr(handle_na: bool = False):
    """Pine ``ta.tr(handle_na=false)`` — True Range.

    Delegates to :func:`pynecore.lib.ta.tr`. The standard TR formula is
    ``max(high - low, |high - close[1]|, |low - close[1]|)``. On the first
    bar there is no ``close[1]``:

    * ``handle_na=False`` (Pine default): emit NA.
    * ``handle_na=True``: emit ``high - low`` for the first bar. This is
      the mode ``ta.atr`` uses internally so its RMA seed starts on bar
      ``length-1`` rather than ``length``.

    PyneCore models ``tr`` as a ``@module_property`` — both ``ta.tr``
    (bare identifier) and ``ta.tr(handle_na)`` (call form) resolve to the
    same underlying function. The bridge exposes the callable form; the
    bare-identifier form compiles through codegen's zero-arg call
    insertion (Phase-2 concern), not through the bridge shape.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is ``(handle_na: simple<bool>) -> series<float>``.
    """
    return _pyne_ta.tr(handle_na)


def stdev(source, length: int, biased: bool = True):
    """Pine ``ta.stdev(source, length, biased=true)`` — rolling standard deviation.

    Delegates to :func:`pynecore.lib.ta.stdev`. Default ``biased=True``
    matches PyneCore's default and Pine's documented behaviour: variance
    is normalised by ``n`` (population) rather than ``n - 1`` (sample).
    Callers who need the sample form pass ``biased=False``.

    Warm-up: the first ``length - 1`` bars are NA (variance needs a full
    window). PyneCore's implementation uses a Welford online recurrence
    with Kahan compensation and a Pébay decremental step for the sliding
    window, so long series don't accumulate ULP-level drift.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(src: series<float>, length: simple<int>, biased: simple<bool>) ->
    series<float>``. The C3 registry names the first arg ``src`` (Pine's
    short form) where PyneCore names it ``source`` — positional dispatch
    keeps them interoperable.
    """
    return _pyne_ta.stdev(source, length, biased)


def obv():
    """Pine ``ta.obv`` — On-Balance Volume.

    Delegates to :func:`pynecore.lib.ta.obv`. PyneCore models ``obv`` as
    a zero-arg ``@module_property``, so a Pine script uses it as a bare
    identifier (``plot(ta.obv)``). The bridge exposes an explicit callable
    form for uniform codegen dispatch — a bare-identifier reference at
    the Pine call site compiles to the parenthesised call here.

    OBV = ``cum(volume * sign(ta.change(close)))``. Bar 0 is NA because
    ``ta.change(close)`` is NA on the first bar (no previous close to
    compare against). From bar 1 onward the running sum accumulates.
    Requires ``volume`` on the OHLCV stream — the executor's
    ``BYODataProvider`` validation catches missing-volume up front.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is ``() -> series<float>``. Wave 5B-3 ADDS the ``ta.obv``
    registry entry — it is NOT one of the 29 PRD §3.2 Phase-1 ta.*
    builtins.
    """
    return _pyne_ta.obv()


def vwap(source, anchor=None, stdev_mult=None):
    """Pine ``ta.vwap(source, anchor=na, stdev_mult=na)`` — Volume-Weighted Average Price.

    Delegates to :func:`pynecore.lib.ta.vwap`. Cumulative
    ``sum(source * volume) / sum(volume)`` bounded to a session anchor:

    * ``anchor=None`` (default): PyneCore falls back to
      ``session.isfirstbar`` — the vwap resets on the first bar of each
      trading session. In synthetic single-session data the flag can fire
      every bar, producing the trivial ``vwap == source``; the conformance
      fixture passes an explicit ``bar_index == 0`` anchor to exercise the
      cumulative path.
    * ``anchor=<bool>``: caller-supplied reset trigger. Wherever the value
      is truthy, cumulative sums restart at the current bar.
    * ``stdev_mult=None`` (default): scalar ``vwap`` value.
    * ``stdev_mult=<float>``: returns a 3-tuple ``(vwap, upper, lower)``
      where the bands widen by ``stdev_mult * std``. The bridge forwards
      the argument unchanged; the C3 stub declares the scalar return path
      because the vast majority of Pine scripts don't use the bands form.
      A future stub lift can add the tuple return; no bridge change needed.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(source: series<float>, anchor: simple<bool>, stdev_mult: simple<float>)
    -> series<float>``. Wave 5B-3 ADDS the ``ta.vwap`` registry entry —
    it is NOT one of the 29 PRD §3.2 Phase-1 ta.* builtins.
    """
    return _pyne_ta.vwap(source, anchor, stdev_mult)


def sar(start: float = 0.02, inc: float = 0.02, max: float = 0.2):  # noqa: A002 (Pine name)
    """Pine ``ta.sar(start=0.02, inc=0.02, max=0.2)`` — Parabolic SAR.

    Delegates to :func:`pynecore.lib.ta.sar`. Wilder's Stop-and-Reverse
    indicator; takes NO ``source`` argument — it reads ``high``/``low``
    directly from the OHLCV stream to detect trend reversals.

    The parameter named ``max`` shadows Python's builtin ``max``.
    PyneCore's public signature intentionally uses this name to match
    Pine's reference; the bridge preserves it so keyword-form calls
    resolve unchanged. A ``# noqa: A002`` annotation suppresses the
    linter warning at the signature declaration.

    PyneCore's implementation is a faithful Wilder step:

    * Bar 0: NA.
    * Bar 1: seed direction — ``high[1] > high`` (i.e. previous bar's
      high > current bar's high) starts a short trend, else long.
    * Bar 2+: standard Wilder step with reversal on ``low <= sar``
      (long) or ``high >= sar`` (short). Reversals restart ``af`` at
      ``start``; each new extreme point bumps ``af`` by ``inc`` up to
      ``max``.

    Per :mod:`openbb_pine.compiler.builtin_signatures` the compile-time
    signature is
    ``(start: simple<float>, inc: simple<float>, max: simple<float>)
    -> series<float>``. Wave 5B-3 ADDS the ``ta.sar`` registry entry —
    it is NOT one of the 29 PRD §3.2 Phase-1 ta.* builtins.
    """
    return _pyne_ta.sar(start, inc, max)


__all__ += ["bb", "atr", "tr", "stdev", "obv", "vwap", "sar"]
