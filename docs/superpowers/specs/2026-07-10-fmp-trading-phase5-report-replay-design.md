# fmp-trading Phase 5 — `report()` + `replay()` (design spec)

**Date:** 2026-07-10
**Author:** fmp-trading working group
**Status:** Draft — for user approval before Phase 5 planning
**Scope:** Design gate for the openbb-dev-cycle skill's Phase 1 (Design & Brainstorming). Turns PRD §4.6 + §10 P5.1/P5.2/P5.3/P5.4 into concrete implementation decisions. **Depends on** Phase 0-3 (PR #448, currently open against `develop`).

**Closes on Phase 5 completion:**
- No individual GitHub issues in-scope beyond the fmp-trading epic. Phase 5 is polish + deliverables; success = "operator can hand the tool to a colleague and they can inspect + replay a session end-to-end."

---

## 1. Goal

Give the operator two post-session tools:

1. **`obb.fmp_trading.report(session_id, format="all")`** — renders the deterministic session artifacts (Markdown briefing + Excel workbook + JSON manifest) into an output directory. MD reuses `PostCloseAgentTurn`'s narrator template if the agent didn't already write it. XLSX reuses `openbb-techtrade.reporting.export` for the base 6-sheet workbook and adds 2-3 intraday-specific sheets.
2. **`obb.fmp_trading.replay(journal_path, from_tick, to_tick)`** — deterministically re-runs an on-disk NDJSON journal through a fresh `IntradaySession` + stubbed data providers, verifying the produced event stream matches the recorded one byte-for-byte (per event, in order). This is what proves "everything except `BandwidthState` is reconstructible from the journal" (PRD §8.7).

Plus polish:

3. **README + `openbb-daytrade` CLI docs + config examples** — the deliverable a new operator picks up first.

**Non-goals** (deferred to later phases per PRD §10):
- Live-integration validation against real fmp_cached (Phase 6).
- Backtest bridge (Phase 6, `[validation]` extra).
- AlertManager v1 (Phase 4 — deferred).
- MySQL-backed journals (see D1 below — disk-only for now).

---

## 2. User-locked foundational decisions

Recorded from the brainstorming gate (2026-07-10):

| # | Decision | Rationale |
|---|---|---|
| **D1** | **Journal source for `replay()`:** on-disk NDJSON files, one per session at `~/.openbb_platform/fmp_trading/journals/<session_id>.ndjson`. No MySQL for journals in Phase 5. | Matches the P3.2 `PostCloseAgentTurn` path that already reads via `openbb_core_journal.replay()`. Ships the operator-visible feature in ~1 day. MySQL-backed journals would 3x the work + belong in a dedicated persistence bead. |
| **D2** | **`report()` scope:** all four formats — `md`, `xlsx`, `json`, `all` — matching PRD §4.6 verbatim. | Half-shipping (MD-only) leaves the PRD signature partially implemented and defers the reviewer-visible payoff. Full scope is ~4 days and closes the "operator can hand this to a colleague" acceptance bar. |

Implicit / carried from prior phases:

| # | Decision (inherited) | From |
|---|---|---|
| **inh-1** | `Decimal` everywhere for money. | PRD P2 |
| **inh-2** | `openbb_core_journal.replay()` is the sole journal-read primitive. | Phase 1 P1.4 (J3) |
| **inh-3** | `openbb-techtrade[xlsxwriter]` reused for the base workbook; new intraday sheets bolted on. | PRD §4.6 + NG3 |
| **inh-4** | Output directory default: `Analysis/exports/daytrade_<date>/`. | PRD §4.6 |

---

## 3. Architecture

