"""One-shot: file the child issues for #1934 (ScanSnapshotStore subsystem).

Structure:
- Phase A (persistence): 3 leaves
- Phase B (runner + trigger): 2 leaves
- Phase C (widget wiring): 5 leaves — one per existing stub group
- Phase D (rollout): 2 leaves

The 5 widget stub issues (#1692 #1696 #1697 #1698 #1699) ALREADY EXIST — this
script does not re-file them. Instead we file a small "consolidation" tracker
for each phase-C batch so we can wire the child links up cleanly under #1934.

Usage:
    python scripts/scan_snapshot_plan.py [--dry-run]
"""

# Issue bodies intentionally retain long lines, and this CLI reports progress to stdout.
# ruff: noqa: E501, T201
# pylint: disable=line-too-long

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

REPO = "prajoria/OpenBB"
PROJECT_ID = "PVT_kwHOAOc7384BdSTg"  # Project #4
PARENT = 1934
DEPENDENCY_MARKER = re.compile(r"\[\[([A-Z]\d+)\]\]")
PLAN_BREAKDOWN_HEADING = "## Plan breakdown (filed 2026-08-05)"
PLAN_BREAKDOWN_SECTION = re.compile(
    rf"\n*{re.escape(PLAN_BREAKDOWN_HEADING)}\n.*?(?=\n## |\Z)",
    re.DOTALL,
)


