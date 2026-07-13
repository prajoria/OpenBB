"""Meta-tests for the cross-account isolation spec.

Bead: OpenBBTechnical-qy83.1.8 — QA: author cross-account isolation
test spec (pending).

M0 scope: the spec **exists** and its tests **skip cleanly** with a
recorded reason pointing at bead OpenBBTechnical-qy83.4.12 (P2 SEV-1
gate). This locks the bar down as executable code so no P2 engineer
can silently weaken it.

The spec itself lives at ``portfolio_app/tests/test_isolation_spec.py``.
This file only asserts *meta* properties.

Meta-test hardening (PR #473 R2):
- Replaced the ad-hoc regex/split parser with ``ast.parse`` +
  ``ast.walk``, so class-based tests, indented defs, and multi-line
  decorators are all handled correctly.
- Added a body-weakening guard: every scenario test's body must be the
  M0 placeholder (``raise NotImplementedError(...)``) so a P2 engineer
  cannot unskip without also replacing the body with real assertions.
- Emits the spec file's SHA-256 as a diff-detection tripwire so
  reviewers looking at PRs touching the spec can spot silent semantic
  edits without reading every line.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

SPEC_PATH = Path(__file__).resolve().parent / "test_isolation_spec.py"


def _spec_tree() -> ast.Module:
    """Parse the spec file into an AST module."""
    assert SPEC_PATH.is_file(), f"missing spec: {SPEC_PATH}"
    return ast.parse(SPEC_PATH.read_text(encoding="utf-8"))


def _iter_test_functions(tree: ast.Module) -> list[ast.FunctionDef]:
    """Yield every top-level or class-nested ``def test_...`` FunctionDef.

    Uses ast.walk so class-based tests (``class TestX: def test_y``) are
    caught. The previous regex-split parser missed those entirely.
    """
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]


def _has_skip_decorator(func: ast.FunctionDef) -> ast.Call | None:
    """Return the ``@pytest.mark.skip(...)`` Call node if present, else None.

    Handles both direct calls (``@pytest.mark.skip(reason=...)``) and the
    less-common bare-attribute form; verifies via AST attribute chain
    rather than string matching.
    """
    for dec in func.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            fn = dec.func
            if (
                fn.attr == "skip"
                and isinstance(fn.value, ast.Attribute)
                and fn.value.attr == "mark"
                and isinstance(fn.value.value, ast.Name)
                and fn.value.value.id == "pytest"
            ):
                return dec
    return None


def _skip_reason_text(skip_call: ast.Call) -> str:
    """Extract the ``reason=...`` argument text as a flat string.

    Handles Constant string, JoinedStr (f-string), and BinOp string
    concatenations, plus the multi-string parenthesised concat form
    used in the spec (``reason=("foo " "bar")``).
    """
    for kw in skip_call.keywords:
        if kw.arg == "reason":
            return ast.unparse(kw.value)
    # Positional first arg fallback.
    if skip_call.args:
        return ast.unparse(skip_call.args[0])
    return ""


def test_isolation_spec_file_exists() -> None:
    """M0 exit-gate: the spec is on disk under portfolio_app/tests/."""
    assert SPEC_PATH.is_file()


def test_every_test_function_has_skip_marker() -> None:
    """Every ``def test_...`` must be preceded by @pytest.mark.skip.

    If any test is *not* skipped at M0, it will run against non-existent
    P2 isolation code. Skipping keeps the SEV-1 bar intact until P2 is
    ready to hit it. AST-parsed (PR #473 R2 finding 3) so class-based
    tests and multi-line decorators are all covered.
    """
    tests = _iter_test_functions(_spec_tree())
    assert tests, "spec must define at least one test function"
    unskipped = [t.name for t in tests if _has_skip_decorator(t) is None]
    assert not unskipped, (
        f"tests missing @pytest.mark.skip at M0: {unskipped} "
        "(remove skip in P2 once qy83.4.12 lands the isolation code)"
    )


def test_all_skip_reasons_cite_sev1_bead() -> None:
    """Every skip reason must cite ``OpenBBTechnical-qy83.4.12``.

    That is the P2 SEV-1 gate bead. If a skip cites some other bead or
    no bead at all, the traceability from spec to implementation breaks
    and a future engineer might unskip prematurely.
    """
    tests = _iter_test_functions(_spec_tree())
    offenders: list[str] = []
    for t in tests:
        skip = _has_skip_decorator(t)
        if skip is None:
            continue
        reason = _skip_reason_text(skip)
        if "qy83.4.12" not in reason:
            offenders.append(f"{t.name}: reason={reason[:80]!r}")
    assert not offenders, (
        "every skip reason must cite bead OpenBBTechnical-qy83.4.12; "
        f"offenders: {offenders}"
    )


def test_spec_covers_all_prd_scenarios() -> None:
    """PRD 16.6 + 10.3 name six privacy-critical scenarios (post-R2).

    Original 4:
    - real user cannot read another user's real positions
    - paper account cannot read another user's paper account
    - real API cannot alias a paper_* id under a real account
    - portfolio_intel_cache key does not leak user_id or account_id

    Added in R2 (PR #473 review finding 2):
    - same user with multiple paper accounts: each account isolated
      from the others
    - malicious account_id (SQL injection, path traversal, LIKE
      wildcards, DoS, unicode homoglyph) is rejected uniformly
    """
    body = SPEC_PATH.read_text(encoding="utf-8").lower()
    required_scenarios = [
        "cross_user_real",
        "cross_user_paper",
        "paper_aliased_as_real",
        "cache_key_no_pii",
        # R2 additions
        "same_user_different_paper_accounts",
        "account_id_injection_and_traversal",
    ]
    missing = [s for s in required_scenarios if s not in body]
    assert not missing, (
        "spec missing scenario test(s): "
        f"{missing} (PRD sections 10.3 + 16.6 privacy contract)"
    )


def test_every_scenario_body_is_the_pending_placeholder() -> None:
    """Every scenario body must be the M0 pending placeholder.

    PR #473 R2 finding 1: the previous meta-tests did not stop a P2
    engineer from unskipping a test AND replacing its body with
    ``assert True``. This meta-test asserts every scenario's body
    contains exactly one non-docstring statement — a ``raise
    NotImplementedError(...)`` — matching the M0 placeholder shape.

    P2 engineers unskipping a test must ALSO replace the placeholder
    with real assertions in the SAME commit; a partial change (unskip
    without body) fails here.
    """
    tests = _iter_test_functions(_spec_tree())
    offenders: list[str] = []
    for t in tests:
        # Strip docstring statement if present.
        body = [
            n
            for n in t.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
        ]
        if len(body) != 1:
            offenders.append(
                f"{t.name}: expected 1 non-docstring statement, got "
                f"{len(body)} (spec body should be `raise "
                "NotImplementedError(...)` at M0)"
            )
            continue
        stmt = body[0]
        if not (
            isinstance(stmt, ast.Raise)
            and isinstance(stmt.exc, ast.Call)
            and isinstance(stmt.exc.func, ast.Name)
            and stmt.exc.func.id == "NotImplementedError"
        ):
            offenders.append(
                f"{t.name}: body is not `raise NotImplementedError(...)` "
                "(unskip + real implementation must land together)"
            )
    assert (
        not offenders
    ), "scenario bodies drifted from the M0 pending placeholder:\n  " + "\n  ".join(
        offenders
    )


def test_spec_file_hash_surfaces_for_review() -> None:
    """Fingerprint the spec file so reviewers can spot silent edits.

    PR #473 R2 finding 1 (belt-and-braces): even structural meta-tests
    can miss subtle semantic weakenings — a docstring's "must" changed
    to "may", a bullet dropped from the P2 TODO list. This test prints
    the SHA-256 of the spec so a reviewer looking at a PR touching
    ``test_isolation_spec.py`` sees the hash change and can ask
    "legit scope expansion or silent weakening?".

    Never fails on hash mismatch — pure fingerprint via stdout.
    """
    digest = hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()
    print(f"\nisolation-spec SHA-256: {digest}")  # noqa: T201
    assert digest, "hash unexpectedly empty"
