"""E0.4 gate: compiler does not import ``openbb_pine.telemetry`` at any
runtime callsite; instead, ``compile_pine(telemetry=...)`` accepts a
``TelemetrySink`` instance and threads it through the pipeline.

Post-E2 the ``TelemetrySink`` Protocol migrates to
``pyne_compiler.telemetry`` and the compiler will import it from there
under ``TYPE_CHECKING``. Until then it lives in ``openbb_pine.telemetry``
alongside the ``OpenBBTelemetrySink`` implementation openbb-fork routers
instantiate.

These tests enforce three contracts:

1. **No runtime coupling.** The compiler modules (codegen, type_checker,
   v5_migration, __init__) contain zero ``from openbb_pine.telemetry
   import`` lines outside a ``TYPE_CHECKING`` guard. This is the
   grep-gated check E0.7 will run against the shipped tree.
2. **Sink shape.** ``OpenBBTelemetrySink`` implements the two
   ``record_*`` methods the ``TelemetrySink`` Protocol demands, and the
   Protocol itself is exposed for downstream consumers.
3. **End-to-end injection.** ``compile_pine(telemetry=sink)`` propagates
   the sink through every telemetry-emitting sub-stage (detect, migrate,
   type-check, codegen) so unsupported-feature counts land on the
   injected sink rather than the module-global default. With
   ``telemetry=None`` (default) no sink is touched.
"""

from __future__ import annotations

import inspect

import pytest

from openbb_pine.errors import PineUnsupportedFeatureError


# ---------------------------------------------------------------------------
# Contract 1 — grep-gate: no runtime import of openbb_pine.telemetry
# ---------------------------------------------------------------------------


def test_compiler_modules_do_not_import_openbb_pine_telemetry_at_runtime() -> None:
    """Every telemetry reference in the compiler must be inside a
    ``TYPE_CHECKING`` block (or absent). A runtime ``from
    openbb_pine.telemetry import`` would re-couple the compiler to the
    openbb-fork's concrete module — the exact thing E0.4 exists to break.

    We use AST inspection rather than a bare substring match so the
    ``TYPE_CHECKING``-gated forward-reference import for ``TelemetrySink``
    (the compiler's parameter type) is correctly ignored. E2 rewrites
    that gated import to ``from pyne_compiler.telemetry import
    TelemetrySink`` in a one-line change per module.
    """
    import ast
    import importlib

    modules = [
        importlib.import_module(name)
        for name in (
            "openbb_pine.compiler",
            "openbb_pine.compiler.codegen",
            "openbb_pine.compiler.type_checker",
            "openbb_pine.compiler.v5_migration",
        )
    ]

    for mod in modules:
        src = inspect.getsource(mod)
        tree = ast.parse(src)

        # Collect every node reachable at runtime — i.e. every AST node
        # NOT nested inside an ``if TYPE_CHECKING:`` body. The else-branch
        # of a TYPE_CHECKING guard stays runtime-reachable (there aren't
        # any in practice, but be safe).
        guarded: set[int] = set()
        for node in ast.walk(tree):
            if _is_type_checking_guard(node):
                assert isinstance(node, ast.If)
                for child in node.body:
                    for descendant in ast.walk(child):
                        guarded.add(id(descendant))

        runtime_imports: list[str] = []
        for node in ast.walk(tree):
            if id(node) in guarded:
                continue
            if isinstance(node, ast.ImportFrom) and node.module == (
                "openbb_pine.telemetry"
            ):
                runtime_imports.append(
                    f"line {node.lineno}: {ast.unparse(node)}"
                )
            elif isinstance(node, ast.ImportFrom) and node.module == "openbb_pine":
                # ``from openbb_pine import telemetry`` binds the telemetry
                # submodule as a runtime name — same coupling as
                # ``import openbb_pine.telemetry``. The plain
                # ``from openbb_pine.telemetry import X`` form is caught
                # by the branch above; this one catches the module-bind
                # variant that would otherwise slip past.
                for alias in node.names:
                    if alias.name == "telemetry":
                        runtime_imports.append(
                            f"line {node.lineno}: {ast.unparse(node)}"
                        )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "openbb_pine.telemetry":
                        runtime_imports.append(
                            f"line {node.lineno}: {ast.unparse(node)}"
                        )

        assert not runtime_imports, (
            f"{mod.__name__} imports openbb_pine.telemetry at RUNTIME — "
            f"E0.4 incomplete. Route the record_* call through the injected "
            f"TelemetrySink instead. Offending imports: {runtime_imports}"
        )


def _is_type_checking_guard(node: object) -> bool:
    """True when ``node`` is an ``if TYPE_CHECKING:`` If-statement.

    Matches both bare ``TYPE_CHECKING`` (imported directly) and
    ``typing.TYPE_CHECKING`` (attribute access on the ``typing`` module).
    """
    import ast as _ast

    if not isinstance(node, _ast.If):
        return False
    test = node.test
    if isinstance(test, _ast.Name) and test.id == "TYPE_CHECKING":
        return True
    if isinstance(test, _ast.Attribute) and test.attr == "TYPE_CHECKING":
        return True
    return False


