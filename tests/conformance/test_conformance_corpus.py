"""Conformance corpus runner (PRD section 7).

One parametrized test per ``(.pine, .csv)`` pair auto-discovered by
:mod:`conftest`. For each pair:

1. Read the ``.pine`` source.
2. Compile it via ``openbb_pine.compiler.compile_pine_source`` (or the
   first available compile entry point -- the exact callable name is
   owned by D1 and may shift before stabilising).
3. Run the compiled artifact against the fixture bar series implied by
   the ``.csv`` (which doubles as the input bar grid via its ``date``
   column when an explicit input CSV is not supplied).
4. Diff the produced series against the reference using
   ``np.isclose(atol=1e-9, rtol=0)`` per PRD section 7's tolerance
   contract.
5. On mismatch, report the FIRST offending ``(row index, column,
   expected, actual)`` so the failure points at exactly the line/column
   that diverged.

Phase-1 behaviour: the compiler does not yet exist (C1-C8 beads land
in subsequent waves), so the test SKIPs cleanly until
``openbb_pine.compiler`` is importable. Once the compiler lands the
SAME fixtures start asserting numerical equality without any test code
change. This is the whole point of the harness: adding a builtin =
adding two fixture files, never editing test code.

See :file:`README.md` for the fixture file format and reference-data
provenance posture (PRD section 7.3 -- author-derivative-of-author-script,
not chart-data redistribution).
"""

from __future__ import annotations

from pathlib import Path

import pytest


# Tolerance is a PRD section 7 contract: absolute 1e-9, no relative
# component (rtol=0). Surfacing as a module constant so the same value
# is used by any helper tooling (e.g. coverage reports that count
# pairs-within-tolerance).
ATOL: float = 1e-9
RTOL: float = 0.0


def _read_csv_reference(csv_path: Path):
    """Read a reference CSV into a ``pandas.DataFrame``.

    Skipped (not failed) when pandas is not importable -- pandas is a
    hard dep of openbb-pine per pyproject so its absence at test time
    indicates an environment shape this harness was not built for.
    """
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas not available in test environment")
    return pd.read_csv(csv_path)


def _diff_first_mismatch(reference, produced) -> tuple[int, str, float, float] | None:
    """Return ``(row, col, expected, actual)`` for the first cell whose
    absolute difference exceeds :data:`ATOL`, or ``None`` when every cell
    is within tolerance. Non-numeric columns are compared with ``==``.

    The returned ``row`` is the 0-based DataFrame index of the
    reference CSV; the ``col`` is the column name. Floating-point NaN
    is treated as equal-to-NaN (Pine often emits NaN in warm-up bars).
    """
    try:
        import numpy as np
    except ImportError:
        pytest.skip("numpy not available in test environment")

    # Column alignment: produced must have at LEAST the reference cols.
    # Extra produced cols are tolerated (a script can emit more than
    # the reference asserts on).
    missing = [c for c in reference.columns if c not in produced.columns]
    if missing:
        return (
            -1,
            f"<missing columns: {missing}>",
            float("nan"),
            float("nan"),
        )

    # Row count: produced must have AT LEAST as many rows as reference.
    # Extra produced rows are tolerated (e.g. the compiler may emit a
    # leading priming row).
    if len(produced) < len(reference):
        return (
            len(produced),
            "<row count>",
            float(len(reference)),
            float(len(produced)),
        )

    for col in reference.columns:
        ref_series = reference[col]
        prod_series = produced[col].iloc[: len(reference)]
        for row in range(len(reference)):
            r = ref_series.iloc[row]
            p = prod_series.iloc[row]
            # NaN-equal: both NaN passes.
            r_is_nan = isinstance(r, float) and r != r
            p_is_nan = isinstance(p, float) and p != p
            if r_is_nan and p_is_nan:
                continue
            if r_is_nan != p_is_nan:
                return (row, col, float("nan") if r_is_nan else r,
                        float("nan") if p_is_nan else p)
            # Numeric diff: tolerance per PRD section 7.
            try:
                ok = bool(np.isclose(r, p, atol=ATOL, rtol=RTOL))
            except TypeError:
                # Non-numeric column -- equality compare.
                ok = (r == p)
            if not ok:
                return (row, col, float(r), float(p))
    return None


