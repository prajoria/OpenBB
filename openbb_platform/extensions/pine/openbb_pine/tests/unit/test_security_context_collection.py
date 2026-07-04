"""C3 populates ``CompiledModule.security_contexts`` on ``request.security``.

Bead: ``0e9.6.y86`` (part of the Phase-2 M2 rollup ``0e9.6``).
Design source of truth: D5 §4.1 (SecurityContext), §4.4 (fully-dynamic
symbol/timeframe), §7.2 (compiler signature).

What C3 now does when it walks a ``request.security(sym, tf, expr, gaps=?,
lookahead=?)`` call site (`type_checker._visit_request_security`):

1. Assigns a stable ``ctx_N`` id in source order — deterministic across
   recompiles so the C6 cache key stays stable.
2. Builds a :class:`SecurityContext(symbol=..., timeframe=..., expr=...,
   dynamic_symbol=?, dynamic_timeframe=?)` per call site.
3. ``dynamic_symbol=True`` when the symbol arg is not a bare string
   literal (e.g. ``syminfo.ticker`` — Pine's canonical dynamic form).
   Same rule for ``dynamic_timeframe``.
4. Threads the map onto :attr:`CompiledModule.security_contexts` via
   :class:`TypeCheckResult`.
5. Type-checks ``gaps`` / ``lookahead`` kwargs against ``const<bool>``
   (D5 §7.2 keyword-only slot; validated via the new ``Signature.kwargs``
   field).
6. Rejects a non-string ``symbol`` / ``timeframe`` with ``PT001`` — Pine
   requires string args (or a series-of-string for dynamic form).

Tests use :func:`compile_pine(src, use_cache=False)` end-to-end so the
whole pipeline (lexer → parser → C3) exercises the change. ``use_cache``
is disabled because the C6 cache serializer at
``openbb_pine.compiler.compile_cache._write`` currently hard-codes the
three original ``SecurityContext`` fields — round-trip through the cache
would silently coerce ``dynamic_*`` back to ``False``. Follow-up bead
should extend the serializer once codegen (bead ``0e9.6.god``) wires
``__security_contexts__`` into the emitted @pyne module.
"""

from __future__ import annotations

import pytest

from openbb_pine.compiler import compile_pine
from openbb_pine.compiler.types import CompiledModule, SecurityContext
from openbb_pine.errors import PineTypeError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compile(body: str) -> CompiledModule:
    """Wrap a Pine body in a minimal v6 indicator scaffold and compile.

    ``use_cache=False`` so we don't round-trip through the compile-cache
    serializer, which pre-dates the ``dynamic_symbol`` / ``dynamic_timeframe``
    fields (see module docstring — a future bead extends the serializer).
    """
    src = f'//@version=6\nindicator("X")\n{body}'
    return compile_pine(src, use_cache=False)


# ---------------------------------------------------------------------------
# Empty case — no request.security calls
# ---------------------------------------------------------------------------


class TestEmptySecurityContexts:
    """A script with no ``request.security`` calls carries ``None`` on
    :attr:`CompiledModule.security_contexts` (Phase-1 shape preserved)."""

    def test_bare_indicator_has_none(self) -> None:
        compiled = _compile("plot(close)\n")
        assert compiled.security_contexts is None

    def test_indicator_with_ta_call_has_none(self) -> None:
        # ta.sma is a builtin, but doesn't touch request.security.
        compiled = _compile("plot(ta.sma(close, 20))\n")
        assert compiled.security_contexts is None


# ---------------------------------------------------------------------------
# Single request.security call — static form
# ---------------------------------------------------------------------------


