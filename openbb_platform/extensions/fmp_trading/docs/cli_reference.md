# openbb-daytrade CLI reference

Every subcommand of the `openbb-daytrade` CLI entry point.

## `openbb-daytrade doctor`

**Purpose:** health-check the environment — FMP credentials, MySQL cache
reachability, exchange_calendars data, techtrade version, extras, and
remaining bandwidth budget.

**Options:** none.

**Exit codes:**
- `0` — all checks passed
- `1` — at least one error printed

**Example:**
```bash
$ openbb-daytrade doctor
openbb-daytrade doctor
========================================
  FMP credentials       : OK
  fmp_cached MySQL      : OK
  exchange_calendars    : OK
  openbb-techtrade      : 0.1.0 (OK)
  [agent] extra         : installed
  [xlsxwriter] extra    : absent
  [validation] extra    : absent
  Bandwidth remaining   : 87.3%
```

---

## `openbb-daytrade mcp-serve`

**Purpose:** start the stdio MCP server (Phase 3 P3.3 / GH #85).

Exposes the read-only union of `PRE_OPEN_TOOLS` and `POST_CLOSE_TOOLS`
(with `submit_*` sinks filtered per PRD §7.3) to external MCP clients
like Claude Desktop or VS Code MCP.

**Requires:** the `[agent]` extra. Emits a friendly install-hint if
missing rather than an ImportError stack trace.

**Options:** none.

**Exit codes:**
- `0` — clean shutdown (KeyboardInterrupt)
- `1` — `[agent]` extra missing
- `2` — startup drift check failed (tool schemas out of sync with router)
- `3` — mcp SDK not importable despite extra check passing

---

## `openbb-daytrade report`

**Purpose:** render session artifacts as Markdown + Excel + JSON (P5.1
+ P5.2, PRD §4.6).

**Options:**

| Flag | Type | Default | Purpose |
|---|---|---|---|
| `--session` | str | required | Session id (e.g. `s20260713143025`) |
| `--format` | md/xlsx/json/all | `all` | Which formats to emit |
| `--output-dir` | path | `<jail>/daytrade_<date>/` | Target directory (must be inside `FMP_TRADING_REPORTS_ROOT` jail) |
| `--no-agent-narrative` | flag | off | Force the deterministic Jinja narrator even if the journal has an LLM briefing |
| `--overwrite` | flag | off | Overwrite existing report files (default: refuse with error) |

**Security posture:**
- `output_dir` is JAILED under `FMP_TRADING_REPORTS_ROOT` (default
  `Analysis/exports/`). Paths outside the jail are rejected.
- Overwrites REQUIRE the explicit `--overwrite` flag. Default is
  refuse-with-error so an operator can't clobber yesterday's report by
  accident.
- Symlinks in the target path are refused — no writing through
  symlinks that escape the jail.

**Exit codes:**
- `0` — report written successfully
- `2` — target file exists (pass `--overwrite`)
- `3` — output path outside jail (widen `FMP_TRADING_REPORTS_ROOT`)
- `4` — journal not found for session
- `5` — invalid session id (path-traversal guard)

**Example:**
```bash
$ openbb-daytrade report --session s20260713143025 --format all
openbb-daytrade report
========================================
  Session       : s20260713143025
  Session date  : 2026-07-13
  Events read   : 4736
  Agent backend : claude
  MD            : Analysis/exports/daytrade_2026-07-13/end_of_day.md
  JSON          : Analysis/exports/daytrade_2026-07-13/manifest.json
  XLSX          : Analysis/exports/daytrade_2026-07-13/end_of_day.xlsx
```

---

## `openbb-daytrade replay`

**Purpose:** deterministic journal reconstruction (P5.3 / PRD §4.1).
Drives a fresh `IntradaySession` through recorded ticks via a
`StubbedDataProvider`, comparing emitted vs recorded events per tick.

**Options:**

| Flag | Type | Default | Purpose |
|---|---|---|---|
| `--session` | str | required | Session id (path resolved via traversal-safe helper) |
| `--from-tick` | int | `0` | 0-based tick index to start from |
| `--to-tick` | int | `None` | 0-based tick index to stop before (None = all) |
| `--no-raise` | flag | off | Report divergences via `diverged_at_tick` instead of raising (useful for divergence-diff tooling) |

**Exit codes:**
- `0` — replayed cleanly (no divergence)
- `4` — journal file not found
- `5` — invalid session id (path-traversal guard)
- `6` — divergence detected (details on stderr)

**Example:**
```bash
$ openbb-daytrade replay --session s20260713143025
openbb-daytrade replay
========================================
  Session          : s20260713143025
  Session date     : 2026-07-13
  Events replayed  : 4736
  Plan watchlist   : ['MSFT', 'AAPL', 'NVDA']
  Plan preset      : intraday_momentum
  Diverged at tick : (no divergence)
```

**On divergence:**
```bash
$ openbb-daytrade replay --session s20260713143025
DIVERGENCE at tick 42
  event_type: fill
  field     : payload.fill_price
  expected  : '430.05'
  actual    : '440.05'
```

---

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `FMP_TRADING_REPORTS_ROOT` | Jail root for `report()` output | `Analysis/exports/` |
| `ANTHROPIC_API_KEY` | Required for `[agent]` extra's Claude backend | — |
| `PYTHONIOENCODING` | Set to `utf-8` on Windows to avoid cp1252 encoding errors on Unicode output | — |