# ---------------------------------------------------------------------------
# Contract 2 — TelemetrySink Protocol + OpenBBTelemetrySink impl
# ---------------------------------------------------------------------------


def test_telemetry_sink_protocol_exists() -> None:
    """The compiler programs against ``TelemetrySink``; the openbb-fork
    ships ``OpenBBTelemetrySink`` as the concrete implementation."""
    from openbb_pine.telemetry import OpenBBTelemetrySink, TelemetrySink

    sink = OpenBBTelemetrySink()
    # Protocol shape — both methods callable with a str.
    sink.record_unsupported_feature("test_feature")
    sink.record_unsupported_builtin("test_builtin")
    # Structural typing check (runtime_checkable Protocol).
    assert isinstance(sink, TelemetrySink)


def test_openbb_telemetry_sink_records_counts() -> None:
    """The concrete impl the routers instantiate keeps per-name counts
    on its own instance (not on module state) so multiple router calls
    do not cross-contaminate."""
    from openbb_pine.telemetry import OpenBBTelemetrySink

    sink = OpenBBTelemetrySink()
    sink.record_unsupported_feature("PF010")
    sink.record_unsupported_feature("PF010")
    sink.record_unsupported_builtin("ta.ichimoku")
    assert sink.get_unsupported_feature_counts() == {"PF010": 2}
    assert sink.get_unsupported_builtin_counts() == {"ta.ichimoku": 1}

    # Independent instances stay isolated.
    other = OpenBBTelemetrySink()
    assert other.get_unsupported_feature_counts() == {}


# ---------------------------------------------------------------------------
# Contract 3 — compile_pine threads the sink through every emitter
# ---------------------------------------------------------------------------


def test_compile_pine_accepts_telemetry_kwarg() -> None:
    """The facade signature accepts ``telemetry=sink`` without raising
    ``TypeError``. Actual recording is exercised below."""
    from openbb_pine.compiler import compile_pine
    from openbb_pine.telemetry import OpenBBTelemetrySink

    sink = OpenBBTelemetrySink()
    compile_pine(
        '//@version=6\nindicator("t")\nplot(close)\n',
        telemetry=sink,
        use_cache=False,
    )


def test_compile_pine_defaults_telemetry_to_none() -> None:
    """With ``telemetry=None`` (default), the pipeline runs end-to-end
    without touching any sink. Verifies the ``if telemetry is not None``
    guards actually short-circuit."""
    from openbb_pine.compiler import compile_pine

    result = compile_pine(
        '//@version=6\nindicator("t")\nplot(close)\n', use_cache=False
    )
    assert result is not None
    assert result.source  # emit produced something


def _dummy_span():
    """Zero-position :class:`ir.Span` for hand-constructed IR fixtures."""
    from openbb_pine.compiler import ir

    return ir.Span(
        file="<inline>",
        start_line=1,
        start_col=1,
        end_line=1,
        end_col=1,
        start_byte=0,
        end_byte=0,
    )


def test_injected_sink_receives_codegen_pf010_signal() -> None:
    """visit_Program's PF010 strategy-deferral raise MUST call
    ``sink.record_unsupported_feature('PF010')`` on the injected sink —
    not on the module-global default. This is the end-to-end proof the
    plumbing works."""
    from openbb_pine.compiler import ir
    from openbb_pine.compiler.codegen import _CodegenVisitor
    from openbb_pine.telemetry import OpenBBTelemetrySink

    sink = OpenBBTelemetrySink()
    span = _dummy_span()
    directive = ir.ScriptDirective(
        loc=span,
        kind="strategy",
        title="x",
        shorttitle=None,
        overlay=None,
        arguments=(),
    )
    prog = ir.Program(
        loc=span,
        version=6,
        directive=directive,
        declarations=(),
        body=(),
    )
    visitor = _CodegenVisitor(
        builtins_used=frozenset(), pine_version=6, telemetry=sink
    )
    with pytest.raises(PineUnsupportedFeatureError):
        visitor.visit_Program(prog)

    assert sink.get_unsupported_feature_counts().get("PF010") == 1


def test_injected_sink_receives_type_checker_signal() -> None:
    """_TypeChecker's ``_raise_unsupported_builtin`` MUST call
    ``sink.record_unsupported_builtin(name)`` on the injected sink."""
    from openbb_pine.compiler import ir
    from openbb_pine.compiler.type_checker import _TypeChecker
    from openbb_pine.errors import PineUnsupportedBuiltinError
    from openbb_pine.telemetry import OpenBBTelemetrySink

    sink = OpenBBTelemetrySink()
    tc = _TypeChecker(pine_version=6, telemetry=sink)
    node = ir.Name(id="dummy", loc=_dummy_span())

    with pytest.raises(PineUnsupportedBuiltinError):
        tc._raise_unsupported_builtin("ta.ichimoku", node=node)

    assert sink.get_unsupported_builtin_counts().get("ta.ichimoku") == 1