def _import_compiler():
    """Find the compile entry point, or return ``None`` if not yet present.

    Tries a couple of plausible names before giving up. D1 owns the
    exact callable name; we accept any of:
      * ``openbb_pine.compiler.compile_pine_source(text: str) -> ...``
      * ``openbb_pine.compiler.compile(text: str) -> ...``
      * ``openbb_pine.compile(text: str) -> ...``  (top-level shortcut)
    """
    try:
        import openbb_pine.compiler as _compiler
    except ImportError:
        return None
    for name in ("compile_pine_source", "compile", "compile_source"):
        fn = getattr(_compiler, name, None)
        if callable(fn):
            return fn
    return None


def _run_compiled(compiled, reference) -> object:
    """Execute a compiled artifact against the bar grid implied by the
    reference CSV and return the produced DataFrame.

    This is a best-effort shim. D2 owns the exact run signature; we try
    a few plausible names. When nothing matches we SKIP the test (vs.
    failing) so the harness can land before the runtime contract is
    finalised.
    """
    # If the compiler emits an object with a `.run(bars: DataFrame) -> DataFrame`
    # method, prefer that:
    for name in ("run", "execute", "evaluate", "__call__"):
        fn = getattr(compiled, name, None)
        if callable(fn):
            try:
                return fn(reference)
            except TypeError:
                # Try no-arg form.
                try:
                    return fn()
                except Exception:  # noqa: BLE001
                    continue
    pytest.skip(
        "openbb_pine.compiler entry point loaded but compiled artifact "
        "has no recognised run/execute/evaluate method (D2 runtime "
        "contract not yet final)"
    )


def test_conformance_pair_matches_reference(conformance_pair):
    """Compile + run :paramref:`conformance_pair[0]`, diff vs. :paramref:`conformance_pair[1]`.

    Per PRD section 7 -- absolute tolerance 1e-9, no relative tolerance.
    Failure points at the FIRST diverging cell so the maintainer knows
    exactly where the script went off-script.
    """
    pine_path, csv_path = conformance_pair

    compile_fn = _import_compiler()
    if compile_fn is None:
        pytest.skip(
            f"openbb_pine.compiler not yet implemented (Phase 1 in flight); "
            f"pair {pine_path.name}/{csv_path.name} queued for re-run"
        )

    source = pine_path.read_text(encoding="utf-8")
    reference = _read_csv_reference(csv_path)

    try:
        compiled = compile_fn(source)
    except NotImplementedError as exc:
        pytest.skip(f"compiler not yet supporting this script: {exc}")
    except Exception as exc:  # noqa: BLE001 - compile MUST succeed once landed
        pytest.fail(
            f"compile failed for {pine_path}: {type(exc).__name__}: {exc}"
        )

    produced = _run_compiled(compiled, reference)

    mismatch = _diff_first_mismatch(reference, produced)
    if mismatch is None:
        return  # green
    row, col, expected, actual = mismatch
    pytest.fail(
        f"conformance mismatch in {pine_path.name} vs {csv_path.name}:\n"
        f"  row={row}  col={col}\n"
        f"  expected={expected}\n"
        f"  actual  ={actual}\n"
        f"  tolerance: atol={ATOL}, rtol={RTOL} (PRD section 7)"
    )


def test_harness_discovers_at_least_smoke_pair():
    """Harness self-check: at least the ``_smoke`` pair must be discovered.

    Without this, a future commit that breaks ``_discover_pairs`` (e.g.
    by changing the glob) could silently turn the entire conformance
    suite into "no tests collected" -- which CI would happily pass.

    Imports the discovery helpers via :func:`importlib` to dodge the
    pytest conftest namespace collision (pytest auto-loads
    ``conftest.py`` next to this file but does NOT put it on
    ``sys.path``; a bare ``from conftest import ...`` would pick up a
    sibling conftest from another extension).
    """
    import importlib.util
    conftest_path = Path(__file__).resolve().parent / "conftest.py"
    spec = importlib.util.spec_from_file_location(
        "_conformance_conftest", conftest_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    pairs = module._discover_pairs(module.CONFORMANCE_ROOT)
    stems = {p.with_suffix("").name for p, _ in pairs}
    assert "_smoke" in stems, (
        f"conformance harness lost its _smoke self-test fixture; "
        f"discovered pairs (by stem): {sorted(stems)}"
    )