class TestOneStaticSecurityContext:
    """``request.security("SPY", "1D", close)`` — the D5 §4.1 canonical case:
    both symbol and timeframe are bare string literals so C3 statically
    resolves them; both ``dynamic_*`` flags are False."""

    def test_ctx_0_registered(self) -> None:
        compiled = _compile('spy = request.security("SPY", "1D", close)\nplot(spy)\n')
        assert compiled.security_contexts is not None
        assert list(compiled.security_contexts) == ["ctx_0"]

    def test_symbol_and_timeframe_captured(self) -> None:
        compiled = _compile('spy = request.security("SPY", "1D", close)\nplot(spy)\n')
        ctx = compiled.security_contexts["ctx_0"]
        assert ctx.symbol == "SPY"
        assert ctx.timeframe == "1D"

    def test_static_flags_are_false(self) -> None:
        compiled = _compile('spy = request.security("SPY", "1D", close)\nplot(spy)\n')
        ctx = compiled.security_contexts["ctx_0"]
        assert ctx.dynamic_symbol is False
        assert ctx.dynamic_timeframe is False

    def test_expr_is_serialised_placeholder(self) -> None:
        """``expr`` field carries an opaque string per D5 §4.1 — D2 reads it
        opaquely, so C3's ``str(node)`` placeholder is a valid contract."""
        compiled = _compile('spy = request.security("SPY", "1D", close)\nplot(spy)\n')
        expr = compiled.security_contexts["ctx_0"].expr
        # The placeholder must be a non-empty string. Since our lowered
        # expression here is a bare ``close`` name, the ``str(Name(...))``
        # form must contain the identifier.
        assert isinstance(expr, str) and expr
        assert "close" in expr

    def test_builtins_used_records_request_security(self) -> None:
        """The wild-corpus coverage metric (PRD §3.4 L0.5) reads
        :attr:`CompiledModule.builtins_used` — C3 must add
        ``request.security`` there even on the happy path."""
        compiled = _compile('spy = request.security("SPY", "1D", close)\nplot(spy)\n')
        assert "request.security" in compiled.builtins_used


# ---------------------------------------------------------------------------
# Two independent request.security calls
# ---------------------------------------------------------------------------


class TestTwoIndependentSecurityContexts:
    """C3 must produce distinct ``ctx_N`` ids for two independent call
    sites — the counter is per-checker, incrementing in source order — and
    the id assignment must be deterministic across recompiles so the C6
    cache key stays stable."""

    _SRC = (
        'spy = request.security("SPY", "1D", close)\n'
        'qqq = request.security("QQQ", "60", close)\n'
        'plot(spy)\n'
        'plot(qqq)\n'
    )

    def test_two_ids_registered(self) -> None:
        compiled = _compile(self._SRC)
        assert set(compiled.security_contexts) == {"ctx_0", "ctx_1"}

    def test_ids_assigned_in_source_order(self) -> None:
        compiled = _compile(self._SRC)
        assert compiled.security_contexts["ctx_0"].symbol == "SPY"
        assert compiled.security_contexts["ctx_1"].symbol == "QQQ"

    def test_id_assignment_is_deterministic_across_recompiles(self) -> None:
        """Recompiling the SAME source must produce identical
        ``ctx_N`` → SecurityContext mappings — otherwise cache keys drift
        between compiles even though the source is stable."""
        first = _compile(self._SRC).security_contexts
        second = _compile(self._SRC).security_contexts
        assert first == second


# ---------------------------------------------------------------------------
# D5 §4.4 — fully-dynamic symbol
# ---------------------------------------------------------------------------


class TestDynamicSymbol:
    """When symbol is ``syminfo.ticker`` (or any non-literal expression),
    C3 sets ``dynamic_symbol=True`` — the runtime dispatcher falls back to
    lazy per-bar fetch (D5 §4.4 documented 5-10× perf caveat)."""

    def test_syminfo_ticker_flags_dynamic_symbol(self) -> None:
        compiled = _compile(
            'spy = request.security(syminfo.ticker, "1D", close)\nplot(spy)\n'
        )
        ctx = compiled.security_contexts["ctx_0"]
        assert ctx.dynamic_symbol is True
        assert ctx.dynamic_timeframe is False

    def test_dynamic_symbol_records_unsupported_builtin(self) -> None:
        """Even though we swallow the ``PineUnsupportedBuiltinError`` raised
        by walking ``syminfo.ticker`` (so the SecurityContext still lands),
        the name is recorded in :attr:`builtins_used` for coverage
        attribution."""
        compiled = _compile(
            'spy = request.security(syminfo.ticker, "1D", close)\nplot(spy)\n'
        )
        assert "syminfo.ticker" in compiled.builtins_used
        assert "request.security" in compiled.builtins_used