def test_injected_sink_receives_v5_migration_signal() -> None:
    """migrate_v5_to_v6's PF003 raise MUST call
    ``sink.record_unsupported_feature('PF003')`` on the injected sink.

    Uses an ``iff(a, b, foo(1, 2))`` fixture: the third arg contains a
    parenthesised nested call, so the ``[^,()]+?`` char class in
    V5_REWRITES cannot match past ``foo`` (the ``(`` is excluded from
    the class). The rewrite therefore cannot fire AT ALL — the literal
    ``iff(`` survives verbatim and the sentinel scan fires exactly once
    against exactly one residual ``iff(`` occurrence. Bounded-match, not
    coincidental: this pins the assertion to ``{"PF003": 1}`` even if
    the migration regex is later tightened or relaxed.
    """
    from openbb_pine.compiler.v5_migration import migrate_v5_to_v6
    from openbb_pine.telemetry import OpenBBTelemetrySink

    sink = OpenBBTelemetrySink()

    v5_src_with_unhandled = (
        "//@version=5\nindicator(\"t\")\n"
        # Third arg contains parens → char class [^,()] can't match →
        # 3-arg regex fails → literal iff( survives → sentinel fires once.
        "x = iff(close > 0, 1, foo(1, 2))\n"
    )
    with pytest.raises(PineUnsupportedFeatureError):
        migrate_v5_to_v6(v5_src_with_unhandled, telemetry=sink)

    # Exact-match assertion: exactly one PF003 fire for exactly one
    # residual ``iff(`` sentinel. Equality (not ``.get(...) == 1``)
    # catches accidental cross-fires.
    assert sink.get_unsupported_feature_counts() == {"PF003": 1}


def test_injected_sink_receives_v5_migration_signal_nested_iff() -> None:
    """Regression companion: the nested-arg ``iff(c1, iff(c2, 1, 2), 3)``
    form the plan originally called out. The 3-arg regex ``[^,()]+?`` in
    V5_REWRITES cannot match past the inner ``iff(``'s parens, so the
    outer ``iff(`` also survives the rewrite loop and the sentinel scan
    fires exactly once.

    Kept alongside the parens-in-arg fixture above so BOTH the
    nested-iff and the nested-non-iff paren paths are covered — regex
    changes that break either will surface here.
    """
    from openbb_pine.compiler.v5_migration import migrate_v5_to_v6
    from openbb_pine.telemetry import OpenBBTelemetrySink

    sink = OpenBBTelemetrySink()

    v5_src_with_unhandled = (
        "//@version=5\nindicator(\"t\")\n"
        "x = iff(close > 0, iff(close > 1, 1, 2), 3)\n"
    )
    with pytest.raises(PineUnsupportedFeatureError):
        migrate_v5_to_v6(v5_src_with_unhandled, telemetry=sink)

    assert sink.get_unsupported_feature_counts() == {"PF003": 1}


def test_injected_sink_receives_detect_pine_version_signal() -> None:
    """detect_pine_version's PF001/PF002 raises MUST call
    ``sink.record_unsupported_feature(...)`` on the injected sink."""
    from openbb_pine.compiler.v5_migration import detect_pine_version
    from openbb_pine.telemetry import OpenBBTelemetrySink

    sink = OpenBBTelemetrySink()
    with pytest.raises(PineUnsupportedFeatureError):
        # v4 → PF001
        detect_pine_version("//@version=4\n", telemetry=sink)
    assert sink.get_unsupported_feature_counts().get("PF001") == 1

    # v7 → PF002
    with pytest.raises(PineUnsupportedFeatureError):
        detect_pine_version("//@version=7\n", telemetry=sink)
    assert sink.get_unsupported_feature_counts().get("PF002") == 1


def test_module_level_recorders_stay_functional_for_back_compat() -> None:
    """The module-level ``record_*`` / ``get_*_counts`` / ``reset_metrics``
    helpers are preserved as a thin delegation to a module-global
    ``OpenBBTelemetrySink`` so pre-E0.4 tests that hit those free
    functions directly keep working."""
    from openbb_pine.telemetry import (
        get_unsupported_builtin_counts,
        record_unsupported_builtin,
        reset_metrics,
    )

    reset_metrics()
    record_unsupported_builtin("ta.foo")
    record_unsupported_builtin("ta.foo")
    assert get_unsupported_builtin_counts()["ta.foo"] == 2
    reset_metrics()
    assert get_unsupported_builtin_counts() == {}
