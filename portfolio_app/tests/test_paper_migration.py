"""Structural tests for the paper-trading migration file.

Bead: OpenBBTechnical-qy83.1.5 — Draft paper_* migration file
(reviewed by E1+E3).

M0 scope: the migration file **exists** and is **syntactically valid SQL**
with all 5 tables + all 5 privacy-critical columns from PRD section 16.3.
It does NOT need to be applied at M0 (apply is P2.4.8). These tests
enforce the schema contract so nobody merges a migration that silently
drops one of the isolation columns (`user_id`) or breaks the append-only
rule on `paper_ledger`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Migration lives with the app it augments (portfolio_app owns paper_*).
MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "portfolio_app"
    / "migrations"
    / "001_paper_trading.sql"
)


@pytest.fixture(scope="module")
def sql(sql_raw: str) -> str:
    """Return SQL with ``--`` line-comments stripped.

    Prevents semantic tests from tripping on documentation prose (e.g.
    the header docstring naming ``Portfolio_Positions`` as the sensitive
    table we're deliberately avoiding).
    """
    return re.sub(r"--[^\n]*", "", sql_raw)


@pytest.fixture(scope="module")
def sql_raw() -> str:
    """Return the raw migration text (comments included)."""
    assert MIGRATION_PATH.exists(), f"missing migration: {MIGRATION_PATH}"
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_file_exists() -> None:
    """M0 exit-gate: the file is on disk under portfolio_app/migrations/."""
    assert MIGRATION_PATH.is_file()


@pytest.mark.parametrize(
    "table",
    [
        "paper_accounts",
        "paper_orders",
        "paper_fills",
        "paper_positions",
        "paper_ledger",
    ],
)
def test_every_paper_table_declared(sql: str, table: str) -> None:
    """All 5 PRD section 16.3 tables must be present.

    A `CREATE TABLE IF NOT EXISTS <name>` is required for idempotency —
    reapplying the migration on an existing DB must not error.
    """
    pattern = rf"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+`?{table}`?\s*\("
    assert re.search(
        pattern, sql, re.IGNORECASE
    ), f"CREATE TABLE IF NOT EXISTS {table} not found"


def test_user_id_isolation_column_on_every_table(sql: str) -> None:
    """PRD 16.3 privacy contract: `user_id` present on every paper table.

    Cross-account isolation (bead qy83.4.12, SEV-1) depends on `user_id`
    being on every row so the app can filter without joining. Missing
    even one table = privacy hole. This test *reads the CREATE TABLE
    blocks* and asserts `user_id` inside each.
    """
    # Split on CREATE TABLE boundaries, keep body only.
    blocks = re.split(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+`?(paper_\w+)`?\s*\(",
        sql,
        flags=re.IGNORECASE,
    )
    # blocks = [preamble, name1, body1, name2, body2, ...]
    per_table = dict(zip(blocks[1::2], blocks[2::2], strict=False))
    assert len(per_table) == 5, f"expected 5 paper_ tables, got {len(per_table)}"
    missing = [
        name for name, body in per_table.items() if "user_id" not in body.lower()
    ]
    assert not missing, f"user_id missing on tables: {missing}"


def _extract_table_body(sql: str, table: str) -> str:
    """Return the column-definition body of a CREATE TABLE block.

    Matches from `CREATE TABLE IF NOT EXISTS <table> (` to the matching
    `) ENGINE=` terminator — the exact end of the column-def list in this
    project's SQL style. Avoids semantic tests picking up columns from
    the next table.
    """
    pattern = (
        rf"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+`?{table}`?\s*\((.+?)\)\s*ENGINE\s*="
    )
    m = re.search(pattern, sql, flags=re.IGNORECASE | re.DOTALL)
    assert m, f"CREATE TABLE block for `{table}` not found"
    return m.group(1)


def test_paper_ledger_is_append_only(sql: str) -> None:
    """`paper_ledger` must be append-only per PRD 16.3 + 16.7 (replay).

    Enforced structurally by (a) no `updated_at`, (b) a stable PK
    (`entry_id` is a UUID CHAR(36) — the invariant is uniqueness, not
    monotonicity; ordering is via `occurred_at`), (c) `occurred_at
    TIMESTAMP` for ordering. If the ledger becomes updatable,
    `paper.account.replay` cannot reconstruct historical state —
    which is our determinism contract.

    Docstring corrected in PR #467 R2 (finding 1): earlier version
    misstated the invariant as "monotonic PK".
    """
    body = _extract_table_body(sql, "paper_ledger").lower()
    assert (
        "updated_at" not in body
    ), "paper_ledger must be append-only (no updated_at column)"
    assert "occurred_at" in body, "paper_ledger needs occurred_at for replay ordering"
    assert "entry_id" in body, "paper_ledger needs a stable entry_id PK"


def test_paper_orders_status_enum_covers_all_states(sql: str) -> None:
    """Order status ENUM must include the 6 PRD 16.3 states.

    Missing a state (esp. `rejected` or `partial`) turns the app into a
    liar — orders that hit those states become invalid rows in MySQL
    strict mode. Property caught here rather than in P2 hardening.
    """
    body = _extract_table_body(sql, "paper_orders").lower()
    for state in ("open", "filled", "partial", "cancelled", "rejected", "expired"):
        assert state in body, f"paper_orders status enum missing '{state}'"


def test_migration_uses_utf8mb4(sql: str) -> None:
    """Consistency with create_mysql_setup.sql — utf8mb4 across the DB.

    Latin1 defaults on MySQL 5.x/8.x break international company names
    in dividends/insider tables downstream. Fail fast here, not in P0
    integration.
    """
    assert (
        "utf8mb4" in sql.lower()
    ), "migration must specify utf8mb4 collation (matches fmp_cached setup)"


def test_no_raw_positions_or_lots_data_referenced(sql: str) -> None:
    """Privacy boundary: paper_* must NEVER reference `Portfolio_Positions`.

    Guards against a future accidental FOREIGN KEY that would break the
    isolation contract (PRD section 10.3, section 16.2).
    """
    lowered = sql.lower()
    for banned in ("portfolio_positions", "account_owner", "espp_plan"):
        assert (
            banned not in lowered
        ), f"paper_* migration must not reference sensitive table: {banned}"
