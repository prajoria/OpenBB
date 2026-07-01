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
