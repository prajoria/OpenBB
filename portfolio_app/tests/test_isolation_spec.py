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


# ---------------------------------------------------------------------------
# Scenario 5 — same_user_different_paper_accounts
# Added in PR #473 R2 (review finding 2): user A owning both paper_A1
# and paper_A2 must NOT see paper_A2 rows when requesting paper_A1. The
# user_id filter passes because they're the same user — the account_id
# filter has to catch this. Missing scenario in the original 4.
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason=(
        "Pending until OpenBBTechnical-qy83.4.12 (P2 SEV-1). PRD §16.6: "
        "account_id must be checked independently of user_id — a user with "
        "multiple paper accounts must NOT see cross-account data even "
        "though the user_id filter passes."
    )
)
def test_same_user_different_paper_accounts_no_leakage() -> None:
    """User A owning paper_A1 must not see paper_A2 rows via a paper_A1 request.

    Threat model: a user creates multiple paper accounts (allowed and
    encouraged per PRD §16.5). If the app only filters by user_id and
    trusts the account_id query param, requesting `/paper/positions?
    account_id=paper_A1` returns rows from paper_A2 as long as they
    belong to user A. That is a per-account isolation violation even
    though it isn't a cross-user leak.

    P2 engineer TODO (do not weaken):
        - Create paper_A1 and paper_A2 both owned by REAL_USER_A
        - Insert one row in each
        - GET /portfolio/intel/paper/positions?account_id=paper_A1 as A
        - Assert rows are EXCLUSIVELY from paper_A1
        - Repeat for /paper/order/list and /paper/fills/list
    """
    raise NotImplementedError("Unskip in qy83.4.12 and implement.")


# ---------------------------------------------------------------------------
# Scenario 6 — account_id_injection_and_traversal
# Added in PR #473 R2 (review finding 2): the account_id query param
# is a user-controlled string that MUST be validated before it enters
# any SQL or filesystem path. Enumeration attacks + SQL/path injection
# not covered by the original 4 scenarios.
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason=(
        "Pending until OpenBBTechnical-qy83.4.12 (P2 SEV-1). PRD §16.6: "
        "account_id is a user-controlled string; every read path must "
        "validate against an allowlist regex and never interpolate raw."
    )
)
def test_account_id_injection_and_traversal_rejected() -> None:
    """Malicious account_id values must be rejected, not enumerated.

    Threat scenarios that must all return 400 (not 200 with data, not
    500 with a stack trace):

    - SQL injection: `account_id="paper_alpha' OR 1=1 --"`
    - Path traversal: `account_id="../real_alpha_brokerage"`
    - Namespace-escape: `account_id="paper_%"` (LIKE-wildcard)
    - Long-string DoS: `account_id="paper_" + "a" * 10_000`
    - Unicode homoglyph: `account_id="paper_аlpha"` (Cyrillic 'а')
    - Enumeration via 403 vs 404 differentiation (existing account
      returns 403, missing account returns 404 — that leaks existence)
      — the API must return the SAME error shape for both.

    P2 engineer TODO (do not weaken):
        - Add a validation regex ^paper_[a-z0-9_]{1,63}$ (or similar)
          at request-parse time
        - Every malicious input above returns 400 with a generic error
        - Existing-vs-missing returns the same status + message
    """
    raise NotImplementedError("Unskip in qy83.4.12 and implement.")
