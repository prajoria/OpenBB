# Portfolio Snapshot Importer — Design Spec

| Field | Value |
|---|---|
| **Status** | v0.2 — Draft, awaiting user approval |
| **Program** | Portfolio Intelligence Engine (GH Project #4) |
| **Long-lived branch** | `portfolio` |
| **Proposed side-branch** | `feat/pi-importer/snapshot-append-only` |
| **Author** | Claude (drafted 2026-07-18, revised same-day for interop) |
| **Reviewer** | @prajoria (approval required per section) |
| **Complementary to** | [`docs/Specs/Portfolio-Intelligence-Engine-PRD.md`](../../Specs/Portfolio-Intelligence-Engine-PRD.md) (main PI PRD — analytics consumer of this store) · [`docs/designs/quant_trading/78-paperbroker-fill-sim.md`](../../designs/quant_trading/78-paperbroker-fill-sim.md) (paper-broker fill sim — a peer, NOT overridden) · [`portfolio_app/README.md`](../../../portfolio_app/README.md) (existing MySQL-backed positions service — this importer produces a parallel local snapshot store, does NOT replace) · [`portfolio_export/README.md`](../../../openbb_platform/tools/portfolio_export/README.md) (upstream producer of the CSVs we consume) |

---

## 0. Scope

Build a **read-only snapshot ingestor** that takes a folder of dated broker CSVs
(Fidelity-shaped `Portfolio_Positions_<Mon>-<DD>-<YYYY>_<user_id>.csv`),
treats each CSV as a **complete point-in-time snapshot** of a portfolio, and
lands them into an **append-only** positions table with full history — so you
can answer:

- "What did the portfolio look like on any given date?"
- "What was added between snapshot A and snapshot B?"
- "What was removed?"
- "How did holdings change (quantity, cost basis, market value) over time?"

**Explicit non-goals** (bounded from the ask — each capability listed here
already lives elsewhere and this importer complements, not overrides):

- ❌ **No real broker integration / API polling / execution.** Order execution
  lives in `docs/designs/quant_trading/78-paperbroker-fill-sim.md`
  (`PaperBroker` in `openbb-techtrade`) and will live in future
  `LiveBroker` implementations of the same `BrokerInterface` Protocol.
  This importer never places orders.
- ❌ **No paper-trading simulator.** The `PaperBroker` above already owns
  next-bar-open fill semantics, slippage, commission, no-look-ahead
  discipline. This importer only records historical snapshots — it does
  NOT model forward trading. The two are peers; reconciling "paper-broker
  state at date D" vs "real broker snapshot at date D" is a downstream
  analysis feature, not this PRD's scope.
- ❌ **No portfolio analytics** (returns, attribution, IRR, Sharpe, factor
  models, X-Ray look-through, event calendar, smart-money overlays,
  rebalancing, alerting). Those all belong to
  `docs/Specs/Portfolio-Intelligence-Engine-PRD.md` and the
  `openbb-portfolio-intel` extension. This importer produces the data
  substrate those analytics can read from (in addition to their existing
  `portfolio_basket`/MySQL source).
- ❌ **No editing of imported snapshots** (append-only; corrections come as
  new snapshots on later dates).
- ❌ **No write path to MySQL `Portfolio_Positions`.** That table is owned
  by the corporate pipeline and read by `portfolio_app`. This importer's
  SQLite store is a **parallel, local mirror** for offline / personal-CSV
  use, not a replacement.
- ❌ **No reading of the CSVs' contents by Claude during design** (only
  headers + Python-tool schema introspection; no dates or user identifiers
  leave the local disk).

**In scope for v1:**

