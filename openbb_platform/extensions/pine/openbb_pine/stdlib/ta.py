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