```
┌──────────────────────── obb.fmp_trading.replay ────────────────────────┐
│  replay(journal_path, from_tick=0, to_tick=None) → SessionResult       │
│    1. JournalReader reads NDJSON events in order                       │
│    2. Fresh IntradaySession + StubbedDataProvider (feeds recorded      │
│       quotes/bars back)                                                │
│    3. run_tick() called with the same tick_ts sequence                 │
│    4. Emitted events compared to recorded events                       │
│    5. Divergence -> ReplayDivergenceError with (tick_index, field)     │
│    6. Match -> SessionResult (identical shape to the original run)     │
└────────────────────────────────────────────────────────────────────────┘

┌──────────────────────── obb.fmp_trading.report ────────────────────────┐
│  report(session_id, format="all", output_dir=None,                     │
│         include_agent_narrative=True) → ReportManifest                 │
│    1. Load the journal for session_id (same reader as replay)          │
│    2. Compute SessionMetrics from replayed events (reuses P3.2 helper) │
│    3. If format in {md, all}: render end_of_day.md                     │
│         - if include_agent_narrative and EndOfDayReportEvent found:    │
│           extract briefing_md, write verbatim                          │
│         - else: run the deterministic Jinja narrator (same template    │
│           as P3.2 fallback path)                                       │
│    4. If format in {xlsx, all}: build a Workbook                       │
│         - reuse techtrade.reporting.excel_export.export()              │
│         - add 3 intraday sheets: Fills, Vetoes, PerSymbolPnL           │
│    5. If format in {json, all}: dump the full journal + summary as     │
│       structured manifest.json                                         │
│    6. Return ReportManifest with paths + provenance metadata           │
└────────────────────────────────────────────────────────────────────────┘
```

### Module layout

New files (all under `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/`):

```
reporting/
├── __init__.py                            # Extra-safe re-exports
├── journal_reader.py                      # session_id -> event iterator (disk)
├── report.py                              # report() router + ReportManifest logic
├── replay.py                              # replay() router + StubbedDataProvider
├── md_builder.py                          # deterministic MD template (P5.1)
├── xlsx_builder.py                        # techtrade export + intraday sheets (P5.2)
├── json_builder.py                        # manifest.json dump (P5.1)
└── templates/
    └── end_of_day.md.j2                   # deterministic MD template

routers/
└── report_router.py                       # obb.fmp_trading.{report,replay} bindings

tests/
├── unit/
│   ├── test_journal_reader.py
│   ├── test_md_builder.py                 # AC-P5-1
│   ├── test_xlsx_builder.py               # AC-P5-2 (skip if [xlsxwriter] absent)
│   ├── test_json_builder.py               # AC-P5-3
│   ├── test_report_manifest.py            # AC-P5-4 (format=all round-trip)
│   └── test_replay_determinism.py         # AC-P5-5 (see §7)
├── integration/
│   └── test_replay_roundtrip.py           # AC-P5-6: real journal from AC-1-ext
└── golden/
    └── test_replay_no_divergence.py       # AC-P5-7: byte-for-byte replay
```

Existing files touched:

- `openbb_fmp_trading/models/results.py` — add `ReportManifest`, `SessionResult`, `ReplayDivergenceError` (small additions).
- `openbb_fmp_trading/fmp_trading_router.py` — wire the `report_router` in.
- `openbb_fmp_trading/cli/main.py` — add `report` + `replay` CLI subcommands.
- `openbb_fmp_trading/agent/post_close.py` — refactor `_compute_metrics_from_journal` into a shared helper the report path can also call (no duplication).

---

## 4. Component designs

### 4.1 `JournalReader` (`reporting/journal_reader.py`)

Thin wrapper around `openbb_core_journal.replay()` that adds session-id → path resolution.

```python
DEFAULT_JOURNAL_ROOT = Path.home() / ".openbb_platform" / "fmp_trading" / "journals"

def session_journal_path(session_id: str, root: Path | None = None) -> Path:
    """Resolve session_id -> `<root>/<session_id>.ndjson`."""

def read_session_events(session_id: str, root: Path | None = None) -> Iterable[JournalEvent]:
    """Yield every event in the session's journal, in write order.
    Wraps openbb_core_journal.replay() with disk-path resolution."""

def read_journal_file(path: Path) -> Iterable[JournalEvent]:
    """Same but takes an explicit path (used by replay(), which lets
    the operator point at any journal file, not just their own)."""
```

