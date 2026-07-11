"""SEV-1 cross-account isolation specification (pending — unskipped in P2).

Bead:            OpenBBTechnical-qy83.1.8 (this file, M0 placeholder)
Implementation:  OpenBBTechnical-qy83.4.12 (P2 — remove skips, ship code)
PRD reference:   docs/Specs/Portfolio-Intelligence-Engine-PRD.md
                 §10.3 (privacy contract for derived-analytics cache)
                 §16.6 (paper-account isolation + PAPER badge contract)

WHY THIS FILE EXISTS AT M0
--------------------------
Cross-account leakage in paper trading is the single highest-severity
risk on the program. Once P2 lands the paper-account read paths, any
subtle bug that lets one user's request return another user's rows —
or lets a `paper_*` response be aliased under a real `Portfolio_Positions`
account_id — is a privacy incident.

To prevent that class of bug from ever shipping, QA writes the SEV-1
acceptance tests **now**, at M0, before any P2 implementation code
exists. Every test is `@pytest.mark.skip`'d with a reason citing
`OpenBBTechnical-qy83.4.12` — the P2 engineer's job is not to author
the test (impossible to trust) but to *unskip* the pre-existing test
and make it green.

WHAT P2 MUST DO
---------------
1. Land `paper_*` read paths in `portfolio_app/src/intel.py`.
2. Remove `@pytest.mark.skip` from each test below one at a time.
3. Make the assertion green — do NOT weaken the assertion.
4. Every unskipped test must pass in CI before PR merge.
5. `qy83.4.12` cannot close until all 4 tests are unskipped + green.

CONTRACT LOCK
-------------
This file is guarded by `test_isolation_spec_meta.py` which enforces:
- File exists
- Every test is skipped at M0
- Every skip reason cites qy83.4.12
- All 4 named scenarios present

Weakening any of the assertions below (e.g. changing `assert ... == 0`
to `assert ... <= 1`) will be caught in code review because the intent
is stated inline in the docstring.
"""

from __future__ import annotations

import pytest

# Sentinel constants used by the pending tests — the actual objects
# will exist once P2 code lands. Kept at module top so P2 only touches
# the test bodies, not this scaffolding.
REAL_USER_A = "user_alpha"
REAL_USER_B = "user_beta"
PAPER_ACCOUNT_A1 = "paper_alpha_default"
PAPER_ACCOUNT_B1 = "paper_beta_default"
REAL_ACCOUNT_A1 = "real_alpha_brokerage"


# ---------------------------------------------------------------------------
# Scenario 1 — cross_user_real
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason=(
        "Pending until OpenBBTechnical-qy83.4.12 (P2 SEV-1) lands "
        "portfolio_app paper-account read paths. Do NOT unskip until "
        "intel.py enforces user_id filtering on every paper_* query."
    )
)
def test_cross_user_real_no_leakage() -> None:
    """A real user's request must NEVER return another user's positions.

    PRD §10.3 privacy contract. The test hits every /portfolio/*
    endpoint that returns per-user data and asserts that authenticating
    as user A can never surface a row owned by user B — even when
    user B's account_id is supplied as a query parameter.

    P2 engineer TODO (do not weaken):
        - Boot portfolio_app with two seed users A and B
        - Insert one row for each in portfolio_basket
        - GET /portfolio/positions?account=<B's account> as user A
        - Assert response contains ZERO rows belonging to user B
    """
    raise NotImplementedError("Unskip in qy83.4.12 and implement.")


# ---------------------------------------------------------------------------
# Scenario 2 — cross_user_paper
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason=(
        "Pending until OpenBBTechnical-qy83.4.12 (P2 SEV-1) lands "
        "paper_* read paths. Same isolation contract as real accounts, "
        "extended to the paper namespace."
    )
)
def test_cross_user_paper_no_leakage() -> None:
    """User A must not see User B's paper account, orders, fills, or ledger.

    PRD §16.6 privacy contract. Every paper_* table carries `user_id`
    (enforced by the migration in bead qy83.1.5). This test asserts the
    filter is actually applied.

    P2 engineer TODO (do not weaken):
        - Create paper_alpha_default owned by REAL_USER_A
        - Create paper_beta_default owned by REAL_USER_B
        - GET /portfolio/intel/paper/positions?account_id=paper_beta_default
          authenticated as REAL_USER_A
        - Assert 403 or 404 — NEVER 200 with rows
        - Repeat for /paper/order/list and /paper/fills/list
    """
    raise NotImplementedError("Unskip in qy83.4.12 and implement.")


# ---------------------------------------------------------------------------
# Scenario 3 — paper_aliased_as_real
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason=(
        "Pending until OpenBBTechnical-qy83.4.12 (P2 SEV-1). "
        "PRD §16.6: paper responses cannot be aliased under a real "
        "account_id — the account-selector separation must be enforced "
        "server-side, not just in the UI."
    )
)
def test_paper_aliased_as_real_rejected() -> None:
    """The API must refuse to return a paper account under a real ID.

    Threat model: an attacker (or a UI bug) sends
    `GET /portfolio/positions?account=paper_alpha_default` — a real
    positions endpoint with a paper account_id. The server must reject
    the request, NOT silently serve paper data as if it were real.

    Symmetrically, GET /portfolio/intel/paper/positions?account_id=
    real_alpha_brokerage must reject — real account_ids never flow
    through paper endpoints.

    P2 engineer TODO (do not weaken):
        - Real endpoints reject account_ids starting with "paper_"
        - Paper endpoints reject account_ids NOT starting with "paper_"
        - Assert 400 Bad Request with clear error message
        - NEVER 200
    """
    raise NotImplementedError("Unskip in qy83.4.12 and implement.")


# ---------------------------------------------------------------------------
# Scenario 4 — cache_key_no_pii
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason=(
        "Pending until OpenBBTechnical-qy83.4.12 (P2 SEV-1). "
        "PRD §10.3: portfolio_intel_cache keys are SHA-256 of "
        "(symbol, qty) tuples ONLY — never user_id / account_id / lot_id."
    )
)
def test_cache_key_no_pii() -> None:
    """derived-analytics cache keys must not embed user/account/lot PII.

    PRD §10.3: the `portfolio_intel_cache` table is safe to inspect
    without exposing PII because its `portfolio_hash` column is a
    SHA-256 of sorted `(symbol, quantity)` tuples only. If a future
    refactor sneaks `user_id` or `account_id` into the hash pre-image,
    two users with identical portfolios stop sharing the cache line
    AND the cache table becomes PII-tainted.

    P2 engineer TODO (do not weaken):
        - Compute the hash for two users with identical positions
        - Assert the two hashes are BYTE-EQUAL
        - Also: SELECT * FROM information_schema.columns WHERE
          table_name = 'portfolio_intel_cache' returns exactly
          [portfolio_hash, as_of_date, endpoint, payload, created_at]
          — no PII column names ever
    """
    raise NotImplementedError("Unskip in qy83.4.12 and implement.")