- Discover dated CSVs under a folder (recursive, glob'able)
- Parse each via `portfolio_export.loaders.fidelity.load_positions` (already
  handles Fidelity's quirks — stray trailing comma, `$`/`%` formatting,
  footer/blank rows)
- Extract the snapshot date from the filename (`Jul-18-2026` → `2026-07-18`)
- Extract `user_id` from filename suffix or in-file `user_id` column
- Idempotent append into a local persistent store (SQLite for v1)
- Compute row-level diffs between consecutive snapshots per (`user_id`,
  `account_number`, `symbol`) — added / removed / mutated
- Query API: "give me the snapshot as of date D" / "diff between D1 and D2"
- CLI: `pi import <folder>` / `pi as-of <date>` / `pi diff <date-1> <date-2>`
- Bad-row tolerance: mis-aligned columns or footer/disclaimer noise gets
  logged-and-skipped, never crashes the import

---

## 0.5. Where this fits in the ecosystem — COMPLEMENTARY, not overriding

This importer is a **thin, standalone ingestor** whose only job is to turn a
folder of Fidelity CSV snapshots into a queryable point-in-time store. It
plugs into a **rich, pre-existing** portfolio ecosystem and MUST NOT
duplicate or override any of it:

| Existing artifact | What it owns | How this importer relates |
|---|---|---|
| [`openbb_platform/tools/portfolio_export/`](../../../openbb_platform/tools/portfolio_export/) | Deterministic Playwright-based **producer** of `Portfolio_Positions_*.csv` files from live broker sessions (Fidelity today). Handles login/MFA persistence, downloads to `~/portfolio_exports/`, tags with `user_id` via `pe tag`. | **Upstream producer.** Importer consumes exactly the CSV shape this tool emits. Reuses `portfolio_export.loaders.fidelity.load_positions` verbatim — no re-parse. |
| [`portfolio_app/`](../../../portfolio_app/) | Standalone FastAPI service on :6903 that reads the **canonical MySQL `Portfolio_Positions` table** (populated by the corporate pipeline, not our CSVs). Serves widgets to OpenBB Workspace. Requires MySQL credentials, is a live data path. | **Parallel, not replaced.** MySQL `Portfolio_Positions` is the source of truth for on-network users. This importer builds a **local SQLite mirror** for offline / personal-CSV / air-gapped use cases and for learning/paper flows where the user doesn't have MySQL access. Same conceptual schema (positions with account/symbol/quantity/basis/value); different storage engine + append-only-with-full-history semantics. **Never writes to MySQL.** |
| [`docs/Specs/Portfolio-Intelligence-Engine-PRD.md`](../../Specs/Portfolio-Intelligence-Engine-PRD.md) (main PI PRD) | The umbrella program: `openbb-portfolio-intel` extension providing X-Ray, event calendar, smart-money overlay, risk/attribution, rebalancing, alerting, widget surface. Consumes `portfolio_basket` (the sanitized MySQL view). | **This importer is a NEW backing store option** for `portfolio_basket`-style queries when MySQL isn't available. The PI extension's read path can be extended (post-v1, tracked as [Q5] in §13) to accept a `PortfolioStore` implementation backed by SQLite alongside its existing MySQL path — but that wiring is out of scope for THIS PRD. |
| [`docs/designs/quant_trading/78-paperbroker-fill-sim.md`](../../designs/quant_trading/78-paperbroker-fill-sim.md) (paper-broker) | `PaperBroker` implementation of `BrokerInterface`: next-bar-open fill, slippage/commission, no-look-ahead golden test. Lives in `openbb-techtrade`. Simulates order execution. | **Peer, not replaced.** The paper-broker simulates **forward trading**; this importer records **historical snapshots**. They intersect only if you want to reconcile "what my paper account said I held on date D" (paper-broker state) vs "what my real broker CSV said I held on date D" (importer store). That reconciliation is a downstream *analysis* feature, not this importer's job. **This importer is purely read-only from broker CSVs — it does NOT simulate any trading.** |
| [`docs/Specs/Portfolio-Intelligence-Engine-Execution-Plan.md`](../../Specs/Portfolio-Intelligence-Engine-Execution-Plan.md) | The PI program's phased execution plan (roadmap). | Importer will be added as one bullet on the plan under "Data ingest options" once approved — does not restructure the plan. |

**Governing principle for this PRD:** if a capability lives elsewhere in
the ecosystem, this importer **does not implement it**. This importer's
job ends when a folder of CSVs is faithfully represented as an append-only
positions store. Everything else — analytics, paper trading, order
simulation, MySQL sync, widget rendering — is a downstream consumer or a
peer artifact.

---

## 1. Primary user flow (the L1 happy path)

```
$ pi import ~/portfolio_exports/
Scanned 12 CSVs under ~/portfolio_exports/
  ✓ 2026-07-18  prajoria  Portfolio_Positions_Jul-18-2026_prajoria.csv  (23 rows)
  ✓ 2026-07-18  rashmi    Portfolio_Positions_Jul-18-2026_rashmi.csv   (17 rows)
  ✓ 2026-07-11  prajoria  Portfolio_Positions_Jul-11-2026_prajoria.csv (22 rows)
  ⚠ 2026-07-11  rashmi    Portfolio_Positions_Jul-11-2026_rashmi.csv  (16 rows, 1 skipped: footer)
  ↻ 2026-07-04  prajoria  Portfolio_Positions_Jul-04-2026_prajoria.csv (already imported, skipped)
  ...
Imported 4 new snapshots, 156 position rows. 1 CSV skipped (duplicate content
digest). 3 rows skipped (bad shape or non-position footer).

$ pi as-of 2026-07-11 --user prajoria
Account X99999999 (Individual - TOD)
  XYZ  1.234 sh  @ $12.34  ($99.99 mkt / $88.88 cost)
  ABC  10.00 sh  @ $45.67  ...
  ...
17 positions, $XX,XXX market value, $YY,YYY cost basis.

$ pi diff 2026-07-04 2026-07-18 --user prajoria
Between 2026-07-04 → 2026-07-18 (2 snapshots apart):
  + Added:    2 symbols  (XYZ, ABC)
  - Removed:  1 symbol   (DEF)
  Δ Mutated:  8 symbols  (quantity or cost-basis change)
  = Held:    12 symbols  (no change)
```

**Success criterion:** on a folder of ~20 CSVs across 6 months and 2 users,
`pi import` runs in <5s, is idempotent (second run = zero new imports), and
`pi as-of` reconstructs the full holdings snapshot with dtypes that match
`fidelity.load_positions`.

---

## 2. Where the code lands

Two artifacts, in the sibling relationship the existing repo already models
(`portfolio_export` = deterministic CSV producer; new `portfolio-importer` =
deterministic CSV consumer):

```
OpenBB/
├── portfolio_export/                  # existing — records + downloads CSVs
│   └── portfolio_export/
│       └── loaders/fidelity.py        # ★ reused verbatim
│
└── portfolio-importer/                # NEW — this PRD
    ├── README.md
    ├── pyproject.toml
    ├── pi-import.ps1                  # convenience wrapper (mirror pe-record.ps1)
    ├── portfolio_importer/
    │   ├── __init__.py
    │   ├── __main__.py                # python -m portfolio_importer
    │   ├── cli.py                     # click-based `pi` CLI
    │   ├── config.py                  # env-var driven paths (mirror pe config)
    │   ├── filename.py                # NEW — Fidelity filename → (date, user_id)
    │   ├── ingest.py                  # scan folder → dedupe → append to store
    │   ├── store.py                   # SQLite schema + upsert + query
    │   ├── diff.py                    # per-position diff between two snapshots
    │   └── query.py                   # as-of, timeline, per-symbol history
    └── tests/
        ├── conftest.py                # tmp SQLite fixture + fake-CSV factory
        ├── fixtures/                  # ★ hand-authored fudged CSVs only, no real data
        │   ├── snapshot_a.csv
        │   ├── snapshot_b_added_and_mutated.csv
        │   ├── snapshot_c_removed.csv
        │   ├── malformed_trailing_comma.csv
        │   ├── malformed_short_row.csv
        │   └── multi_user_same_date.csv
        └── unit/
            ├── test_filename.py
            ├── test_ingest_idempotence.py
            ├── test_ingest_bad_rows.py
            ├── test_store_schema.py
            ├── test_diff.py
            └── test_query_as_of.py
```

**Why a separate package, not inside `portfolio_export` or
`openbb_platform/extensions/portfolio_intel`:**

- **Vs. `portfolio_export`:** the export tool depends on Playwright + Chromium
  (~500 MB). The importer needs neither. Keeping them separate means the
  importer installs in seconds and can run in headless CI, on a laptop
  without a browser profile, or on a server.
- **Vs. `openbb_platform/extensions/portfolio_intel`:** the OpenBB extension
  is where portfolio *analytics* live (returns, attribution, risk). The
  importer is a **data ingest** step that populates a persistent store the
  extension can then read from. Keeping the ingest out of the extension
  means the extension has no filesystem-side effects, no CSV parsing surface
  in its public API, and no coupling to Fidelity's filename convention.

If the OpenBB extension ever needs to *read* the store, it imports
`portfolio_importer.query.PortfolioStore` and reads. It never writes.

---

## 3. Store schema — append-only positions with full history

Single SQLite database, default path `~/.portfolio_importer/positions.db`
(mirrors `~/.portfolio_export/chrome_profile/` — user-local, never in the
repo). Two logical tables:

### 3.1 `snapshot` — one row per (user, snapshot_date, source file)

```sql
CREATE TABLE snapshot (
    snapshot_id       TEXT PRIMARY KEY,      -- BLAKE2b hex of file content + user_id
    snapshot_date     DATE NOT NULL,         -- parsed from filename
    user_id           TEXT NOT NULL,         -- from filename or in-file column
    source_filename   TEXT NOT NULL,         -- original CSV filename (not full path — PII)
    source_sha256     TEXT NOT NULL,         -- content hash for idempotence
    imported_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    row_count_raw     INTEGER NOT NULL,      -- rows in CSV
    row_count_kept    INTEGER NOT NULL,      -- rows that landed as positions
    row_count_skipped INTEGER NOT NULL,      -- rows dropped (malformed, footer, etc.)
    schema_version    INTEGER NOT NULL       -- bump when position table shape changes
);
CREATE UNIQUE INDEX ux_snapshot_content ON snapshot(source_sha256, user_id);
CREATE INDEX ix_snapshot_date_user ON snapshot(snapshot_date, user_id);
```

**Idempotence key:** `(source_sha256, user_id)`. Re-importing the same file
is a no-op. If the same broker file is downloaded twice at different
timestamps but content is identical → single snapshot row.

### 3.2 `position` — one row per (snapshot, account, symbol)

```sql
CREATE TABLE position (
    position_id                 INTEGER PRIMARY KEY,
    snapshot_id                 TEXT NOT NULL REFERENCES snapshot(snapshot_id),
    snapshot_date               DATE NOT NULL,               -- denormalized for fast filters
    user_id                     TEXT NOT NULL,               -- denormalized
    account_number              TEXT NOT NULL,
    account_name                TEXT,
    basket_name                 TEXT,
    symbol                      TEXT NOT NULL,               -- e.g. XYZ, SPAXX (money-market)
    description                 TEXT,
    type                        TEXT,                        -- Cash / Margin / etc.
    quantity                    REAL,                        -- may be fractional
    last_price                  REAL,
    last_price_change           REAL,
    current_value               REAL,
    today_gain_loss_dollar      REAL,
    today_gain_loss_percent     REAL,
    total_gain_loss_dollar      REAL,
    total_gain_loss_percent     REAL,
    percent_of_account          REAL,
    cost_basis_total            REAL,
    average_cost_basis          REAL,
    raw_row_number              INTEGER NOT NULL,            -- source CSV row for audit
    FOREIGN KEY (snapshot_id) REFERENCES snapshot(snapshot_id)
);
CREATE INDEX ix_position_snapshot ON position(snapshot_id);
CREATE INDEX ix_position_date_user_symbol ON position(snapshot_date, user_id, symbol);
CREATE INDEX ix_position_date_user_account ON position(snapshot_date, user_id, account_number);
```

**Append-only guarantee:** no `UPDATE` or `DELETE` on `position` or `snapshot`
in the write path. Correction = **new snapshot on a new date** (or, if the
same-date CSV is genuinely republished with corrections, a new
`source_sha256` produces a new snapshot row and the old one stays as
historical audit).

**Denormalized `snapshot_date` and `user_id` on `position`:** deliberate.
Every query filters on date and user; joining `snapshot` for every read is
wasted work. Storage cost is negligible.

### 3.3 What we do NOT store

- **Full file path** — filename only. Absolute paths leak home-dir usernames.
- **Import timestamps of individual rows** — only per-snapshot `imported_at`.
- **Raw CSV text** — parsed values only. The content hash lets us prove
  which file produced a snapshot; we don't need to keep the text.

---

## 4. Filename parser

Fidelity's convention: `Portfolio_Positions_<Mon>-<DD>-<YYYY>_<user_id>.csv`.

The existing `portfolio_export/discover.py:_TAGGED_SUFFIX_RE` extracts
`user_id`; we add the date parse:

```python
# portfolio_importer/filename.py

_FIDELITY_RE = re.compile(
    r"^Portfolio_Positions_(?P<mon>[A-Za-z]{3})-(?P<dd>\d{2})-(?P<yyyy>\d{4})"
    r"(?:_(?P<user_id>[A-Za-z0-9_.-]{1,64}))?"
    r"\.csv$"
)

def parse_fidelity_filename(name: str) -> tuple[date, str | None]:
    """(date, user_id) or raise FilenameParseError."""
```

**Failure mode:** anything the regex doesn't match gets logged as
`skipped: unrecognized_filename` and left on disk untouched. No guessing,
no fuzzy match — deterministic like the sibling `portfolio_export`.

**Extension point:** a `LOADERS` registry maps `(regex → loader_module)` so
Schwab, Vanguard, IBKR can be added later without touching the ingest core.
v1 ships Fidelity only.

---

## 5. Ingest algorithm

```python
def import_folder(folder: Path, *, store: PortfolioStore) -> IngestReport:
    """Scan folder for CSVs, parse each, upsert idempotently. Never mutates."""

    for path in sorted(folder.rglob("Portfolio_Positions_*.csv")):
        try:
            snap_date, user_id = parse_fidelity_filename(path.name)
        except FilenameParseError as e:
            report.skip(path, reason="unrecognized_filename", detail=str(e))
            continue

        sha = _sha256_of_file(path)
        if store.snapshot_exists(source_sha256=sha, user_id=user_id):
            report.skip(path, reason="duplicate_content")
            continue

        try:
            df = fidelity.load_positions(path)          # ★ REUSE, no re-parse
        except Exception as e:
            report.skip(path, reason="parse_failed", detail=str(e))
            continue

        # Bad-row filter: fidelity.load_positions already drops the
        # trailing-comma + footer rows. This is a second belt-and-suspenders
        # check for anything the loader missed (unexpected NaN symbol, etc.).
        kept, skipped_rows = _filter_position_rows(df)

        with store.tx() as tx:
            snapshot_id = tx.insert_snapshot(
                snapshot_date=snap_date,
                user_id=user_id,
                source_filename=path.name,
                source_sha256=sha,
                row_count_raw=len(df),
                row_count_kept=len(kept),
                row_count_skipped=len(skipped_rows),
            )
            tx.insert_positions(snapshot_id, kept)

        report.ingested(path, snapshot_id, kept_count=len(kept),
                        skipped_count=len(skipped_rows))

    return report
```

**Bad-row filter rules** (`_filter_position_rows`):

- Drop rows where `symbol` is null/empty (`fidelity.load_positions` already
  handles trailing-comma noise, but a footer line like `"Brokerage services
  provided by..."` produces a row with everything null)
- Drop rows where `account_number` doesn't match `^[A-Za-z0-9]{6,}$` (uses
  the sibling's `_ACCOUNT_CELL_RE`)
- Drop rows where `quantity`, `current_value`, and `cost_basis_total` are
  ALL null (nothing meaningful left)
- Log the skipped row's `raw_row_number` (not content — content might be PII)

---

## 6. Diff between snapshots

```python
def diff_snapshots(
    store: PortfolioStore,
    date_a: date,
    date_b: date,
    *,
    user_id: str,
) -> SnapshotDiff:
    """Positions present in b but not a, in a but not b, or changed."""
```

Diff key: `(account_number, symbol)`.

Returned buckets:

- **added**: `(account, symbol)` in B, not in A
- **removed**: in A, not in B
- **mutated**: in both, but any of {`quantity`, `cost_basis_total`,
  `average_cost_basis`} differ by more than a tolerance (default: exact
  equality on quantity + basis, `abs(a - b) / a > 0.001` for market values
  since prices drift daily)
- **unchanged**: in both, no material change

`current_value` / `last_price` / `today_gain_loss_*` change daily and are
excluded from the "mutated" definition by default (they'd flag every
position as mutated every day). Optional flag `--include-price-drift`
switches the diff to compare those too.

**Multi-account users:** the diff runs per user by default. `--per-account`
splits further. Cross-user diffs are not supported (each user's portfolio
is its own entity).

---

## 7. CLI surface

```
pi import <folder> [--recursive/--no-recursive] [--dry-run] [--json]
pi list-snapshots [--user <id>] [--from <date>] [--to <date>]
pi as-of <date> [--user <id>] [--account <acct>] [--json]
pi diff <date-a> <date-b> [--user <id>] [--per-account] [--include-price-drift] [--json]
pi timeline <symbol> [--user <id>] [--json]        -- symbol's quantity/basis over time
pi purge --user <id> --confirm                     -- delete all of one user's data
```

**Never destructive without `--confirm`.** `pi purge` is the only path
that deletes. Idempotent import handles the "I accidentally imported the
same folder twice" case without needing purge.

**JSON output for every command** so a downstream OpenBB extension /
notebook can consume the results without re-parsing text.

---

## 8. Reused vs. new

| Component | Source | Reuse strategy |
|---|---|---|
| Fidelity CSV parsing (money/percent/dtype handling) | `portfolio_export.loaders.fidelity.load_positions` | Verbatim import; do not fork |
| `user_id` from filename suffix | `portfolio_export.discover._TAGGED_SUFFIX_RE` | Verbatim import |
| Account-number sanity regex | `portfolio_export.loaders.fidelity._ACCOUNT_CELL_RE` | Verbatim import |
| Path-outside-repo validation | `portfolio_export.config` pattern | Copy the pattern (not the code) |
| Env-var config for paths | `portfolio_export.config` | Same pattern, different env vars (`PI_STORE_PATH`, `PI_IMPORT_DIR`) |
| Filename → date parse | **NEW** | `filename.py` module |
| SQLite schema + upsert | **NEW** | `store.py` module (no ORM, plain `sqlite3` — small, zero-dep) |
| Diff logic | **NEW** | `diff.py` |
| Snapshot as-of query | **NEW** | `query.py` (single-JOIN SQL, no ORM) |
| CLI | **NEW** | `cli.py` (`click`, mirrors `pe` CLI style) |

**Total NEW code estimate:** ~600 LoC across 6 small modules + ~400 LoC of
tests. Should ship in one modest feature-branch PR.

---

## 9. Bad-row / bad-file handling

Every failure mode is logged (`ingest_report.jsonl` alongside the store) and
either:

- **Skipped, with reason** (row-level: `unrecognized_filename`,
  `duplicate_content`, `parse_failed`, `empty_after_filter`, `bad_shape`) —
  ingest continues to the next file
- **Fatal only for**: store-write errors (disk full, permission denied,
  DB locked). The importer exits non-zero with the error, no partial state
  committed (single transaction per file).

**Never crashes on user data.** The import of 20 CSVs where one is truncated
succeeds for 19 and reports the failing one.

**Bad rows within a good CSV:**

- Truncated row (fewer cells than header) → skip row, log
  `row=N, reason=short_row`
- Extra-cell row (Fidelity's stray trailing comma) → the sibling loader
  already handles this — verify with a fixture
- Non-numeric in a numeric column → skip row, log `row=N,
  reason=bad_numeric, col=<name>`
- Empty `symbol` after cleanup → skip row silently (it's a footer)

---

## 10. Testing strategy — per CLAUDE.md R7 rules

Every load-bearing function gets **realistic-shape fixtures** (R7.1) via
**fudged synthetic CSVs I author by hand**, NOT snapshots of real
portfolios. Fixture directory: `tests/fixtures/`. Values are made up;
column order and dtypes mirror the real Fidelity export shape.

- **R7.3 loud empties:** ingest emits WARNING logs when a whole file has
  zero kept rows. A silently-zero import is treated as an anomaly, not a
  success.
- **R7.7 reverse-verification:** each regression test (e.g.
  `test_ingest_ignores_footer_disclaimer`) is written such that removing
  the footer filter causes the test to fail. Verified at author-time via
  mutation.
- **R7.11 ceremonial-test check:** for the "duplicate CSV is a no-op" test,
  mutate the idempotence guard to always return `False`, confirm the test
  turns red (i.e. imports twice), restore the guard.

**Integration test:** `test_full_folder_roundtrip.py` runs the whole
`pi import` → `pi as-of` → `pi diff` flow against 6 hand-authored CSVs
spanning 3 dates and 2 users. Asserts row counts, diff buckets, and
`as-of` output shape.

**No integration test hits real broker data or real user files.**

---

## 11. Security / privacy defaults

- **Paths outside the repo, always.** Mirror the `portfolio_export` guard:
  store path, import folder, and log path are all validated to resolve
  OUTSIDE the git repo before any write.
- **`~/.portfolio_importer/` gitignored** (and any dev-set `PI_STORE_PATH`
  candidate is checked against the repo root).
- **No content logging.** The importer logs `row_number` and `column_name`
  on parse failures, never the cell value. A row like
  `"John Smith,SSN123-45-6789"` in a bad file would leak PII to logs — so
  we simply don't log the value.
- **Filename-only in the store.** Absolute paths often contain OS
  usernames.
- **Content hash, not content, for dedup.** SHA-256 of file bytes.
- **User-scoped queries by default.** `pi as-of` without `--user` errors
  out with "specify --user or --all"; forcing an explicit choice prevents
  accidental cross-user mixing.

---

## 12. Non-goals (repeat, for absolute clarity)

Every capability listed here **already exists** or **is planned** in a peer
artifact. This PRD does not override or duplicate them; it complements.

- ❌ Not a paper-trading simulator — see [`docs/designs/quant_trading/78-paperbroker-fill-sim.md`](../../designs/quant_trading/78-paperbroker-fill-sim.md) (`PaperBroker` in `openbb-techtrade`)
- ❌ Not a broker API client / order-execution engine — same `BrokerInterface` Protocol future-`LiveBroker` will implement
- ❌ No portfolio *analytics* (returns, Sharpe, factor loadings, X-Ray look-through, event calendar, smart-money, risk/attribution, rebalancing, alerting) — see [`docs/Specs/Portfolio-Intelligence-Engine-PRD.md`](../../Specs/Portfolio-Intelligence-Engine-PRD.md) (`openbb-portfolio-intel` extension)
- ❌ No CSV *editing* / correction workflow (append-only; corrections = new-dated snapshots)
- ❌ No performance charts / UI (CLI + SQLite for v1; the OpenBB extension or a notebook wraps it later)
- ❌ No cloud sync / multi-machine sharing (local SQLite; back it up yourself)
- ❌ No writes to the corporate MySQL `Portfolio_Positions` table — that pipeline is untouched; this store is a parallel local mirror
- ❌ No competition with `portfolio_app/` — that service serves widgets from MySQL for on-network users; this importer serves the same shape from SQLite for offline / personal-CSV users

---

## 13. Open questions (need your call before implementation)

Numbered so we can resolve in order. Nothing in the PRD blocks on this
list until we get to implementation — but each `[Q]` marks a decision I
need before writing code.

1. **[Q1] Store engine.** SQLite (recommended) vs. plain Parquet files
   per snapshot vs. DuckDB. SQLite is portable, zero-dep, and good for
   millions of rows. DuckDB is faster for analytical queries but adds a
   dep. Parquet-per-snapshot is simplest but every query re-scans all
   files.
2. **[Q2] Snapshot-id scheme.** BLAKE2b(file_bytes) alone, or
   BLAKE2b(file_bytes + user_id)? Same file tagged for two users would
   produce two snapshots either way (because `user_id` is a separate
   column); but a single content hash makes cross-user dedup simpler if
   you ever share portfolios. Recommend `sha256(file_bytes)` +
   `user_id` as a compound uniqueness key on the snapshot table.
3. **[Q3] Date extraction fallback.** If a filename doesn't match the
   Fidelity pattern (e.g. renamed to `july18.csv`), do we (a) skip, (b)
   read filesystem mtime, (c) look inside the CSV for an "As of" line?
   Recommend (a) — strict, deterministic, matches `portfolio_export`
   philosophy. Extension point: user can rename to Fidelity convention
   before re-running.
4. **[Q4] Cross-broker support in v1?** Recommend Fidelity-only for v1
   (matches the CSVs you actually have). Add a `loader_id` column to
   `snapshot` now so we can add Schwab/Vanguard/IBKR later without a
   migration.
5. **[Q5] OpenBB extension exposure.** Does v1 add a read-only OpenBB
   Platform command (`obb.portfolio_intel.as_of(...)`) that reads the
   importer's store? Recommend NO for v1 — ship the CLI + Python API
   first. The main PI PRD's read path currently binds to `portfolio_basket`
   (MySQL); adding a `PortfolioStore` abstraction that can be backed by
   EITHER MySQL or this SQLite store is a **follow-up** tracked separately
   (would touch the PI PRD, not this one). This importer stays a
   standalone data producer for v1.
6. **[Q6] Reconciliation with paper-broker state (out of scope, but noted).**
   Some day it might be useful to diff "what `PaperBroker.positions()` says
   I hold on date D" vs "what the broker CSV snapshot for date D says I
   hold". That's a reconciliation *feature* — belongs in a downstream
   analytics module (probably `openbb-portfolio-intel`), NOT in this
   importer. Flagging here so we don't scope-creep the importer.

---

## 14. Deliverables + timeline (rough)

| Step | Deliverable | Est. effort |
|---|---|---|
| 1 | This spec, approved | done pending your ack |
| 2 | Feature branch cut from `portfolio` | 5 min |
| 3 | `filename.py` + tests | 1 h |
| 4 | `store.py` + schema + tests | 3 h |
| 5 | `ingest.py` (reuse fidelity loader) + tests | 2 h |
| 6 | `diff.py` + tests | 2 h |
| 7 | `query.py` (as-of, timeline) + tests | 1.5 h |
| 8 | `cli.py` + integration test | 2 h |
| 9 | README + `pi-import.ps1` wrapper | 30 min |
| 10 | Local `/verify` on your real CSV folder (you drive, I read only logs — never row contents) | 20 min |
| 11 | Local review (coderabbit + pr-review-toolkit) + push + PR to `portfolio` | 30 min |
| **Total** | | ~12 h |

---

## 15. What Claude will NOT do

- Will NOT read the contents of any CSV file you point us at during design
  or implementation (only headers via `pd.read_csv(nrows=0)` and Python
  tool introspection).
- Will NOT execute `pi as-of` / `pi diff` against your real data — you run
  those; I read stdout summaries you paste.
- Will NOT commit the SQLite database or any log file that might contain
  filenames from your real portfolio (gitignore covers this).
- Will NOT open a PR from `portfolio` → `develop` (that's your final call,
  per Portfolio Intelligence Engine workflow in `CLAUDE.md`).

---

## Sign-off

- [ ] Reviewer: @prajoria
- [ ] Approved to move to implementation plan (`docs/superpowers/plans/2026-07-18-portfolio-snapshot-importer-plan.md`)
- [ ] Any of the 5 [Q1]–[Q5] open questions answered inline before plan drafting
