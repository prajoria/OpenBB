"""Round-trip integration tests for the v5→v6 auto-migration shim.

Per PRD §8.1 M1 gate (h): "Pine v5 script runs unedited via the v5→v6
migration shim." This test loads three hand-authored v5 fixtures (PRD §2.1
— no source copied from TradingView), compiles them via ``compile_pine()``,
and asserts:

1. The v5 source compiles to an IR ``Program`` with ``version=6`` and an
   ``IndicatorDecl`` directive (kind="indicator", NOT "study" — which
   doesn't exist as an IR shape).
2. The same script in hand-translated v6 form compiles to a Program with
   the same structural shape — same number of declarations, same number
   of body statements, same directive kind, same directive title, same
   var names appearing in body.

The "same structural shape" comparison is intentionally NOT a full IR
``__eq__`` — IR ``Span`` fields differ because the v5 input has the
``study(` rewrite that shifts column positions in surrounding tokens.
Comparing the "skeleton" (declaration / statement count + names) is the
right granularity for "the migration shim preserves meaning."

These fixtures double as cookbook examples in PRD Phase 4: each one is a
documented v5→v6 diff that demonstrates the shim's coverage. The
``v5_fixtures/`` directory is intentionally small (3 fixtures) — adding
new ones is the M2 wild-corpus telemetry feedback loop, not M1 territory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openbb_pine.compiler import compile_pine_to_program, ir

# Resolve once so test parametrization sees a stable directory regardless
# of where pytest is invoked from. Matches tests/conformance/conftest.py's
# discovery pattern.
FIXTURE_DIR = Path(__file__).resolve().parent / "v5_fixtures"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _skeleton(prog: ir.Program) -> dict[str, object]:
    """Reduce a Program IR to its structural skeleton for shape comparison.

    Loc / Span info varies between the v5-migrated input and the v6
    hand-translation (because the rewrites shift column positions); we
    exclude it. Variable names + declaration kinds + body statement
    classes are the right granularity for "the migration shim preserved
    the script's meaning."
    """
    body_kinds: list[str] = []
    body_names: list[str | None] = []
    for stmt in prog.body:
        body_kinds.append(type(stmt).__name__)
        # Capture the LHS name where applicable so we catch a rewrite
        # that accidentally renamed a variable.
        if isinstance(stmt, ir.Assign) and isinstance(stmt.target, ir.Name):
            body_names.append(stmt.target.id)
        elif isinstance(stmt, ir.VarDecl):
            body_names.append(stmt.name)
        else:
            body_names.append(None)
    return {
        "directive_kind": prog.directive.kind,
        "directive_title": prog.directive.title,
        "declaration_count": len(prog.declarations),
        "declaration_names": [
            d.name for d in prog.declarations
            if isinstance(d, (ir.FunctionDecl, ir.TypeDecl, ir.EnumDecl))
        ],
        "body_kinds": body_kinds,
        "body_names": body_names,
    }


@pytest.mark.parametrize(
    "fixture_name",
    [
        "simple_sma",
        "custom_function",
        "iff_input",
        # Wave 5B-5 X2 additions (bead 0e9.5.60) — real-shaped v5 scripts
        # exercising the migration shim's combined behavior:
        #   * multi_v5_builtins   — study + security + transp all in one.
        #   * typed_function_args — user-defined function with two args.
        #   * combined_rewrites   — study + transp (x2) + iff all in one.
        "multi_v5_builtins",
        "typed_function_args",
        "combined_rewrites",
    ],
)
def test_v5_fixture_compiles_unedited(fixture_name: str) -> None:
    """The M1-gate scenario: a v5 script compiles via the IR-level facade
    without manual edits, and the resulting IR has ``IndicatorDecl``
    (not StudyDecl, which doesn't exist) at top level.

    Uses :func:`compile_pine_to_program` (the IR-level facade) rather than
    the public :func:`compile_pine` (which returns the full
    :class:`CompiledModule` post-C5) so the test can inspect the IR
    skeleton directly. The full compile-pipeline integration is exercised
    by ``test_codegen.TestCompilePineFacadeIntegration``.

    ``type_check=False``: the fixtures include a v5 ``smooth(src) => ...``
    function decl that references a body-level ``length`` — C3 visits
    declarations BEFORE body, so it can't see the outer ``length`` when
    type-checking the function body. That's a known C3 limitation
    (forward-declaration scoping); fixing it is a separate bead. For
    the migration-shape test we only need the parser's raw IR, which is
    what ``type_check=False`` returns.
    """
    v5_src = _read(FIXTURE_DIR / f"{fixture_name}.v5.pine")
    prog = compile_pine_to_program(v5_src, type_check=False)
    assert isinstance(prog, ir.Program), f"{fixture_name}: expected Program IR"
    assert prog.version == 6, (
        f"{fixture_name}: post-migration version must be 6; got {prog.version}"
    )
    assert prog.directive.kind == "indicator", (
        f"{fixture_name}: directive should be indicator (not study); "
        f"got {prog.directive.kind!r}"
    )


@pytest.mark.parametrize(
    "fixture_name",
    [
        "simple_sma",
        "custom_function",
        "iff_input",
        # Wave 5B-5 X2 additions (bead 0e9.5.60) — same 3 real-shaped v5
        # scripts as :func:`test_v5_fixture_compiles_unedited` (see there
        # for individual coverage notes).
        "multi_v5_builtins",
        "typed_function_args",
        "combined_rewrites",
    ],
)
def test_v5_v6_skeleton_equivalence(fixture_name: str) -> None:
    """The v5 migrated source should produce a Program IR with the same
    structural skeleton as the hand-translated v6 source.

    This is the strongest "the migration preserved meaning" assertion we
    can make at the IR layer without a runtime to actually execute the
    script (Phase 1 has no executor yet for unit-style assertions). The
    type checker (C3, sibling bead) will reinforce it once it lands by
    comparing inferred types between the two compilations.
    """
    v5_prog = compile_pine_to_program(
        _read(FIXTURE_DIR / f"{fixture_name}.v5.pine"), type_check=False
    )
    v6_prog = compile_pine_to_program(
        _read(FIXTURE_DIR / f"{fixture_name}.v6.pine"), type_check=False
    )

    v5_sk = _skeleton(v5_prog)
    v6_sk = _skeleton(v6_prog)
    assert v5_sk == v6_sk, (
        f"{fixture_name}: skeleton differs between v5-migrated and "
        f"hand-translated v6 IR.\n  v5: {v5_sk}\n  v6: {v6_sk}"
    )


def test_all_fixtures_present() -> None:
    """Fail loudly if a fixture goes missing — a silent skip would mask
    a regression in the corpus."""
    expected = {
        "simple_sma.v5.pine", "simple_sma.v6.pine",
        "custom_function.v5.pine", "custom_function.v6.pine",
        "iff_input.v5.pine", "iff_input.v6.pine",
        # Wave 5B-5 X2 additions (bead 0e9.5.60).
        "multi_v5_builtins.v5.pine", "multi_v5_builtins.v6.pine",
        "typed_function_args.v5.pine", "typed_function_args.v6.pine",
        "combined_rewrites.v5.pine", "combined_rewrites.v6.pine",
    }
    actual = {p.name for p in FIXTURE_DIR.glob("*.pine")}
    missing = expected - actual
    assert not missing, f"missing v5/v6 fixtures: {missing}"