**Resilience:** missing file → `FileNotFoundError` propagates. Corrupt line → `JournalCorruption` exception (from `openbb_core_journal`) propagates. `report()` and `replay()` both fail loud on journal problems — silent zeros would be dangerous for post-mortem work.

### 4.2 `MDBuilder` (`reporting/md_builder.py`)

Two paths:

1. **Agent narrative** (default, when `EndOfDayReportEvent` is in the journal AND `include_agent_narrative=True`): extract `briefing_md` from the event's payload, write verbatim to `end_of_day.md`. This is what the operator wants when the LLM turn ran — the LLM's prose is more nuanced than the template.
2. **Deterministic template**: render `templates/end_of_day.md.j2` using `SessionMetrics` computed from the journal. Same template file as `PostCloseAgentTurn.templates/post_close_briefing.md.j2` — moving the shared template to `reporting/templates/` and having `post_close.py` reference it from there (small refactor).

**Shared metrics helper:** `_compute_metrics_from_journal(events)` moves from `agent/post_close.py` to `reporting/journal_reader.py` and both consumers import it. No behavior change.

### 4.3 `XLSXBuilder` (`reporting/xlsx_builder.py`)

```python
def build_workbook(
    session_id: str,
    events: list[JournalEvent],
    metrics: SessionMetrics,
    output_path: Path,
    engine: Literal["openpyxl", "xlsxwriter"] = "openpyxl",
) -> Path:
    """Build the 6+3 sheet end-of-day workbook."""
```

**Approach — reuse-then-augment:**

