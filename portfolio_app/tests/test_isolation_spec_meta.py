"""Meta-tests for the cross-account isolation spec.

Bead: OpenBBTechnical-qy83.1.8 — QA: author cross-account isolation
test spec (pending).

M0 scope: the spec **exists** and its tests **skip cleanly** with a
recorded reason pointing at bead OpenBBTechnical-qy83.4.12 (P2 SEV-1
gate). This locks the bar down as executable code so no P2 engineer
can silently weaken it — they can only *unskip* it once their
implementation actually satisfies the assertions.

The spec itself lives at ``portfolio_app/tests/test_isolation_spec.py``.
This file only asserts *meta* properties: it exists, every test is
marked pending, the skip reasons all cite the SEV-1 bead, and the
scenarios cover the four privacy-critical cases from PRD sections
10.3 + 16.6.
"""

from __future__ import annotations

import re
from pathlib import Path

SPEC_PATH = Path(__file__).resolve().parent / "test_isolation_spec.py"


def test_isolation_spec_file_exists() -> None:
    """M0 exit-gate: the spec is on disk under portfolio_app/tests/."""
    assert SPEC_PATH.is_file(), f"missing spec: {SPEC_PATH}"


def _iter_test_blocks(body: str) -> list[tuple[str, str]]:
    """Yield ``(test_name, decorators_above)`` for each ``def test_...``.

    Splits the file on ``def test_`` boundaries; the chunk *before*
    each split contains that test's decorators. This handles multi-line
    ``@pytest.mark.skip(reason=(...))`` decorators cleanly, which a
    lookbehind regex cannot.
    """
    parts = re.split(r"\n(?=def (test_\w+)\()", body)
    # parts = [preamble, name1, body1, name2, body2, ...]
    out: list[tuple[str, str]] = []
    preceding = parts[0]
    for i in range(1, len(parts), 2):
        name = parts[i]
        preceding_chunk = preceding
        out.append((name, preceding_chunk))
        preceding = parts[i + 1] if i + 1 < len(parts) else ""
    return out


def test_every_test_function_has_skip_marker() -> None:
    """Every ``def test_...`` must be preceded by an @pytest.mark.skip.

    If any test is *not* skipped at M0, it will run against non-existent
    P2 isolation code and produce a red baseline — which someone will
    then "fix" by weakening the assertion. Skipping keeps the bar
    intact until P2 is ready to hit it.
    """
    body = SPEC_PATH.read_text(encoding="utf-8")
    blocks = _iter_test_blocks(body)
    assert blocks, "spec must define at least one test function"
    for name, preceding in blocks:
        # Only the LAST decorator block above the def belongs to this
        # test — walk back over blank/decorator lines from end of chunk.
        tail = preceding.rstrip().splitlines()[-15:]  # generous window
        joined = "\n".join(tail)
        assert "@pytest.mark.skip" in joined, (
            f"test {name} must be @pytest.mark.skip'd at M0 "
            "(remove skip in P2 once qy83.4.12 lands the isolation code)"
        )


def test_all_skip_reasons_cite_sev1_bead() -> None:
    """Every skip reason must cite ``OpenBBTechnical-qy83.4.12``.

    That is the P2 SEV-1 gate bead. If a skip cites some other bead or
    no bead at all, the traceability from spec to implementation breaks
    and a future engineer might unskip prematurely.
    """
    body = SPEC_PATH.read_text(encoding="utf-8")
    # Find every @pytest.mark.skip(...) block INCLUDING multiline
    # parenthesized reason arguments.
    skip_blocks = re.findall(
        r"@pytest\.mark\.skip\s*\((.+?)\)\s*\ndef test_",
        body,
        flags=re.DOTALL,
    )
    assert skip_blocks, "no @pytest.mark.skip(...) decorators found on tests"
    for block in skip_blocks:
        assert "qy83.4.12" in block, (
            "every skip reason must cite bead OpenBBTechnical-qy83.4.12 "
            f"(SEV-1 isolation gate); got: {block[:80]!r}"
        )


def test_spec_covers_four_prd_scenarios() -> None:
    """PRD 16.6 + 10.3 name four privacy-critical scenarios.

    - real user cannot read another user's real positions
    - paper account cannot read another user's paper account
    - real API cannot alias a paper_* id under a real account
    - portfolio_intel_cache key does not leak user_id or account_id

    Named test functions matching each scenario must be present so P2
    engineers know exactly which cases they are implementing against.
    """
    body = SPEC_PATH.read_text(encoding="utf-8").lower()
    required_scenarios = [
        "cross_user_real",
        "cross_user_paper",
        "paper_aliased_as_real",
        "cache_key_no_pii",
    ]
    missing = [s for s in required_scenarios if s not in body]
    assert not missing, (
        "spec missing scenario test(s): "
        f"{missing} (PRD sections 10.3 + 16.6 privacy contract)"
    )