# ---------------------------------------------------------------------------
# D5 §4.4 — fully-dynamic timeframe
# ---------------------------------------------------------------------------


class TestDynamicTimeframe:
    """When timeframe is a series/input-derived string (not a literal), C3
    sets ``dynamic_timeframe=True``. Same runtime consequence as
    ``dynamic_symbol`` — per D5 §4.4."""

    _SRC = (
        'tf = input.string("1D")\n'
        'spy = request.security("SPY", tf, close)\n'
        'plot(spy)\n'
    )

    def test_input_string_timeframe_flags_dynamic_timeframe(self) -> None:
        compiled = _compile(self._SRC)
        ctx = compiled.security_contexts["ctx_0"]
        assert ctx.dynamic_symbol is False
        assert ctx.dynamic_timeframe is True

    def test_static_symbol_still_captured_verbatim(self) -> None:
        compiled = _compile(self._SRC)
        # Dynamic timeframe doesn't taint the static symbol — SPY is still
        # a bare literal, so C3 records the literal value.
        assert compiled.security_contexts["ctx_0"].symbol == "SPY"


# ---------------------------------------------------------------------------
# D5 §7.2 keyword-only args: gaps / lookahead
# ---------------------------------------------------------------------------


class TestGapsAndLookaheadKwargs:
    """``gaps`` and ``lookahead`` are Signature.kwargs entries (D5 §7.2
    keyword-only slot). C3 must accept bool consts."""

    def test_bool_kwargs_accepted(self) -> None:
        compiled = _compile(
            'spy = request.security("SPY", "1D", close, gaps=true, lookahead=false)\n'
            'plot(spy)\n'
        )
        assert compiled.security_contexts is not None
        assert "ctx_0" in compiled.security_contexts

    def test_gaps_only_kwarg_accepted(self) -> None:
        compiled = _compile(
            'spy = request.security("SPY", "1D", close, gaps=true)\nplot(spy)\n'
        )
        assert compiled.security_contexts is not None

    def test_lookahead_only_kwarg_accepted(self) -> None:
        compiled = _compile(
            'spy = request.security("SPY", "1D", close, lookahead=false)\nplot(spy)\n'
        )
        assert compiled.security_contexts is not None


# ---------------------------------------------------------------------------
# Type rejection — non-string symbol
# ---------------------------------------------------------------------------


class TestRejectsNonStringSymbol:
    """PT001 fires when ``symbol`` isn't a string.

    ``request.security(123, "1D", close)`` — Pine rejects an int-typed
    symbol per D5 §7.2. Our compiler surfaces this via the PT001 rule
    inside :meth:`_TypeChecker._resolve_security_string_arg` (the strict
    inner-type check that runs after the walk succeeds)."""

    def test_int_symbol_raises_pt001(self) -> None:
        with pytest.raises(PineTypeError) as excinfo:
            _compile('spy = request.security(123, "1D", close)\nplot(spy)\n')
        assert excinfo.value.rule == "PT001"


# ---------------------------------------------------------------------------
# Threading — CompiledModule carries the same dict TypeCheckResult built
# ---------------------------------------------------------------------------


class TestSecurityContextThreading:
    """The C3 → codegen (emit) → CompiledModule pipeline must thread the
    security_contexts dict unchanged. This test guards against a silent
    drop somewhere in the compile facade."""

    def test_compiled_module_carries_security_contexts(self) -> None:
        compiled = _compile('spy = request.security("SPY", "1D", close)\nplot(spy)\n')
        # The dict is populated per C3, then echoed through emit() into
        # CompiledModule.security_contexts. Verify the shape survives.
        assert isinstance(compiled.security_contexts, dict)
        assert isinstance(compiled.security_contexts["ctx_0"], SecurityContext)

    def test_none_when_no_request_security(self) -> None:
        # Guards against accidental empty-dict-vs-None drift — TypeCheckResult
        # normalises {} to None so downstream consumers don't have to.
        compiled = _compile("plot(close)\n")
        assert compiled.security_contexts is None