1. Call `openbb_techtrade.reporting.excel_export.export(...)` to get the 6-sheet base workbook (Recommendations, Trades, Signals, Metrics, Config, ReadMe — techtrade's contract).
2. Open the resulting workbook and add 3 intraday-specific sheets:
   - **`Fills`** — every FillEvent as a row: ts, symbol, side, qty, fill_price, commission, slippage.
   - **`Vetoes`** — every VetoEvent: ts, symbol, reason_code, gate, plan echo.
   - **`PerSymbolPnL`** — pivoted from Fills: symbol → realized_pnl, fill_count, win_rate.

Uses the openpyxl engine by default (core dep, no extra needed). `xlsxwriter` is a nice-to-have per techtrade's contract — same `engine` arg passed through.

**`[xlsxwriter]` extra guard:** the base techtrade export needs its dep; if the operator doesn't have techtrade installed at compatible version, `report(format="xlsx")` raises `XLSXUnavailable("install openbb-techtrade")`. `format="all"` degrades gracefully: still ships MD + JSON, journals a warning about the missing xlsx.

### 4.4 `JSONBuilder` (`reporting/json_builder.py`)

Dumps the full session as a machine-readable manifest:

```json
{
  "session_id": "s20260713",
  "date": "2026-07-13",
  "agent_backend": "claude",
  "metrics": {...},                     // SessionMetrics
  "daily_plan": {...},                  // DailyPlan reconstituted from event
  "end_of_day_report": {...} | null,    // EndOfDayReport if present
  "events": [                            // every journaled event in order
    {"event_type": "session_start", ...},
    ...
  ]
}
```

Purpose: downstream tooling (spreadsheets, notebooks, backtest bridges) that wants raw structured data. No prose interpretation.

### 4.5 `report()` router (`reporting/report.py`)

```python
def report(
    session_id: str,
    format: Literal["md", "xlsx", "json", "all"] = "all",
    output_dir: Path | None = None,
    include_agent_narrative: bool = True,
) -> OBBject[ReportManifest]:
```

- `output_dir` default: `Path("Analysis/exports/daytrade_" + session_date + "/")`, resolved from `session_id`'s date component.
- Creates `output_dir` if it doesn't exist. If any target file already exists, overwrites with a WARN log (idempotent regeneration is a feature — operators regenerate reports after fixing a template bug).
- Returns `ReportManifest` with `md_path` / `xlsx_path` / `json_path` (None for formats not requested), plus provenance metadata (`agent_backend`, `is_deterministic_narrative`, `session_events_count`).

### 4.6 `replay()` router (`reporting/replay.py`)

```python
def replay(
    journal_path: Path,
    from_tick: int = 0,
    to_tick: int | None = None,
) -> OBBject[SessionResult]:
```

**Determinism strategy — event-by-event replay:**

1. Read all events from the journal file into memory.
2. Extract the initial `SessionStartEvent` payload (date, watchlist, preset, agent_backend).
3. Reconstitute the `DailyPlan` from the `DailyPlanCommittedEvent` if present, else from `SessionStartEvent`.
4. Create a fresh `IntradaySession` with a `StubbedDataProvider` that returns recorded quotes/bars/session-status keyed by tick_ts.
5. Iterate through recorded `TickEvent`s (from index `from_tick` to `to_tick`), calling `run_tick(session, tick_ts)` for each.
6. Collect emitted events per tick and compare against the recorded events at the same tick position.
7. On mismatch: raise `ReplayDivergenceError(tick_index, field, expected, actual)`.
8. On match through the range: return `SessionResult` with the reconstructed metrics.

**What replay proves:**
- The tick loop is a pure function of `(session_state, tick_ts, market_data)`.
- No hidden state in module globals / closures.
- Any change to `_process_signal` chokepoint semantics fails replay on prior journals.

**What replay does NOT prove:**
- FMP data hasn't changed (the stub feeds recorded data, not live). This is a *reproducibility* proof, not a *live-behavior* proof.
- `BandwidthMeter` behavior (per PRD §8.7 — bandwidth is session-scoped ephemeral).

### 4.7 CLI subcommands (`cli/main.py`)

Two new subcommands following the P1.6 `doctor` + P3.3 `mcp-serve` pattern:

```bash
openbb-daytrade report --session s20260713 --format all [--output-dir path] [--no-agent-narrative]
openbb-daytrade replay --journal path/to/journal.ndjson [--from-tick 0] [--to-tick 100]
```

Both delegate to the router functions; CLI just handles argparse + prints the returned manifest / result.

---

## 5. Data models added

Two new pydantic models in `models/results.py` (small additions; the file already exists per PRD §6):

```python
class ReportManifest(Data):
    session_id: str
    session_date: date
    md_path: Path | None
    xlsx_path: Path | None
    json_path: Path | None
    included_agent_narrative: bool = Field(
        description="True if end_of_day.md was written verbatim from an "
                    "EndOfDayReportEvent's briefing_md; False if the "
                    "deterministic template ran."
    )
    session_events_count: int
    agent_backend: Literal["claude", "openai", "none"] | None
    warnings: list[str] = Field(default_factory=list)


class SessionResult(Data):
    """Reconstructed session state from replay(). Same shape as what
    IntradaySession would have produced on the original run — minus
    BandwidthState (see PRD §8.7)."""

    session_id: str
    session_date: date
    daily_plan: DailyPlan
    end_of_day_report: EndOfDayReport | None
    metrics: SessionMetrics
    events_replayed: int
    diverged_at_tick: int | None = None
```

Plus one new exception in `agent/errors.py` (or a new `reporting/errors.py` — see §12 self-review):

```python
class ReplayDivergenceError(Exception):
    """Raised when replay's produced event differs from the recorded event.
    Attributes: tick_index, event_type, field, expected, actual."""
```

---

## 6. Cross-cutting concerns

### 6.1 Extras handling

- `[xlsxwriter]` extra needed only for the richer XLSX engine; default openpyxl works without it. Both `report(format="xlsx")` and `report(format="all")` handle the extra-missing case: xlsx is skipped with a WARN, MD + JSON still ship. Never fail-fast for missing xlsx.
- No new extra added in Phase 5 — reuses techtrade's `[xlsxwriter]` per NG3.

### 6.2 Idempotency + overwrites

Every `report()` call overwrites existing files in `output_dir`. Operators regenerate reports after fixing template bugs; the alternative (fail-if-exists) would force manual cleanup. WARN log per overwrite so it's auditable.

### 6.3 Deterministic template = the fallback + the report

Same Jinja template (`templates/end_of_day.md.j2`) drives both:
- `PostCloseAgentTurn` narrator fallback (P3.2)
- `report()` when `include_agent_narrative=False` OR no `EndOfDayReportEvent` in the journal

Move the template from `agent/templates/` to `reporting/templates/` in P5.1; update the P3.2 reference. Small refactor, keeps a single source of truth.

### 6.4 Security discipline (carried from Phase 3)

The `md_builder`'s deterministic template path renders `SessionMetrics` fields (numbers, gate names) into MD. **No free-form user text** enters the template — same allowlist principle as `_sanitize_summary` from P3.1. A future addition of an operator-supplied `notes` field to the report would need to run through equivalent sanitization.

`report()` and `replay()` are **read-only** at the router layer — neither writes to `state_store`, neither touches `broker.submit`. They're pure post-session analysis.

### 6.5 Output directory security

`output_dir` accepts arbitrary paths from the operator. To prevent path-traversal-style writes when called from an MCP surface (future scope — Phase 5 doesn't expose these to MCP): if invoked from a context where the caller isn't the operator (Phase 5 CLI + Python API only for now), we'd need path-jailing. **Phase 5 explicitly does not expose `report` / `replay` on the MCP surface** (they'd need write access to disk). Future MCP exposure = follow-up bead with the path-jail defense.

---

## 7. Acceptance criteria

| AC | Description | Test |
|---|---|---|
| AC-P5-1 | `md_builder` produces valid Markdown from a real journal; agent narrative extracted verbatim when present | `test_md_builder.py` |
| AC-P5-2 | `xlsx_builder` produces a workbook with 6 techtrade sheets + 3 intraday sheets; extra-missing degrades gracefully | `test_xlsx_builder.py` |
| AC-P5-3 | `json_builder` produces a valid JSON manifest that round-trips through `json.loads` | `test_json_builder.py` |
| AC-P5-4 | `report(format="all")` writes all 3 files + returns `ReportManifest` with correct paths | `test_report_manifest.py` |
| AC-P5-5 | `replay()` on a well-formed journal produces byte-identical event stream to the recorded one | `test_replay_determinism.py` |
| AC-P5-6 | Round-trip: run `AC-1-ext` E2E → save journal → `replay()` on that journal → same outcome | `test_replay_roundtrip.py` |
| AC-P5-7 | Golden: any change to `_process_signal` that alters event shape fails replay on a checked-in reference journal | `test_replay_no_divergence.py` |

---

## 8. Global constraints (inherited)

- **P1** deterministic core — no LLM in `report()` / `replay()` code paths (LLM only used to extract prior `briefing_md` verbatim).
- **P2** `Decimal` for money — every P&L / fill value in reports uses `Decimal`.
- **P3** no look-ahead — replay is byte-for-byte deterministic; any look-ahead injected via bug fails AC-P5-5.
- **P6** bandwidth meter — replay does NOT charge the meter (it's a replay, not a live run).
- **P7** RiskManager chokepoint — replay uses the same `_process_signal` path (verifying the chokepoint held historically).

---

## 9. Roadmap → Phase 5 planning

Each ships as an independent bd bead + GH issue:

- **P5.0** `reporting/journal_reader.py` + move `_compute_metrics_from_journal` to shared helper (~0.5 day) — foundation.
- **P5.1** `md_builder` + `json_builder` + `report()` router (formats: md, json, all-partial) (~1.5 days) — operator-visible MD path.
- **P5.2** `xlsx_builder` + techtrade export reuse + 3 intraday sheets (~1.5 days) — completes `report()`.
- **P5.3** `replay()` router + `StubbedDataProvider` + `ReplayDivergenceError` + AC-P5-5/6/7 tests (~1.5 days) — closes PRD §8.7.
- **P5.4** CLI subcommands (`report`, `replay`) + README + config examples (~0.5 day) — polish + operator handoff.

**Sequence:** P5.0 → P5.1 → P5.2 → P5.3 → P5.4. P5.0 delivers the journal-reader primitive P5.1/P5.2/P5.3 all consume. P5.2 depends on P5.1's `report()` router being in place. P5.3 is independent of P5.1/P5.2 in principle but ships last so the CLI subcommand can wire both. P5.4 depends on all prior beads landing.

Total estimate: **~5.5 days** (matches PRD §10's "~1 week; Sprint 5").

**Deferred (P2 findings from any post-hoc reviews, filed as `bd remember` notes, NOT blocking Phase 5):**
- MySQL-backed journals (D1 alternative) — a dedicated persistence bead if multi-machine ops materializes.
- MCP exposure of `report` / `replay` — needs path-jail defense first.
- Real-time replay with speed multiplier (`--speed 10x`) — nice-to-have for demos.

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Techtrade export contract changes | Version-pin `openbb-techtrade` in `pyproject.toml`; xlsx_builder catches ImportError on missing `export` symbol and falls through to a minimal fallback workbook |
| Journal corruption breaks replay for that one session | JournalReader propagates corruption errors loudly; operator can inspect the file with `head` / `grep` — NDJSON is line-oriented by design |
| Replay divergence is hard to debug when tick_index is high | `ReplayDivergenceError` carries `(tick_index, event_type, field, expected, actual)` — enough to reproduce the failing tick in isolation |
| Large journals (5000+ events) slow to replay | JournalReader streams events, doesn't load all into memory; replay processes tick-by-tick |
| Operator points `output_dir` at `/etc/` or `~/.ssh/` | Phase 5 doesn't expose report/replay via MCP; local operator's own choice. Future MCP surface = path-jail defense (deferred bead) |
| Path-traversal via crafted `session_id` (e.g. `"../../etc/passwd"`) | `session_journal_path` sanitizes: reject session_id containing `/`, `\`, `..`, or leading `.` before touching disk |

---

## 11. Open questions

**None.** All prior open questions have been resolved by the user-locked D1/D2 decisions, PRD §4.6 signatures, or explicit inheritance from prior phases.

---

## 12. Spec self-review

- ✅ **Placeholder scan** — no TBDs, no vague "handle appropriately" bullets. Every AC has a named test file.
- ✅ **Internal consistency** — the 5-bead split (§9) matches the 4 builders + replay module (§4), the model additions (§5), and the acceptance criteria (§7).
- ✅ **Scope check** — Phase 5 is one design; it decomposes into 5 buildable beads. `[xlsxwriter]` extra work is bounded (reuse techtrade + add 3 sheets, not rewrite an Excel engine).
- ✅ **Ambiguity check** — "byte-identical" is defined operationally as "recorded events at tick_index N equal produced events at tick_index N, where equal means same event_type + same payload dict after pydantic validation." "Deterministic template" reuses the P3.2 Jinja template verbatim.
- ✅ **Prior-phase alignment** — the shared `_compute_metrics_from_journal` refactor is called out explicitly (§4.2, §6.3); the P3.2 template move is called out (§6.3). No silent renames.
- ✅ **Security posture** — carries Phase 3 discipline: no free-form text in deterministic templates, no MCP exposure of write-capable routers, `session_id` sanitization for path resolution.

---

## 13. What's deliberately NOT in Phase 5

- **AlertManager (Phase 4).** Deferred — you can add it in parallel or after Phase 5. Phase 5 doesn't depend on it.
- **Live-integration validation.** Phase 6 covers real fmp_cached hits.
- **Real-time replay speed multiplier.** Nice-to-have, filed as a follow-up bead.
- **Multi-session batch report (`report --sessions 2026-07-06..2026-07-13`).** Same shape but different aggregation. Filed as a follow-up.
- **Report diff (`report-diff s1 s2`).** Operator use case exists but is speculative for Phase 5.
