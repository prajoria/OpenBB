"""D5 §5.3 — ``_install_secondaries_hook`` monkey-patch context manager.

Wraps ``ScriptRunner.run_iter()`` so PyneCore's ``request.security()`` reads
from the DataFrames :func:`openbb_pine.runtime.security_dispatcher.
prefetch_security_contexts` already produced, rather than trying to resolve
the request itself (which would either fail — the vendored PyneCore's
``request.security`` deliberately raises ``RuntimeError`` because it expects
its own SecurityTransformer AST rewrite to have handled the call — or, in
future when we integrate PyneCore's transformer, spin up its heavyweight
multi-process security machinery for what we've already prefetched).

The hook is a **single-call substitute**: when the compiled script calls
``pynecore.lib.request.security(symbol, timeframe, expression)`` at bar
``N``, we:

1. Look up ``(symbol, timeframe)`` in ``security_contexts`` to find the
   matching ``context_id`` (C3 populated the map at compile time). Static
   lookup — a miss raises :class:`PineSecurityContextNotFoundError` so the
   operator sees the mismatch immediately rather than a silent nan.
2. Fetch ``secondaries[context_id]`` — a ``pd.DataFrame`` already
   forward-filled to the primary bar grid by the c1x dispatcher (D5 §4.2
   step 4). We index it via ``iloc[current_bar_index]``.
3. Coerce ``expression`` (which for M2 is one of PyneCore's ``Source``
   sentinels — ``close`` / ``volume`` / ``high`` / … — see
   ``pynecore.types.source.Source``) into a column name and return the
   scalar value.

For M2 we support only static symbol + static timeframe contexts. Dynamic
contexts (``dynamic_symbol`` / ``dynamic_timeframe`` per D5 §4.4) raise
:class:`PineSecurityContextNotFoundError(reason="dynamic_unsupported")`
so the failure mode is loud and documented.

Design decisions locked in per D5 §5.3
--------------------------------------

* **Manual save/restore** rather than ``unittest.mock.patch.object`` — the
  runtime isn't a test surface and pulling ``unittest`` into the runtime
  import graph is unnecessary weight. The ``try/finally`` shape is one
  screen and matches the ``capture_alerts`` precedent in ``_pynecore_glue``.
* **Callable bar-index accessor** rather than a snapshot int. The executor
  advances PyneCore's ``lib.bar_index`` state per yield; passing a
  ``Callable[[], int]`` lets the hook read the current bar on every call
  without the executor having to reach into our internals mid-loop
  (mirrors how ``capture_alerts`` accepts ``bar_index_getter`` /
  ``timestamp_getter``).
* **Nested install is safe** — we save the current ``pynecore.lib.request.
  security`` (which may itself already be a wrapper from an outer install)
  and restore it on exit. LIFO unwinding falls out naturally.
* Only ``pynecore.lib.request.security`` is patched. ``request.
  security_lower_tf`` (LTF intrabar reads) is out of scope for M2 —
  requesting it raises ``RuntimeError`` from PyneCore's own stub, which we
  don't intercept.

Clean-room: I have not viewed TradingView or PyneComp source code.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Callable, Iterator

import pandas as pd

from openbb_pine.errors import PineSecurityContextNotFoundError

if TYPE_CHECKING:  # pragma: no cover -- typing-only
    from openbb_pine.compiler.types import SecurityContext


__all__ = [
    "install_secondaries_hook",
    "expression_column_name",
]


_log = logging.getLogger(__name__)


# --- Expression -> column-name helper ---------------------------------------


def expression_column_name(expression: Any) -> str:
    """Return the DataFrame column name for a PyneCore ``expression`` arg.

    PyneCore's ``request.security(symbol, timeframe, expression)`` accepts
    the built-in ``Source`` sentinels ``close`` / ``volume`` / ``open`` /
    ``high`` / ``low`` / ``hl2`` / ``hlc3`` / ``ohlc4`` (see
    ``pynecore.types.source.Source``). Those objects render their name via
    ``__str__`` — we prefer :attr:`Source.name` when available so we don't
    depend on the ``__str__`` shape.

    Plain strings (``"close"``, ``"volume"``) pass through unchanged so
    tests that don't want to import PyneCore's ``Source`` type can drive
    the hook directly.

    Anything else (arbitrary expressions like ``close + open``) falls
    outside M2 scope — the c1x dispatcher already forward-fills whole
    OHLCV frames, so only the sentinel columns are addressable here.
    Callers that hand us something exotic get a ``TypeError`` with the
    offending value in the message rather than an ``AttributeError`` deep
    in the hook.
    """
    # 1) Source-typed sentinel (PyneCore's IDE-support marker).
    name = getattr(expression, "name", None)
    if isinstance(name, str) and name:
        return name
    # 2) Plain string — pass through.
    if isinstance(expression, str):
        return expression
    # 3) Anything else: refuse with a message that names the offender.
    raise TypeError(
        f"request.security(): unsupported expression type "
        f"{type(expression).__name__!r} (value={expression!r}); M2 hook "
        "supports built-in Source sentinels (close, volume, high, low, "
        "open, hl2, hlc3, ohlc4) and plain column-name strings."
    )


# --- Context resolution ------------------------------------------------------


def _context_is_dynamic(ctx: "SecurityContext") -> bool:
    """Mirror ``security_dispatcher._context_is_dynamic`` — but resolved
    at the hook boundary so a dynamic context surfaces as a runtime error
    instead of silently returning empty (the dispatcher path).

    Uses ``getattr`` fallbacks so this file stays compatible with the
    Wave-1 ``SecurityContext`` shape (bead d75) and the Wave-2 shape (bead
    y86) that adds ``dynamic_symbol`` / ``dynamic_timeframe`` fields —
    Wave-2 subagents develop concurrently, so we can't assume the fields
    exist yet.
    """
    return bool(
        getattr(ctx, "dynamic_symbol", False)
        or getattr(ctx, "dynamic_timeframe", False)
    )


def _lookup_context_id(
    symbol: str,
    timeframe: str,
    security_contexts: dict[str, "SecurityContext"],
) -> str:
    """Resolve ``(symbol, timeframe)`` → ``context_id``.

    Raises :class:`PineSecurityContextNotFoundError` with the full list of
    known ``(symbol, timeframe)`` pairs so a mismatch (e.g. ``"1D"`` vs
    ``"1d"``) is visible in one error message rather than a silent NaN.
    """
    for cid, ctx in security_contexts.items():
        if ctx.symbol == symbol and ctx.timeframe == timeframe:
            return cid
    # Miss — build a "did-you-mean"-style list for the operator.
    available = [
        f"{cid}: {ctx.symbol!r}@{ctx.timeframe!r}"
        for cid, ctx in security_contexts.items()
    ]
    raise PineSecurityContextNotFoundError(
        symbol=symbol,
        timeframe=timeframe,
        reason="not_found",
        available_keys=available,
    )


# --- The hook ---------------------------------------------------------------


@contextmanager
def install_secondaries_hook(
    secondaries: dict[str, pd.DataFrame],
    security_contexts: dict[str, "SecurityContext"],
    *,
    get_current_bar_index: Callable[[], int],
) -> Iterator[None]:
    """Monkey-patch ``pynecore.lib.request.security`` for one executor pass.

    Parameters
    ----------
    secondaries
        The ``{context_id: DataFrame}`` map that
        :func:`openbb_pine.runtime.security_dispatcher.prefetch_security_contexts`
        produced. Each DataFrame is already forward-filled to the primary
        bar index (D5 §4.2 step 4); we index it with ``iloc``.
    security_contexts
        The compiler-populated ``{context_id: SecurityContext}`` map from
        :attr:`openbb_pine.compiler.types.CompiledModule.security_contexts`.
        We iterate it once per hook call to resolve ``(symbol, timeframe)``
        → ``context_id``; the map is expected to be tiny (a handful of
        contexts) so no lookup dict is warranted.
    get_current_bar_index
        Callable returning the current primary-series bar index, called
        once per ``request.security()`` invocation. The executor threads
        this from ``pynecore.lib.bar_index`` (already stateful — see
        ``executor.run_compiled``'s ``_bar_index_now`` helper for the
        precedent alongside ``capture_alerts``).

    Yields
    ------
    None
        Enter the ``with`` block; ``pynecore.lib.request.security`` is
        patched for the block's lifetime and restored on exit
        (``try/finally`` — restoration runs even if the compiled script
        raises).

    Behaviour of the patched function
    --------------------------------

    Signature matches PyneCore's ``request.security(symbol, timeframe,
    expression, **kwargs)`` — extra kwargs (``gaps``, ``lookahead``,
    ``ignore_invalid_symbol``, …) are accepted for future compatibility
    but ignored in M2 (they were already applied by the c1x dispatcher's
    forward-fill and would need per-bar handling that D5 defers to M3+).

    Return type mirrors what the field-name column contains at
    ``iloc[current_bar_index]`` — typically a ``float`` for ``close`` /
    ``volume``. Tuple-valued ``expression=[close, volume]`` is out of
    M2 scope (see :func:`expression_column_name`); the compiler's
    codegen for tuple returns is a separate bead.

    Raises
    ------
    PineSecurityContextNotFoundError
        When ``(symbol, timeframe)`` doesn't match any known context, or
        matches one whose ``dynamic_symbol`` / ``dynamic_timeframe``
        flag is set (M2 static-only). The error carries
        ``available_keys`` so the operator can spot the mismatch.
    IndexError
        When ``get_current_bar_index()`` returns a bar past the end of
        the aligned secondary frame. Propagates unchanged — this is a
        wire-up bug (the dispatcher should have aligned the frame to
        the primary; if it didn't, we want the stack trace, not a
        silent NaN).
    """
    # Local import to keep the pynecore sys.path bridge ordering intact —
    # the runtime layer imports pynecore lazily so unit tests that don't
    # touch runtime code don't pay the import cost. Matches the pattern
    # already established in ``_pynecore_glue.capture_alerts`` (see line
    # 176 of that file).
    from pynecore.lib import request as request_module  # noqa: PLC0415

    original = request_module.security

    def _hook_security(
        symbol: Any,
        timeframe: Any,
        expression: Any,
        *_args: Any,
        **_kwargs: Any,
    ) -> Any:
        """Bar-time lookup that replaces PyneCore's stub.

        We coerce ``symbol`` / ``timeframe`` to ``str`` explicitly so the
        hook doesn't refuse a caller that hands us ``syminfo.ticker`` (a
        Source-like object whose ``__str__`` gives the underlying string)
        even after C3 has statically resolved it. If C3 couldn't resolve
        statically we're already in the dynamic-context branch, which
        raises via ``_context_is_dynamic``.
        """
        sym_s = str(symbol)
        tf_s = str(timeframe)

        # Resolve (symbol, timeframe) → context_id. Missing → raise with
        # the full context list attached.
        context_id = _lookup_context_id(sym_s, tf_s, security_contexts)

        # M2 only supports static contexts. If the matched context is
        # dynamic, surface a documented, actionable error rather than
        # silently taking the slow path we haven't built yet.
        ctx = security_contexts[context_id]
        if _context_is_dynamic(ctx):
            raise PineSecurityContextNotFoundError(
                symbol=sym_s,
                timeframe=tf_s,
                reason="dynamic_unsupported",
                context_id=context_id,
            )

        # Look up the pre-aligned secondary frame. Missing context_id in
        # ``secondaries`` while present in ``security_contexts`` means
        # the dispatcher never ran (wire-up bug) — raise the same class
        # so the surface stays uniform. This is defensive; production
        # code paths always populate both maps together.
        if context_id not in secondaries:
            raise PineSecurityContextNotFoundError(
                symbol=sym_s,
                timeframe=tf_s,
                reason="not_found",
                context_id=context_id,
                available_keys=list(secondaries.keys()),
                message=(
                    f"context_id {context_id!r} resolved from "
                    f"({sym_s!r}, {tf_s!r}) has no prefetched frame "
                    "(dispatcher may not have run)"
                ),
            )

        df = secondaries[context_id]
        column = expression_column_name(expression)

        # Bar-index read. iloc[N] raises IndexError for N past the end —
        # we let it propagate: that's a wire-up bug in the dispatcher's
        # forward-fill, and we want the stack rather than a silent NaN.
        bar_index = get_current_bar_index()
        row = df.iloc[bar_index]

        # Prefer .get() so a missing column raises KeyError with the
        # column name — friendlier than a bare NaN.
        if column not in row.index:
            raise KeyError(
                f"request.security(): column {column!r} not present in "
                f"prefetched frame for context {context_id!r} "
                f"(available columns: {list(row.index)})"
            )
        return row[column]

    request_module.security = _hook_security  # type: ignore[assignment]
    try:
        yield
    finally:
        # Restore. Runs even if the compiled script raises inside the
        # ``with`` block, so a script crash never leaves the runtime
        # module in a patched state that would corrupt the next call.
        request_module.security = original  # type: ignore[assignment]