def gh(*args: str) -> str:
    """Run GitHub CLI with the supplied arguments and return stdout."""
    executable = shutil.which("gh")
    if executable is None:
        print("GitHub CLI executable 'gh' was not found.", file=sys.stderr)
        raise SystemExit(127)
    r = subprocess.run(  # noqa: S603 - fixed executable; arguments are passed without a shell.
        [executable, *args],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    if r.returncode != 0:
        print(f"gh {' '.join(args)}\nSTDERR: {r.stderr}", file=sys.stderr)
        raise SystemExit(r.returncode)
    return r.stdout.strip()


def find_open_by_title(title: str) -> int | None:
    """Return the matching issue number when an issue with this title exists."""
    out = gh(
        "issue",
        "list",
        "--repo",
        REPO,
        "--search",
        f'"{title}" in:title',
        "--state",
        "all",
        "--json",
        "number,title",
        "--limit",
        "10",
    )
    for it in json.loads(out or "[]"):
        if it["title"].strip() == title.strip():
            return int(it["number"])
    return None


def create_issue(title: str, body: str, dry: bool) -> int:
    """Create an issue or synchronize the body of an exact-title match."""
    existing = find_open_by_title(title)
    if existing:
        if dry:
            print(f"  exists: #{existing}  {title[:70]}")
        else:
            gh(
                "issue",
                "edit",
                str(existing),
                "--repo",
                REPO,
                "--body",
                body,
            )
            print(f"  updated: #{existing}  {title[:70]}")
        return existing
    if dry:
        print(f"  DRY create: {title}")
        return 0
    url = gh("issue", "create", "--repo", REPO, "--title", title, "--body", body)
    n = int(url.rstrip("/").rsplit("/", 1)[-1])
    print(f"  created #{n}  {title[:70]}")
    return n


def node_id_for(num: int) -> str:
    """Return the GitHub GraphQL node ID for an issue number."""
    return gh("api", f"repos/{REPO}/issues/{num}", "--jq", ".node_id")


def add_to_project(num: int, dry: bool) -> None:
    """Add an issue to Portfolio Intelligence Engine Project #4."""
    if dry or num == 0:
        return
    nid = node_id_for(num)
    q = "mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}"
    gh(
        "api",
        "graphql",
        "-f",
        f"query={q}",
        "-f",
        f"p={PROJECT_ID}",
        "-f",
        f"c={nid}",
    )


@dataclass
class Node:
    """Describe one child issue in the ScanSnapshotStore implementation plan."""

    key: str
    title: str
    body: str
    number: int = 0


def resolve_dependencies(
    body: str, issue_numbers: dict[str, int], dry_run: bool
) -> str:
    """Resolve dependency markers from issue numbers returned by GitHub."""

    def replace_marker(match: re.Match[str]) -> str:
        key = match.group(1)
        number = issue_numbers.get(key)
        if number:
            return f"#{number}"
        if dry_run:
            return f"#<{key}>"
        raise ValueError(f"Dependency {key} has not been created yet")

    return DEPENDENCY_MARKER.sub(replace_marker, body)


def render_parent_body(body: str, plan: list[Node]) -> str:
    """Replace prior plan breakdowns while preserving other parent content."""
    body_without_breakdowns = PLAN_BREAKDOWN_SECTION.sub("", body).rstrip()
    lines = [PLAN_BREAKDOWN_HEADING, ""]
    lines.extend(f"- #{node.number} — {node.title}" for node in plan)
    return body_without_breakdowns + "\n\n" + "\n".join(lines)


def build_plan() -> list[Node]:
    """Build the ordered child-issue plan for the ScanSnapshotStore feature."""
    parent_ref = f"Parent Feature: #{PARENT} (ScanSnapshotStore FRS)"

    return [
        # Phase A — persistence layer
        Node(
            key="A1",
            title="[techtrade] ScanSnapshotStore Phase A1 — DDL + schema (tt_scan_snapshot table)",
            body=f"""{parent_ref}

Ships the MySQL DDL for `tt_scan_snapshot` per FRS §5, plus the equivalent
SQLite schema helper used by the fallback impl.

## Scope

- New file `openbb_platform/extensions/techtrade/openbb_techtrade/engine/scan_schema.py`:
  - MySQL DDL constant `_TT_SCAN_SNAPSHOT_DDL` (BIGINT PK autoincrement,
    scan_kind VARCHAR(32), segment VARCHAR(64), computed_at DATETIME(6),
    engine_version VARCHAR(32), preset VARCHAR(32), row_count INT,
    meta_json JSON, payload_json JSON, INDEX(scan_kind, segment,
    computed_at DESC)).
  - Sqlite DDL constant with equivalent shape (JSON columns → TEXT).
  - `ensure_schema_mysql(cursor)` and `ensure_schema_sqlite(conn)`
    idempotent helpers, mirroring `_ensure_schema` in MysqlPaperEngine.

## Non-goals

- No store implementation. That's A2.
- No migration CLI. That's part of A2.

## Acceptance

- Schema constants match FRS §5 exactly.
- `ensure_schema_mysql` on a fresh test DB creates the table; second call is a
  no-op.
- Retention decision (per @user): **keep latest N per (scan_kind, segment)** —
  the DDL is retention-agnostic; retention runs in the write path (A2).
- Chunking decision (per @user): **per-segment snapshots**. Segment is a
  non-nullable column; wildcard "all segments" writes are not allowed.

Refs #1934.
""",
        ),
        Node(
            key="A2",
            title="[techtrade] ScanSnapshotStore Phase A2 — Protocol + Mysql/Sqlite impls + factory + migration CLI",
            body=f"""{parent_ref}

Ships the core store surface per FRS §4 FR-1..FR-4 + the migration CLI.

## Scope

- `ScanSnapshotStore` Protocol (`write_snapshot`, `read_latest`, `read_by_id`,
  `list_snapshots`) — mirrors the `PortfolioStore`/`PaperEngine` protocol
  pattern.
- `MysqlScanSnapshotStore` — default. Acquires the fmp_cached pool via
  `get_connection_pool()` (same as `MysqlPaperEngine`). Retention: on every
  write, delete rows for the same (scan_kind, segment) beyond the latest
  `N=10` (default; overridable via `PI_SCAN_RETENTION_N`).
- `SqliteScanSnapshotStore` — fallback. `~/.portfolio_intel/scan.db`
  (override `PI_SCAN_DB`).
- `get_default_scan_store()` factory — honors `PI_SCAN_ENGINE` env var
  (`mysql` default, `sqlite` fallback); graceful WARNING+fallback on MySQL
  unreachable, mirroring `get_default_engine` in `paper_engine.py`.
- `openbb_techtrade/engine/migrate_scan_to_mysql.py` — one-shot CLI mirroring
  `migrate_paper_to_mysql.py`. Idempotent, `INSERT IGNORE`.

## Non-goals

- No runner (Phase B1). This ticket ships the store surface only, invoked
  directly in tests.

## Acceptance

- Unit tests per FRS §8: T-1 (roundtrip), T-3 (loud-empty on empty store),
  T-4 (factory selector parity), T-6 (payload shape contract).
- Integration tests skipped-in-CI unless `FMP_CACHE_TEST_MODE=true`.
- R7.11 mutation-twin discipline on every load-bearing test.

Refs #1934. Blocked-by [[A1]] (A1 schema).
""",
        ),
        Node(
            key="A3",
            title="[techtrade] ScanSnapshotStore Phase A3 — recorded fixtures + realistic-shape tests for 3 scan_kinds",
            body=f"""{parent_ref}

Ships the "realistic-shape" fixtures for the store + widget tests.

Per CLAUDE.md testing rules R1 (no mocks-that-agree-with-themselves): each
scan_kind fixture is a real recorded payload from `scan_segments` /
`screener_router.movers` / `signals_router.signals` captured once and
checked in.

## Scope

- `openbb_platform/extensions/techtrade/tests/fixtures/scan_snapshots/`:
  - `movers_information_technology_2026-08-05.json`
  - `signals_information_technology_2026-08-05.json`
  - `scan_full_2026-08-05.json` (11 GICS segments — payload structure only,
    top_n=3 per segment to keep the file small)
- `openbb_platform/extensions/techtrade/tests/test_scan_snapshot_shapes.py`:
  - Assert every fixture round-trips through `write_snapshot` → `read_latest`
    with byte-identical payload.
  - Assert every fixture's payload rows contain the columns the
    corresponding widget renders (FR contract test).
  - Loud-empty assertion — empty store on any scan_kind returns None; the
    widget shim renders the friendly no-scan-yet markdown.

## Non-goals

- Fixture recording script itself. Fixtures are recorded manually once and
  checked in; the record command is documented in the docstring.

## Acceptance

- 3 fixtures under 500 KB total.
- All shape-contract tests pass.
- No secrets / PII in the fixtures. All symbols round-numbered / anonymized
  where necessary.

Refs #1934. Blocked-by [[A1]] (A1), [[A2]] (A2).
""",
        ),
        # Phase B — runner + trigger
        Node(
            key="B1",
            title="[techtrade] ScanSnapshotStore Phase B1 — scan_runner CLI (run_scan + `python -m` entry)",
            body=f"""{parent_ref}

Ships the scan runner per FRS §4 FR-5.

## Scope

- `openbb_techtrade/engine/scan_runner.py`:
  - `run_scan(scan_kind: str, segments: list[str] | None = None, top_n: int = 3, preset: str = "default") -> list[int]` — returns list of snapshot_ids written.
  - Per-segment writes (chunking decision: per-segment snapshots). A `scan`
    over 11 GICS sectors produces 11 rows, one per segment. Partial progress
    visible after each segment completes.
  - Idempotent under concurrent invocation (safe from cron + manual invoke at
    the same time). Uses `INSERT` for new rows only.
  - CLI entry: `python -m openbb_techtrade.engine.scan_runner --scan-kind
    movers --segments "Information Technology,Financials" --top-n 3`.
- Structured logging: one log line per segment completed, one summary at the
  end (segments processed, snapshots written, total elapsed).

## Acceptance

- `run_scan('movers', segments=['Information Technology'], top_n=3)` persists
  a snapshot; subsequent `read_latest('movers','Information Technology')`
  returns it with correct `computed_at`, `row_count`, `payload`.
- Idempotency: two parallel runs against the same segment produce two separate
  snapshot rows with distinct `snapshot_id`s; readers see the latest.
- Integration test (`@pytest.mark.integration`, skipped in CI) hits real MySQL.

Refs #1934. Blocked-by [[A2]] (A2).
""",
        ),
        Node(
            key="B2",
            title="[techtrade] ScanSnapshotStore Phase B2 — POST /tt/scan/trigger endpoint (2 modes: dev-sync + prod-detached)",
            body=f"""{parent_ref}

Ships the optional HTTP trigger per FRS §4 FR-8.

## Scope

- New route in `widget_backend` (or a small sibling router):
  `POST /tt/scan/trigger` with body `{{scan_kind, segments, top_n, preset}}`.
- Two modes selected by env var `PI_ENABLE_SCAN_TRIGGER`:
  - `PI_ENABLE_SCAN_TRIGGER=dev` — synchronous invocation. Blocks the HTTP
    worker until run_scan returns. Marked prominently as dev-only in the
    endpoint docstring + response body. Rate-limited to one concurrent run
    per (scan_kind, segment) via a Redis-free file-lock or an in-process
    Lock (single-worker uvicorn assumption).
  - `PI_ENABLE_SCAN_TRIGGER=prod` — spawns a detached subprocess via
    `subprocess.Popen([sys.executable, "-m", "openbb_techtrade.engine.scan_runner", ...])`.
    Returns `202 Accepted` with a `{{queued_at, scan_kind, segments}}` body
    within ~50ms.
  - Unset or any other value — returns `404` (endpoint hidden, feature off).
- Auth: per ADR-#1809-adjacent posture, this endpoint is loopback-only and
  respects the existing widget_backend auth mode (`required` vs
  `loopback-dev`).

## Acceptance

- `PI_ENABLE_SCAN_TRIGGER=dev` mode: request returns 200 with the persisted
  `snapshot_id`; blocking behavior documented + tested with a stubbed short
  run.
- `PI_ENABLE_SCAN_TRIGGER=prod` mode: request returns 202 in < 100ms; a
  detached subprocess is running; a subsequent `read_latest` after that
  subprocess completes returns the new snapshot.
- Endpoint hidden (404) when env unset.
- Node:test-style contract: response schema matches the OpenAPI shape.

Refs #1934. Blocked-by [[B1]] (B1).
""",
        ),
        # Phase C — widget rewiring
        Node(
            key="C1",
            title="[techtrade] ScanSnapshotStore Phase C — wire tt_movers + tt_scan + tt_scan_export widgets (batch, closes #1692)",
            body=f"""{parent_ref}

Wires the three `movers`/`scan` widgets to the snapshot store. Closes #1692.

## Scope

- Each of `tt_movers`, `tt_scan`, `tt_scan_export` widget endpoints:
  - Replace synchronous compute with `store.read_latest(scan_kind, segment)`.
  - Add freshness line: "Scanned <ago> ago" from `computed_at`.
  - Add staleness badge if `computed_at` older than 24h (FRS §10 Q3 answer).
  - Loud-empty: friendly markdown when store returns None ("no scan yet —
    run `python -m openbb_techtrade.engine.scan_runner ...`").

## Acceptance

- All 3 widgets render < 500ms against a populated store (AC-1).
- All 3 render friendly loud-empty when store is empty (AC-4).
- All 3 render freshness line + staleness badge (AC-5).
- `tt_scan_export` still produces the CSV/JSON export from the persisted
  payload (no OHLCV fetch on the export path).

Closes #1692.
Refs #1934. Blocked-by [[B1]] (B1 runner) + [[A3]] (A3 fixtures for the tests).
""",
        ),
        Node(
            key="C2",
            title="[techtrade] ScanSnapshotStore Phase C — wire tt_signals + tt_plan + tt_orders + tt_simulate widgets (batch, closes #1696)",
            body=f"""{parent_ref}

Wires the four `signals`/`plan` family widgets. Closes #1696.

Same read-latest + freshness + loud-empty pattern as the previous batch.
`scan_kind` per widget:
- `tt_signals` → `signals`
- `tt_plan` → `plan`
- `tt_orders` → `orders`
- `tt_simulate` → `simulate`

## Acceptance

Same as Phase C1: < 500ms reads, loud-empty on empty store, freshness +
staleness rendering.

Closes #1696.
Refs #1934. Blocked-by [[B1]] (B1) + [[A3]] (A3).
""",
        ),
        Node(
            key="C3",
            title="[techtrade] ScanSnapshotStore Phase C — wire tt_validate widget (closes #1697)",
            body=f"""{parent_ref}

Wires `tt_validate` to `scan_kind = validate`. Same read-latest + freshness +
loud-empty pattern.

Closes #1697.
Refs #1934. Blocked-by [[B1]] + [[A3]].
""",
        ),
        Node(
            key="C4",
            title="[techtrade] ScanSnapshotStore Phase C — wire tt_tune widget (closes #1698)",
            body=f"""{parent_ref}

Wires `tt_tune` to `scan_kind = tune`. Same read-latest + freshness +
loud-empty pattern.

Closes #1698.
Refs #1934. Blocked-by [[B1]] + [[A3]].
""",
        ),
        Node(
            key="C5",
            title="[techtrade] ScanSnapshotStore Phase C — wire tt_audit widget (closes #1699)",
            body=f"""{parent_ref}

Wires `tt_audit` to `scan_kind = audit`. Same read-latest + freshness +
loud-empty pattern.

Closes #1699.
Refs #1934. Blocked-by [[B1]] + [[A3]].
""",
        ),
        # Phase D — rollout
        Node(
            key="D1",
            title="[techtrade] ScanSnapshotStore Phase D — retention worker + snapshot pruning verification",
            body=f"""{parent_ref}

Retention was decided as **keep latest N per (scan_kind, segment)** with
N=10 default overridable via `PI_SCAN_RETENTION_N`.

Phase A2 ships the write-time retention delete. This ticket ships:

## Scope

- Standalone `prune_snapshots(scan_kind=None, segment=None, keep_n=None)`
  entry point in `scan_runner.py`, invocable via
  `python -m openbb_techtrade.engine.scan_runner --prune` — useful for
  operators who tune `keep_n` retroactively and want to clean up
  accumulated history.
- Integration test that seeds N+5 snapshots for the same (scan_kind, segment)
  and asserts the write-time prune leaves exactly N rows.
- Docstring note: retention on migration from SQLite → MySQL is enforced
  on the first write per (scan_kind, segment) after migration, NOT during
  migration itself (migration is `INSERT IGNORE`; keep behavior additive).

## Acceptance

- After 15 sequential writes to the same segment with N=10, only the 10 most
  recent rows survive.
- `--prune` CLI is idempotent (re-run does not error).

Refs #1934. Blocked-by [[A2]] (A2).
""",
        ),
        Node(
            key="D2",
            title="[techtrade] ScanSnapshotStore Phase D — cron / Task Scheduler cadence docs + example config",
            body=f"""{parent_ref}

Documents the operator-facing cadence patterns.

## Scope

- New file `openbb_platform/extensions/techtrade/docs/scan_runner_cadence.md`:
  - Recommended cadences per scan_kind (movers: 1h during market hours, scan:
    24h EOD, validate/tune: 7d, audit: daily post-close, etc.).
  - Example crontab entry for POSIX (invokes `openbb-techtrade-scan` or
    `python -m openbb_techtrade.engine.scan_runner`).
  - Example Windows Task Scheduler XML with the equivalent schedule.
  - Recovery: what happens if a run misses its slot / a run overruns.
  - Freshness threshold defaults (`PI_SCAN_STALENESS_HOURS=24`) and how to
    override per environment.
- Reference from the widget docstrings that mention "scanned <ago>" so users
  finding a stale badge have a next-step link.

## Acceptance

- Doc validates against markdown lint.
- Example crontab is copy-pasteable (works against `.venv_portfolio`).

Refs #1934. Blocked-by [[B1]] (B1).
""",
        ),
    ]


def main() -> int:
    """File or preview the child issues and update their parent issue."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    plan = build_plan()
    issue_numbers: dict[str, int] = {}
    print(f"Filing {len(plan)} child issues under #{PARENT}...\n")
    for node in plan:
        body = resolve_dependencies(node.body, issue_numbers, args.dry_run)
        node.number = create_issue(node.title, body, args.dry_run)
        issue_numbers[node.key] = node.number
        add_to_project(node.number, args.dry_run)
    if not args.dry_run:
        # Update parent #1934 with the phase breakdown
        body = gh(
            "issue",
            "view",
            str(PARENT),
            "--repo",
            REPO,
            "--json",
            "body",
            "--jq",
            ".body",
        )
        new_body = render_parent_body(body, plan)
        gh("issue", "edit", str(PARENT), "--repo", REPO, "--body", new_body)
        print(f"\nUpdated #{PARENT} body with plan breakdown.")
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
