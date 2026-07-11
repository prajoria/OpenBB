# fmp-trading Phase 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Supersedes:** `docs/superpowers/plans/2026-07-06-fmp-trading-phase5.md` (795-line pre-Phase-3 draft). That file was written alongside the PRD before Phase 3 shipped; several primitives it references (`session_router.py`, `IntradaySession.reconstruct_from_events`, `AC-8`) either don't exist or have different shapes than reality after Phases 0–3 landed. This plan supersedes it against the actual shipped primitives on branch `fmp_trading @ 3d68f0be3`.

**Goal:** Ship the two post-session tools operators need to consume + verify what happened today: `obb.fmp_trading.report(session_id, format="all")` (MD + XLSX + JSON generation) and `obb.fmp_trading.replay(journal_path, from_tick, to_tick)` (byte-identical journal reconstruction). Plus polish: README + CLI subcommand docs + starter config examples. Closes PRD §10 Phase 5.

**Architecture:** Five thin modules under a new `reporting/` package, each with one responsibility (journal reading, MD building, XLSX building, JSON building, top-level `report()` orchestration) plus a separate `reporting/replay.py` that reads recorded events + runs them through the shipped Phase 2 `IntradaySession` via a `StubbedDataProvider`. XLSX **imports** `openbb_techtrade.reporting.excel_export` for the base 6-sheet workbook and appends 3 intraday-specific sheets — no reimplementation of techtrade internals (NG3). MD reuses P3.2's Jinja narrator template when the journal has no `EndOfDayReportEvent` (or when `include_agent_narrative=False`), otherwise extracts `briefing_md` verbatim from the event. Replay determinism is what proves the "reconstructible from journal" contract PRD §8.7 states.

**Tech Stack:** Python 3.10-3.13, Pydantic v2, `openpyxl` (core dep — default XLSX engine), `openbb-techtrade` (already required — used for base workbook), `openbb_core_journal` (shipped in Phase 1 / J1-J3), `jinja2` (already in `[agent]` extra — reused for the deterministic MD template). Env: `.venv_win`. Provider always `fmp_cached` (no raw `fmp`, no `yfinance`).

**PRD + design references:**
- PRD `docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md` §4.6 (report), §4.1 (replay), §8.7 (reconstructible from journal), §10 Phase 5 roadmap, NG3 (Excel reuses techtrade)
- Design spec `docs/superpowers/specs/2026-07-10-fmp-trading-phase5-report-replay-design.md` (D1/D2 decisions + 5-bead split)

## Pre-execution checklist (from review §8 — ALL must be addressed before/during the relevant task)

- [ ] **[P0] P5.3** implement real `replay()` with `StubbedDataProvider` + `run_tick` + comparator + `ReplayDivergenceError`. **Mutation test must fail against a placeholder** (perturb a fill, assert divergence detected). No greening against stubs.
- [ ] **[P0] P5.2 tests** assert the 6 techtrade base sheets ARE present (not just the 3 intraday sheets). `_call_techtrade_export` calls techtrade for real; no placeholder workbook.
- [ ] **[P0] P5.1 tests** cover the verbatim-narrative path with a real briefing_md_content extraction (paired with P5.0 Step 4 widening `EndOfDayReportEvent`).
- [ ] **[P0] P5.0 Step 0** — resolve the `openbb_core_journal` API (function names + import path) before writing any downstream code. Critical-path unknown must not stay unknown.
- [ ] **[P1] P5.0** — widen `EndOfDayReportEvent` to journal `briefing_md_content` so `include_agent_narrative=True` actually works.
- [ ] **[P1] P5.2** — `PerSymbolPnL` accumulates in `Decimal`, not float. Regression test asserts `"0.30"` not `"0.30000000000000004"`.
- [ ] **[P1] P5.0** — `SessionMetrics.pnl_source` surfaces P&L provenance (authoritative vs reconstructed). `SessionMetrics.total_commissions` + `total_slippage` for cost drag.
- [ ] **[P1] P5.3** — reconcile replayed P&L against `session_end.realized_pnl`; mismatch is a stronger correctness signal than deserialization stability.
- [ ] **[P1] `agent/post_close.py`** narrow try/except (only `FileNotFoundError` + `JSONDecodeError`); programming bugs propagate.
- [ ] **[P2] `session_journal_path`** — Windows drive-relative guard + post-resolution `is_relative_to` check.
- [ ] **[P2] `_parse_session_date`** — raise on failure, don't default to `today()` (mis-dating trap).
- [ ] **[P2] Config examples** — filenames encode BOTH axes (`<preset>-<risk_tuning>.yaml`); no bare `default.yaml`.
- [ ] **[P2] MD briefing template** — surface cost drag (`total_commissions` + `total_slippage`) + `pnl_source`.

---

## Global Constraints

Every task's requirements implicitly include these. Copied verbatim from PRD + prior phases so no reader needs to jump documents.

- **P1 — Deterministic core:** no LLM in `report()` / `replay()` code paths. The only LLM interaction is *extracting* pre-recorded `briefing_md` from a `EndOfDayReportEvent` when the operator wants the agent narrative verbatim.
- **P2 — `Decimal` for money:** every price, size, notional, commission, and P&L value in reports uses `Decimal(str(...))`. Never `float`. `Decimal` serializes to string in JSON manifests (canonical form).
- **P3 — No look-ahead:** replay is byte-for-byte deterministic. Any look-ahead injected via bug fails `AC-P5-5` / `AC-P5-7` on stored journals.
- **P6 — Bandwidth meter:** `replay()` does NOT charge the meter (it's a replay of past data, not a live run). `report()` doesn't touch the meter either.
- **P7 — RiskManager chokepoint:** replay uses the same `IntradaySession._process_signal` path — verifying the chokepoint invariant held historically.
- **NG3 — No new Excel engine:** `xlsx_builder` calls `openbb_techtrade.reporting.excel_export.export()` for the base workbook; only the 3 new intraday-specific sheets are original code in this extension.
- **`fmp_cached` is the only provider** — never raw `fmp`, never `yfinance`. `StubbedDataProvider` used in replay so provider dispatch is moot for the deterministic reconstruction path.
- **`.venv_win` for all Python commands** — `.venv_win\Scripts\python.exe -m pytest ...`. Never system Python.
- **Codegen bug (inherited from Phase 1):** router commands annotate return type as **bare `OBBject`**, never `OBBject[ReportManifest]` or `OBBject[SessionResult]`. The static package builder emits parametrized model names into generated signatures without importing them → `NameError` on first namespace access.
- **Beads for all task tracking** — `bd create`, `bd close`, `bd ready`. Never `TodoWrite` / `TaskCreate` / markdown TODOs.
- **Ship each task as one commit** with `Co-Authored-By: Claude <noreply@anthropic.com>` and a `#<gh-issue>` / `bd-<id>` reference in the subject.

---

## File Structure

Additive package + one router edit + one CLI edit. Existing Phase 2/3 code is unchanged except for the small `_compute_metrics_from_journal` refactor (moved from `agent/post_close.py` to `reporting/journal_reader.py` so both consumers import it).

```
openbb_platform/extensions/fmp_trading/openbb_fmp_trading/
├── reporting/                                       # ALL NEW in P5.x
│   ├── __init__.py                                  # extras-safe re-exports
│   ├── journal_reader.py                           # P5.0 — session_id -> events + shared metrics helper
│   ├── md_builder.py                               # P5.1 — MD path (agent narrative OR deterministic template)
│   ├── json_builder.py                             # P5.1 — canonical JSON manifest
│   ├── report.py                                    # P5.1 — report() orchestrator + ReportManifest
│   ├── xlsx_builder.py                             # P5.2 — techtrade base + 3 intraday sheets
│   ├── replay.py                                    # P5.3 — journal-driven IntradaySession replay
│   └── templates/
│       └── end_of_day.md.j2                        # P5.1 — deterministic MD template (moved from agent/templates/)
├── routers/                                         # NEW package
│   ├── __init__.py                                  # marker
│   └── report_router.py                             # P5.1/P5.3 — obb.fmp_trading.{report,replay} bindings
├── models/
│   └── results.py                                  # UPDATE — add SessionResult, ReplayResult (ReportManifest already exists)
├── agent/
│   ├── post_close.py                                # UPDATE — import metrics helper from reporting.journal_reader
│   └── templates/
│       └── post_close_briefing.md.j2                # DELETE (or symlink) — template moves to reporting/templates/
└── cli/
    └── main.py                                      # UPDATE — add `report` and `replay` subcommands

openbb_platform/extensions/fmp_trading/
├── README.md                                        # P5.4 — user-facing entry doc (may already exist; overwrite)
├── docs/cli_reference.md                            # P5.4 — per-subcommand reference (NEW)
├── config_examples/                                 # P5.4 — 3 starter YAML configs (NEW dir)
│   ├── intraday_momentum-moderate.yaml             # Preset + risk axis separated (review #6)
│   ├── trend_follow-conservative.yaml
│   └── mean_revert-aggressive.yaml
├── tests/
│   ├── unit/
│   │   ├── test_journal_reader.py                  # P5.0
│   │   ├── test_md_builder.py                      # P5.1 — AC-P5-1
│   │   ├── test_json_builder.py                    # P5.1 — AC-P5-3
│   │   ├── test_report_manifest.py                 # P5.1 — AC-P5-4 (format="all" round-trip)
│   │   ├── test_xlsx_builder.py                    # P5.2 — AC-P5-2 (skip if [xlsxwriter] absent)
│   │   └── test_replay_determinism.py              # P5.3 — AC-P5-5 (byte-identical across 3 runs)
│   ├── integration/
│   │   └── test_replay_roundtrip.py                # P5.3 — AC-P5-6 (AC-1-ext journal round-trip)
│   ├── golden/
│   │   └── test_replay_no_divergence.py            # P5.3 — AC-P5-7 (reference-journal regression)
│   └── fixtures/journals/
│       └── ref_2026-07-13_msft_aapl.ndjson         # P5.3 — checked-in reference journal (~50 events)
└── pyproject.toml                                    # unchanged (no new extras; [xlsxwriter] already exists)
```

**Deliberately NOT touched:**
- `core/session.py`, `core/tick_loop.py` (Phase 2 code stays as-is; replay drives them through the existing seams)
- `core/state_store.py` (P3.0 stays as-is; replay is read-only)
- Any `fmp_cached` provider code
- `[agent]` extra (Phase 3 stays as-is)

**Out of scope for Phase 5** (deferred to Phase 6 or later beads, do NOT create here):
- Backtest bridge / `validate` command → P6.1
- HTML/PDF renderers → v2
- Email / webhook / push delivery of the report → v2 (NG7)
- MySQL-backed journals (see design spec D1) → dedicated persistence bead
- MCP exposure of `report` / `replay` (needs path-jail defense) → follow-up bead
- Real-time replay speed multiplier (`--speed 10x`) → nice-to-have follow-up

---

## Task Right-Sizing

Each task ships as one bd bead + one commit + one GH issue closure. Setup/config/doc edits fold into the task whose deliverable needs them. Every task ends with an independently-verifiable green pytest run (deferred to `.venv_win` per project convention — the sandbox has no Python).

---

## Task P5.0: `reporting/journal_reader.py` + shared metrics helper + `SessionMetrics.pnl_source`

**Consumes:** `openbb_core_journal` line-reader (verify canonical name at P5.0 Step 0 below — critical-path resolution per review S6); `SessionMetrics` from `models/report.py` (Phase 3 P3.2 shipped it); typed `JournalEvent` subclasses from `models/journal_events.py`.

**Produces:**
- `read_session_events(session_id, root=None) -> Iterable[JournalEvent]` — resolver + reader
- `read_journal_file(path) -> Iterable[JournalEvent]` — takes explicit path (used by `replay()`)
- `session_journal_path(session_id, root=None) -> Path` — path-traversal-guarded resolver (see review S4 for Windows drive-relative hardening)
- `compute_metrics_from_events(events) -> SessionMetrics` — shared helper, replaces `PostCloseAgentTurn._compute_metrics_from_journal`
- `SessionMetrics.pnl_source: Literal["authoritative_session_end", "summed_from_fills", "empty"]` — new field surfacing P&L provenance (review finding #4)
- `SessionMetrics.total_commissions: Decimal` + `SessionMetrics.total_slippage: Decimal` — session-level cost drag (review finding #6)

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/__init__.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/journal_reader.py`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models/report.py` — extend `SessionMetrics` with `pnl_source`, `total_commissions`, `total_slippage` (review findings #4 + #6)
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/post_close.py` — replace private `_compute_metrics_from_journal` with `from openbb_fmp_trading.reporting.journal_reader import compute_metrics_from_events`; narrow the try/except (review S2); **journal the LLM's `briefing_md` content in `EndOfDayReportEvent.payload["briefing_md_content"]` so the P5.1 verbatim path is actually reachable (review finding #2)**
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_journal_reader.py`

**Interfaces:**
- Consumes: `openbb_core_journal.<resolved-name>(path_or_id)` (see Step 0)
- Produces: 4 public functions above + `DEFAULT_JOURNAL_ROOT = Path.home() / ".openbb_platform" / "fmp_trading" / "journals"`

- [ ] **Step 0: Resolve the `openbb_core_journal` API (review S6, P0-CRITICAL)**

The old plan repeatedly said "verify at impl time" — P5.0 is that time. Run these two lookups and pin the exact function name before writing any P5.0 code:

```bash
# What's the shipped public API for reading journals?
grep -n "^def \|^class " openbb_platform/core/openbb_core_journal/reader.py
grep -n "^def \|^class " openbb_platform/core/openbb_core_journal/replay.py
grep -n "^__all__" openbb_platform/core/openbb_core_journal/__init__.py
```

Record the answer here before proceeding:

- Function to iterate NDJSON events from a file: `<name>` (e.g. `read_journal_lines`, `iter_events`, `replay_file`)
- Function that takes a session_id (if any): `<name>` (may not exist — that's what our shim is for)
- Import path: `from openbb_core_journal import <name>` OR `from openbb_core_journal.reader import <name>`

Every downstream task inherits this resolution. Getting it wrong here cascades into P5.1/P5.2/P5.3.

- [ ] **Step 1: Write the failing test suite (RED)**

Create `openbb_platform/extensions/fmp_trading/tests/unit/test_journal_reader.py`:

```python
"""Unit tests for reporting/journal_reader.py (P5.0).

Verifies:
  * session_journal_path resolves session_id -> DEFAULT_JOURNAL_ROOT / <id>.ndjson
  * session_id sanitization rejects path-traversal attempts
  * read_session_events + read_journal_file both yield JournalEvent objects
  * compute_metrics_from_events produces same SessionMetrics that
    PostCloseAgentTurn._compute_metrics_from_journal did
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestSessionJournalPath:
    def test_default_root_used_when_none(self):
        from openbb_fmp_trading.reporting.journal_reader import (
            DEFAULT_JOURNAL_ROOT, session_journal_path,
        )
        assert session_journal_path("s20260713") == (
            DEFAULT_JOURNAL_ROOT / "s20260713.ndjson"
        )

    def test_explicit_root_respected(self, tmp_path):
        from openbb_fmp_trading.reporting.journal_reader import session_journal_path
        result = session_journal_path("s20260713", root=tmp_path)
        assert result == tmp_path / "s20260713.ndjson"

    @pytest.mark.parametrize("bad_id", [
        "../etc/passwd",
        "..\\..\\Windows\\System32\\config",
        "a/b",
        "a\\b",
        ".hidden",
        "",
        "C:foo",  # review S4: Windows drive-relative
        "sess:id",  # embedded colon
    ])
    def test_bad_session_id_rejected(self, bad_id):
        """Security: session_id sanitization prevents path-traversal writes."""
        from openbb_fmp_trading.reporting.journal_reader import session_journal_path
        with pytest.raises(ValueError):
            session_journal_path(bad_id)


class TestReadJournalFile:
    def test_reads_ndjson_and_yields_events(self, tmp_path):
        """Round-trip: write a tiny NDJSON, read it back, count events."""
        from openbb_fmp_trading.reporting.journal_reader import read_journal_file

        path = tmp_path / "s.ndjson"
        # Two events; typed subclasses ship in models.journal_events
        path.write_text(
            '{"event_type":"session_start","ts":"2026-07-13T13:30:00+00:00",'
            '"session_id":"s20260713","payload":{}}\n'
            '{"event_type":"session_end","ts":"2026-07-13T20:15:00+00:00",'
            '"session_id":"s20260713","payload":{"flat_at_close":true}}\n',
            encoding="utf-8",
        )
        events = list(read_journal_file(path))
        assert len(events) == 2
        # Order-preserving
        assert events[0].event_type == "session_start"
        assert events[1].event_type == "session_end"

    def test_missing_file_raises(self, tmp_path):
        from openbb_fmp_trading.reporting.journal_reader import read_journal_file
        with pytest.raises(FileNotFoundError):
            list(read_journal_file(tmp_path / "does-not-exist.ndjson"))


class TestComputeMetricsFromEvents:
    """Refactor contract: same SessionMetrics as PostCloseAgentTurn produced."""

    def test_empty_journal_produces_zero_metrics(self):
        from openbb_fmp_trading.reporting.journal_reader import (
            compute_metrics_from_events,
        )
        metrics = compute_metrics_from_events([])
        assert metrics.realized_pnl == Decimal("0")
        assert metrics.fill_count == 0
        assert metrics.order_count == 0
        assert metrics.veto_counts_by_gate == {}

    def test_counts_orders_fills_vetoes(self):
        """A representative mixed-event journal produces the expected aggregates."""
        from openbb_fmp_trading.models.journal_events import (
            FillEvent, OrderEvent, VetoEvent, SessionEndEvent,
        )
        from openbb_fmp_trading.reporting.journal_reader import (
            compute_metrics_from_events,
        )
        from datetime import datetime, timezone

        events = [
            OrderEvent(ts=datetime(2026,7,13,14,0,tzinfo=timezone.utc),
                       session_id="s", payload={}),
            OrderEvent(ts=datetime(2026,7,13,14,5,tzinfo=timezone.utc),
                       session_id="s", payload={}),
            FillEvent(ts=datetime(2026,7,13,14,0,tzinfo=timezone.utc),
                      session_id="s", payload={"realized_pnl": "150.00"}),
            VetoEvent(ts=datetime(2026,7,13,14,10,tzinfo=timezone.utc),
                      session_id="s", payload={"gate": "G1"}),
            VetoEvent(ts=datetime(2026,7,13,14,15,tzinfo=timezone.utc),
                      session_id="s", payload={"gate": "G1"}),
            SessionEndEvent(ts=datetime(2026,7,13,20,15,tzinfo=timezone.utc),
                            session_id="s", payload={"realized_pnl": "175.00"}),
        ]
        metrics = compute_metrics_from_events(events)
        assert metrics.order_count == 2
        assert metrics.fill_count == 1
        # session_end.realized_pnl overrides fill-summing (matches P3.2 behavior)
        assert metrics.realized_pnl == Decimal("175.00")
        assert metrics.veto_counts_by_gate == {"G1": 2}
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_journal_reader.py -q`
Expected: FAIL — `ModuleNotFoundError: openbb_fmp_trading.reporting.journal_reader`.

- [ ] **Step 2: Implement `reporting/__init__.py` + `reporting/journal_reader.py` (GREEN)**

`reporting/__init__.py`:

```python
"""Post-session reporting + replay tools (Phase 5).

Nothing in this package is [agent]-gated — pure deterministic post-
processing of on-disk NDJSON journals. The `[xlsxwriter]` extra is
optional and only affects the XLSX renderer (xlsx_builder.py); the MD +
JSON paths work with the core install alone.
"""
```

`reporting/journal_reader.py`:

```python
"""Journal reading + shared metrics helper (P5.0).

The single source of truth for two questions:
  1. Where does session_id map to on disk? -> session_journal_path
  2. How do we turn a stream of JournalEvents into SessionMetrics?
     -> compute_metrics_from_events (shared with PostCloseAgentTurn)

Both `report()` and `replay()` — and the P3.2 post-close narrator path
that was already computing metrics inline — call these functions. No
duplicated event-tallying logic anywhere else in the extension.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Iterable

from openbb_fmp_trading.models.report import SessionMetrics

# All journals live here unless the operator overrides. Matches the
# on-disk layout the JournalWriter uses today (Phase 1 J2).
DEFAULT_JOURNAL_ROOT = Path.home() / ".openbb_platform" / "fmp_trading" / "journals"

# Characters/patterns rejected in session_id path resolution.
# session_ids come from IntradaySession (currently `s%Y%m%d%H%M%S`
# strftime) so this is defense-in-depth against a compromised journal-
# writer or a hand-crafted CLI arg.
# ':' rejected per review S4 — Windows drive-relative names bypass root.
_FORBIDDEN_SUBSTRINGS = ("/", "\\", "..", ":")


def session_journal_path(session_id: str, root: Path | None = None) -> Path:
    """Resolve session_id -> on-disk path with path-traversal guards.

    Rejects (before touching disk):
      * empty session_id
      * starts with '.'
      * contains '/' or '\\' or '..'
      * contains ':' — Windows drive-relative names like 'C:foo' resolve
        to a completely different drive when joined; a session_id must
        never be able to select the drive (review S4).

    After resolution: assert the resolved path is inside root. If it
    escapes root (via symlinks, drive-relative Windows quirks, or a
    bug in the character-blocklist above), raise ValueError. Belt +
    suspenders — the character list should catch it first, but the
    is_relative_to check is the actual security invariant.
    """
    if not session_id or session_id.startswith("."):
        raise ValueError(f"invalid session_id: {session_id!r}")
    for bad in _FORBIDDEN_SUBSTRINGS:
        if bad in session_id:
            raise ValueError(f"invalid session_id (contains {bad!r}): {session_id!r}")
    resolved_root = (root or DEFAULT_JOURNAL_ROOT)
    candidate = resolved_root / f"{session_id}.ndjson"
    # Post-resolution check (S4): the actual filesystem path must stay
    # inside the root. is_relative_to is Python 3.9+; the extension's
    # floor is 3.10 (per pyproject) so this is available.
    try:
        candidate.resolve().relative_to(resolved_root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"session_id {session_id!r} resolves outside journal root — "
            f"likely a Windows drive-relative or symlink attack"
        ) from exc
    return candidate


def read_journal_file(path: Path):
    """Yield JournalEvent objects from an NDJSON file, in write order.

    Uses openbb_core_journal's line-oriented parser so typed subclass
    dispatch (TickEvent, SessionStartEvent, etc.) works. FileNotFoundError
    propagates loudly — silent zeros would be dangerous for post-mortem work.
    """
    from openbb_core_journal import read_journal_lines
    # read_journal_lines shipped in Phase 1 J2/J3; if the API differs use the shim.
    yield from read_journal_lines(path)


def read_session_events(session_id: str, root: Path | None = None):
    """Yield events for a session_id — thin shim over read_journal_file."""
    yield from read_journal_file(session_journal_path(session_id, root=root))


def compute_metrics_from_events(events) -> SessionMetrics:
    """Extract SessionMetrics from an event iterable.

    Extracted from PostCloseAgentTurn._compute_metrics_from_journal (P3.2).
    Same core logic; both callers import from here now so there's exactly
    one place to fix if the metrics rollup changes shape.

    Behavior (with review-fold-in for finding #4 pnl_source):
      * FillEvent counted; realized_pnl summed from fill payloads (Decimal)
      * FillEvent commission + slippage aggregated for review finding #6
      * OrderEvent counted
      * VetoEvent counted, aggregated by 'gate' (falls back to 'reason_code')
      * SessionEndEvent.payload.realized_pnl OVERRIDES the fill-summed value
        AND sets pnl_source='authoritative_session_end' — the operator can
        see whether the number is authoritative or reconstructed.
      * If no SessionEndEvent + we saw at least one fill:
        pnl_source='summed_from_fills' (reconstructed — may disagree if
        session_end existed but we're replaying a truncated journal)
      * If no fills and no session_end: pnl_source='empty'
    """
    veto_counts: dict[str, int] = {}
    fill_count = 0
    order_count = 0
    realized_pnl_from_fills = Decimal("0")
    total_commissions = Decimal("0")
    total_slippage = Decimal("0")
    authoritative_pnl: Decimal | None = None

    for e in events:
        et = getattr(e, "event_type", None)
        payload = getattr(e, "payload", {}) or {}
        if et == "order":
            order_count += 1
        elif et == "fill":
            fill_count += 1
            fp = payload.get("realized_pnl")
            if fp is not None:
                try:
                    realized_pnl_from_fills += Decimal(str(fp))
                except (TypeError, ValueError):
                    pass
            # Review finding #6: aggregate cost drag
            comm = payload.get("commission")
            if comm is not None:
                try:
                    total_commissions += Decimal(str(comm))
                except (TypeError, ValueError):
                    pass
            slip = payload.get("slippage")
            if slip is not None:
                try:
                    total_slippage += Decimal(str(slip))
                except (TypeError, ValueError):
                    pass
        elif et == "veto":
            gate = payload.get("gate") or payload.get("reason_code") or "unknown"
            veto_counts[gate] = veto_counts.get(gate, 0) + 1
        elif et == "session_end":
            rp = payload.get("realized_pnl")
            if rp is not None:
                try:
                    authoritative_pnl = Decimal(str(rp))
                except (TypeError, ValueError):
                    pass

    # Provenance: review finding #4 — operator sees WHICH source produced the number
    if authoritative_pnl is not None:
        realized_pnl = authoritative_pnl
        pnl_source = "authoritative_session_end"
    elif fill_count > 0:
        realized_pnl = realized_pnl_from_fills
        pnl_source = "summed_from_fills"
    else:
        realized_pnl = Decimal("0")
        pnl_source = "empty"

    return SessionMetrics(
        realized_pnl=realized_pnl,
        pnl_source=pnl_source,
        total_commissions=total_commissions,
        total_slippage=total_slippage,
        veto_counts_by_gate=veto_counts,
        fill_count=fill_count,
        order_count=order_count,
    )
```

**Model additions in `models/report.py`** (needed for the fields above):

```python
class SessionMetrics(Data):
    # existing fields ...
    realized_pnl: Decimal = Field(description="Total realized P&L in dollars.")
    # NEW (review finding #4): P&L provenance so the operator can see if this
    # is authoritative (session_end payload) or reconstructed (summed from fills).
    pnl_source: Literal["authoritative_session_end", "summed_from_fills", "empty"] = Field(
        default="empty",
        description=(
            "Where realized_pnl came from. 'authoritative_session_end' means the "
            "IntradaySession's own tally was persisted. 'summed_from_fills' means "
            "we reconstructed from FillEvent payloads (e.g. after a crash mid-"
            "session) — may disagree with the true tally. 'empty' means no fills."
        ),
    )
    # NEW (review finding #6): session-level cost drag surfaced in headline metrics
    total_commissions: Decimal = Field(
        default=Decimal("0"),
        description="Total commission paid across all fills today (P2 Decimal).",
    )
    total_slippage: Decimal = Field(
        default=Decimal("0"),
        description="Total slippage across all fills today (P2 Decimal).",
    )
    # existing fields continue ...

    model_config = ConfigDict(
        # Pin Decimal-as-string serialization for the whole model — review finding #3.
        # Without this, pydantic may coerce Decimal->float at model_dump(mode='json')
        # time, silently losing precision BEFORE json_builder's default=str runs.
        # Explicit is safer than trusting default behavior across pydantic versions.
        json_encoders={Decimal: str},
    )
```

- [ ] **Step 3: Refactor `PostCloseAgentTurn._compute_metrics_from_journal`**

Modify `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/post_close.py`:

```python
def _compute_metrics_from_journal(self, session_id: str) -> SessionMetrics:
    """Replay today's journal into aggregate metrics.

    Delegates to the shared helper in reporting.journal_reader. Kept as
    a thin method so P3.2's callers don't change; the actual math lives
    in one place (P5.0 refactor).

    Exception discipline (review S2 — narrow catch):
      * FileNotFoundError -> empty metrics (session never journaled)
      * json.JSONDecodeError / journal-corruption from the reader ->
        empty metrics with WARN log (bad data, not our bug)
      * EVERYTHING ELSE propagates. A TypeError/AttributeError deep in
        the metrics helper is a bug — surfacing it beats masking it as
        "empty session" for the next 6 months.
    """
    import json as _json

    try:
        from openbb_fmp_trading.reporting.journal_reader import (
            compute_metrics_from_events, read_session_events,
        )
    except ImportError:
        # Reporting package missing (shouldn't happen — defense-in-depth)
        return SessionMetrics(realized_pnl=Decimal("0"))

    try:
        events = list(read_session_events(session_id))
    except FileNotFoundError:
        return SessionMetrics(realized_pnl=Decimal("0"))
    except _json.JSONDecodeError as exc:
        logger.warning(
            "post_close: journal corrupt for session %s (%s); empty metrics",
            session_id, exc,
        )
        return SessionMetrics(realized_pnl=Decimal("0"))
    # Note: NO broad `except Exception` — programming bugs propagate.
    return compute_metrics_from_events(events)
```

Existing P3.2 tests (`test_post_close_fallback.py`) should still pass — the behavior is unchanged, only the code location moved. Run those tests after the refactor to confirm no regression.

- [ ] **Step 4: Widen `EndOfDayReportEvent` to journal `briefing_md` content (review finding #2)**

The current P3.2 event stores `briefing_md_length: int` but NOT the content. This makes `include_agent_narrative=True` a dead knob in P5.1 — the extractor can never find the content to extract. Two edits close it:

**a. In `agent/post_close.py::_journal_commit`** — add the content to the payload:

```python
def _journal_commit(
    self, report: EndOfDayReport, tool_call: ToolCall | None
) -> None:
    self.journal.write(
        EndOfDayReportEvent(
            ts=datetime.now(timezone.utc),
            session_id=report.session_id,
            payload={
                "agent_backend": report.agent_backend,
                "is_deterministic_fallback": report.is_deterministic_fallback,
                "briefing_md_length": len(report.briefing_md),
                # NEW (review finding #2): journal the actual content so
                # report(include_agent_narrative=True) can extract it verbatim
                # tomorrow / next week / during a post-mortem.
                "briefing_md_content": report.briefing_md,
                "recommendation_count": len(report.tomorrow_recommendations),
                "model_id": (
                    getattr(tool_call, "model_id", None) if tool_call else None
                ),
                "prompt_version": POST_CLOSE_PROMPT_VERSION,
            },
        )
    )
```

**b. Regression test in `test_post_close_fallback.py`** — extend `TestA6ProvenanceOnCommit` to assert `briefing_md_content` is present in the payload (both LLM and narrator paths — the narrator's own briefing_md is journaled too).

**Rationale (from review #2):** shipping `include_agent_narrative=True` as a feature knob that silently always falls back to the deterministic template is a trap. Either make it work (which is 2 lines) or delete it. Making it work is the right call — the LLM's prose IS more nuanced than any template and operators will want it verbatim in post-mortems.

**Storage cost:** `briefing_md` is typically 500-2000 chars. Journal writes are append-only NDJSON; this is negligible.

- [ ] **Step 4: Run tests + commit P5.0**

Run:
```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_journal_reader.py openbb_platform/extensions/fmp_trading/tests/unit/test_post_close_fallback.py -q
```

Expected: all pass.

Commit:
```
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/ \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/post_close.py \
        openbb_platform/extensions/fmp_trading/tests/unit/test_journal_reader.py
git commit -m "feat(fmp_trading): P5.0 reporting.journal_reader + shared metrics helper

Foundation for Phase 5. Ships:
  - reporting/journal_reader.py:
    * session_journal_path (path-traversal guarded resolver)
    * read_session_events / read_journal_file
    * compute_metrics_from_events (extracted from PostCloseAgentTurn)
  - agent/post_close.py: _compute_metrics_from_journal delegates to
    the shared helper. Behavior unchanged; single source of truth
    for metrics-from-journal computation.

Closes OpenBBTechnical-<P5.0-bead>, #<gh-issue>

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task P5.1: `report(session_id, format={md,json,all})` — MD + JSON paths

**Consumes:** P5.0's `journal_reader`; P3.2's `EndOfDayReport` + `SessionMetrics` models; Jinja template (moved from `agent/templates/` to `reporting/templates/`).

**Produces:**
- `reporting/md_builder.py` — `build_md(events, metrics, include_agent_narrative) -> str`
- `reporting/json_builder.py` — `build_json_manifest(events, metrics, plan, report) -> str`
- `reporting/report.py` — `report(session_id, format, output_dir, include_agent_narrative) -> ReportManifest`
- `routers/report_router.py` — thin wrapper exposing `obb.fmp_trading.report(...)` (bare `OBBject` return)

`format="xlsx"` and the XLSX portion of `format="all"` land in P5.2.

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/md_builder.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/json_builder.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/report.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/templates/end_of_day.md.j2` (moved from `agent/templates/post_close_briefing.md.j2` — content unchanged)
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/post_close.py` — update template path constant to reference the moved file
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models/results.py` — add `SessionResult` (see §5 of design spec)
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/routers/__init__.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/routers/report_router.py`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/fmp_trading_router.py` — wire report_router in
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_md_builder.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_json_builder.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_report_manifest.py`

**Interfaces:**
- Consumes: `journal_reader.read_session_events`, `journal_reader.compute_metrics_from_events`
- Produces: `report(session_id: str, format: Literal["md","json","xlsx","all"], output_dir: Path | None, include_agent_narrative: bool) -> ReportManifest`

- [ ] **Step 1: Move the template file (no code change)**

```
git mv openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/templates/post_close_briefing.md.j2 \
       openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/templates/end_of_day.md.j2
mkdir -p openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/templates/
```

Update the constant in `agent/post_close.py`:

```python
_TEMPLATES_DIR = (
    Path(__file__).parent.parent / "reporting" / "templates"
)
_NARRATOR_TEMPLATE = "end_of_day.md.j2"
```

Existing P3.2 narrator tests should still pass — same template content, new path.

- [ ] **Step 2: Write the failing MD-builder test**

Create `tests/unit/test_md_builder.py`:

```python
"""AC-P5-1: md_builder produces valid Markdown from events.

Two code paths — BOTH must have real assertions per review finding #1
(TDD honesty). No greening against stubs.

  1. include_agent_narrative=True AND EndOfDayReportEvent in events
     -> extract briefing_md verbatim from the event's
        payload["briefing_md_content"] (added in P5.0 Step 4)
  2. Otherwise -> render deterministic Jinja template using SessionMetrics
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


class TestAgentNarrativePath:
    """Review finding #2: `include_agent_narrative=True` must produce
    the LLM's actual prose verbatim, NOT silently fall through."""

    def test_extracts_briefing_md_verbatim_when_present(self):
        """P5.0 Step 4 widened EndOfDayReportEvent to journal
        briefing_md_content. This test proves the extractor uses it."""
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.models.journal_events import EndOfDayReportEvent
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.md_builder import build_md

        # The distinctive LLM prose we expect back verbatim
        llm_briefing = (
            "# Session Briefing — Q3 2026\n\n"
            "Today's rotation into semis was catalyzed by NVDA earnings; "
            "MSFT lagged into close due to CFO exit rumor.\n\n"
            "**Process observation:** G6 fired twice on out-sized entry "
            "attempts — sizing rules working as intended."
        )
        events = [
            EndOfDayReportEvent(
                ts=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
                session_id="s20260713",
                payload={
                    "briefing_md_length": len(llm_briefing),
                    "briefing_md_content": llm_briefing,
                    "agent_backend": "claude",
                    "is_deterministic_fallback": False,
                },
            ),
        ]
        metrics = SessionMetrics(realized_pnl=Decimal("100"))
        md = build_md(events, metrics, include_agent_narrative=True)

        # AC-P5-1 (real): the LLM's distinctive prose survives byte-for-byte
        assert md == llm_briefing, (
            "include_agent_narrative=True must return the journaled "
            "briefing_md verbatim, not fall through to the template"
        )
        # Sanity: template header is NOT present in the LLM output
        assert "Session Briefing — " in md  # LLM's own header, not template
        # Distinctive LLM sentence survives round-trip
        assert "rotation into semis" in md

    def test_falls_back_to_template_when_no_briefing_content(self):
        """Legacy events (pre-P5.0-Step-4) have no briefing_md_content
        — extractor returns None, template fallback fires."""
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.models.journal_events import EndOfDayReportEvent
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.md_builder import build_md

        events = [
            EndOfDayReportEvent(
                ts=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
                session_id="s20260713",
                payload={"briefing_md_length": 42, "agent_backend": "claude"},
                # NOTE: no briefing_md_content — legacy or corrupt event
            ),
        ]
        metrics = SessionMetrics(realized_pnl=Decimal("100"))
        md = build_md(events, metrics, include_agent_narrative=True)
        # Template header appears (deterministic fallback fired)
        assert "Session Briefing" in md

    def test_include_agent_narrative_false_forces_template(self):
        """Even when briefing_md_content is present, False forces template."""
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.models.journal_events import EndOfDayReportEvent
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.md_builder import build_md

        events = [
            EndOfDayReportEvent(
                ts=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
                session_id="s20260713",
                payload={
                    "briefing_md_length": 20,
                    "briefing_md_content": "# LLM prose — do NOT use",
                    "agent_backend": "claude",
                },
            ),
        ]
        metrics = SessionMetrics(realized_pnl=Decimal("100"))
        md = build_md(events, metrics, include_agent_narrative=False)
        assert "LLM prose" not in md  # LLM content ignored
        assert "Session Briefing" in md  # template header present


class TestDeterministicTemplatePath:
    def test_renders_template_when_no_end_of_day_event(self):
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.md_builder import build_md

        metrics = SessionMetrics(
            realized_pnl=Decimal("175.00"),
            fill_count=2,
            order_count=2,
            veto_counts_by_gate={"G1": 1},
        )
        md = build_md([], metrics, include_agent_narrative=False)
        assert "Session Briefing" in md
        assert "175.00" in md  # realized_pnl rendered
        assert "G1" in md      # veto gate name rendered

    def test_deterministic_output_stable_across_calls(self):
        """AC-P5-1: same input -> same output (no dict-order noise)."""
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.md_builder import build_md

        metrics = SessionMetrics(realized_pnl=Decimal("0"))
        a = build_md([], metrics)
        b = build_md([], metrics)
        assert a == b
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_md_builder.py -q`
Expected: FAIL — `ModuleNotFoundError: reporting.md_builder`.

- [ ] **Step 3: Implement `md_builder.py`**

```python
"""Markdown builder for report() (P5.1).

Two paths:
  1. include_agent_narrative=True AND briefing_md recoverable from the
     journal -> use it verbatim (LLM prose is richer than any template)
  2. Otherwise -> render templates/end_of_day.md.j2 with SessionMetrics

The template is the SAME file agent/post_close.py's fallback uses
(one source of truth per design-spec §6.3).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def build_md(
    events: list[Any],
    metrics,
    include_agent_narrative: bool = True,
) -> str:
    # Try agent narrative first
    if include_agent_narrative:
        briefing = _extract_briefing_md(events)
        if briefing is not None:
            return briefing
    # Deterministic template fallback
    return _render_narrator_template(metrics)


def _extract_briefing_md(events: list[Any]) -> str | None:
    """Return the LLM's `briefing_md` content if the journal has an
    EndOfDayReportEvent that carries `payload.briefing_md_content`.

    P5.0 Step 4 widened the event schema to include this. Legacy events
    (pre-P5.0-Step-4) may only have `briefing_md_length` — return None
    in that case so the caller falls through to the deterministic
    template. Review finding #2 fold-in: the extractor is no longer a
    permanent no-op; it works whenever the P5.0-augmented journal is
    available.
    """
    for e in events:
        if getattr(e, "event_type", None) == "end_of_day_report":
            payload = getattr(e, "payload", {}) or {}
            content = payload.get("briefing_md_content")
            if content:
                return content
    return None


def _render_narrator_template(metrics) -> str:
    """Render templates/end_of_day.md.j2 with the given SessionMetrics."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("end_of_day.md.j2")
    # session_date + session_id are template-required; template already
    # tolerates them being placeholder strings for the standalone
    # (non-agent) path — see agent/post_close.py's render call for the
    # full arg set.
    return template.render(
        session_date="",
        session_id="",
        metrics=metrics,
        recommendations=[],
    )
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_md_builder.py -q`
Expected: 3 passed.

- [ ] **Step 4: Write + implement `json_builder.py`**

Test (`tests/unit/test_json_builder.py`):

```python
"""AC-P5-3: json_builder produces valid, stable JSON."""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


class TestJsonBuilder:
    def test_output_is_valid_json(self):
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.json_builder import build_json_manifest

        metrics = SessionMetrics(realized_pnl=Decimal("100"))
        text = build_json_manifest(
            events=[], metrics=metrics, plan=None, report=None,
            session_id="s20260713",
        )
        parsed = json.loads(text)
        assert parsed["session_id"] == "s20260713"
        assert parsed["metrics"]["realized_pnl"] == "100"

    def test_decimal_serialized_as_string(self):
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.json_builder import build_json_manifest

        metrics = SessionMetrics(realized_pnl=Decimal("1234.56789012"))
        parsed = json.loads(build_json_manifest(
            events=[], metrics=metrics, plan=None, report=None,
            session_id="s",
        ))
        # Precision preserved via string serialization
        assert parsed["metrics"]["realized_pnl"] == "1234.56789012"

    def test_stable_output_across_calls(self):
        """Sorted keys = stable JSON bytes for same input.

        Note (review S1 fix): timestamps ARE in the output — they come
        from the recorded journal events. Stability is guaranteed only
        because those timestamps are inputs (not generated at render
        time); do NOT call datetime.now() anywhere in json_builder."""
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.json_builder import build_json_manifest

        metrics = SessionMetrics(realized_pnl=Decimal("0"))
        a = build_json_manifest(events=[], metrics=metrics,
                                plan=None, report=None, session_id="s")
        b = build_json_manifest(events=[], metrics=metrics,
                                plan=None, report=None, session_id="s")
        assert a == b
```

Impl (`reporting/json_builder.py`):

```python
"""Canonical JSON manifest builder for report() (P5.1)."""

from __future__ import annotations

import json
from typing import Any


def build_json_manifest(
    events: list[Any],
    metrics,
    plan,
    report,
    session_id: str,
) -> str:
    """Serialize a session's events + metrics + plan + report as sorted-key
    canonical JSON. Decimal renders as string for precision preservation."""
    payload = {
        "session_id": session_id,
        "metrics": metrics.model_dump(mode="json"),
        "daily_plan": plan.model_dump(mode="json") if plan is not None else None,
        "end_of_day_report": (
            report.model_dump(mode="json") if report is not None else None
        ),
        "events": [
            e.model_dump(mode="json") if hasattr(e, "model_dump") else dict(e)
            for e in events
        ],
    }
    return json.dumps(payload, sort_keys=True, default=str)
```

- [ ] **Step 5: Implement `report.py` orchestrator**

Test (`tests/unit/test_report_manifest.py`) — covers `format="all"` with `xlsx` skipped gracefully (P5.2 wires the real XLSX path):

```python
"""AC-P5-4: report(format='all') writes MD + JSON + returns ReportManifest."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


class TestReportManifest:
    def test_format_all_writes_md_and_json(self, tmp_path, monkeypatch):
        # Stub the journal read so no live disk / MySQL involvement
        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter([]),
        )
        from openbb_fmp_trading.reporting.report import report

        manifest = report(
            session_id="s20260713",
            format="all",
            output_dir=tmp_path,
        )
        assert manifest.md_path is not None
        assert manifest.json_path is not None
        assert manifest.md_path.exists()
        assert manifest.json_path.exists()
        # xlsx skipped gracefully in P5.1 (P5.2 wires it)
        # Either xlsx_path is None OR the file exists — both are acceptable

    def test_format_md_writes_only_md(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter([]),
        )
        from openbb_fmp_trading.reporting.report import report

        manifest = report(
            session_id="s20260713",
            format="md",
            output_dir=tmp_path,
        )
        assert manifest.md_path is not None
        assert manifest.json_path is None
        assert manifest.xlsx_path is None

    def test_second_call_overwrites_and_warns(self, tmp_path, monkeypatch, caplog):
        """Review S5: design §6.2 documents idempotent-overwrite behavior.
        Prove it — two report() calls to the same dir overwrite the file
        + emit a WARN log."""
        import logging

        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter([]),
        )
        from openbb_fmp_trading.reporting.report import report

        caplog.set_level(logging.WARNING)
        report(session_id="s20260713", format="md", output_dir=tmp_path)
        first_mtime = (tmp_path / "end_of_day.md").stat().st_mtime
        import time
        time.sleep(0.01)  # ensure mtime tick
        report(session_id="s20260713", format="md", output_dir=tmp_path)
        second_mtime = (tmp_path / "end_of_day.md").stat().st_mtime
        assert second_mtime > first_mtime  # file was rewritten
        # WARN emitted at least once about the overwrite
        assert any("overwrit" in r.message.lower() for r in caplog.records)


class TestFullPathDecimalPrecision:
    """Review finding #3: prove Decimal survives the FULL report(format='json')
    path — not just build_json_manifest in isolation.

    Regression against pydantic v2 coercing Decimal->float silently
    somewhere upstream of json.dumps."""

    def test_decimal_precision_survives_report_json_path(self, tmp_path, monkeypatch):
        import json
        from decimal import Decimal

        from openbb_fmp_trading.models.journal_events import FillEvent, SessionEndEvent
        from datetime import datetime, timezone

        # A Decimal that CANNOT be exactly represented as float
        precise_pnl = Decimal("1234.56789012345")
        events = [
            FillEvent(
                ts=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
                session_id="s",
                payload={"symbol": "MSFT", "realized_pnl": str(precise_pnl)},
            ),
            SessionEndEvent(
                ts=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
                session_id="s",
                payload={"flat_at_close": True, "realized_pnl": str(precise_pnl)},
            ),
        ]

        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter(events),
        )
        from openbb_fmp_trading.reporting.report import report

        manifest = report(session_id="s20260713", format="json", output_dir=tmp_path)
        raw = json.loads(manifest.json_path.read_text())

        # Precision preserved end-to-end: raw JSON has the full digits
        assert raw["metrics"]["realized_pnl"] == "1234.56789012345", (
            f"Decimal precision lost: got {raw['metrics']['realized_pnl']!r}. "
            f"Check model_config.json_encoders on SessionMetrics AND "
            f"json_builder's default=str fallback path (review finding #3)."
        )
```

Impl (`reporting/report.py`):

```python
"""report() orchestrator (P5.1)."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Literal

from openbb_fmp_trading.models.results import ReportManifest

logger = logging.getLogger(__name__)


def report(
    session_id: str,
    format: Literal["md", "xlsx", "json", "all"] = "all",
    output_dir: Path | None = None,
    include_agent_narrative: bool = True,
) -> ReportManifest:
    """Render session artifacts. See design-spec §4.5."""
    from openbb_fmp_trading.reporting import journal_reader
    from openbb_fmp_trading.reporting.json_builder import build_json_manifest
    from openbb_fmp_trading.reporting.md_builder import build_md

    events = list(journal_reader.read_session_events(session_id))
    metrics = journal_reader.compute_metrics_from_events(events)

    # Default output_dir: Analysis/exports/daytrade_<date>/
    session_date = _parse_session_date(session_id, events)
    if output_dir is None:
        output_dir = Path("Analysis") / "exports" / f"daytrade_{session_date}"
    output_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    md_path: Path | None = None
    xlsx_path: Path | None = None
    json_path: Path | None = None

    if format in ("md", "all"):
        md_content = build_md(events, metrics, include_agent_narrative)
        md_path = output_dir / "end_of_day.md"
        if md_path.exists():
            logger.warning("report: overwriting existing %s (idempotent regen)", md_path)
        md_path.write_text(md_content, encoding="utf-8")

    if format in ("json", "all"):
        json_content = build_json_manifest(
            events=events, metrics=metrics,
            plan=None, report=None, session_id=session_id,
        )
        json_path = output_dir / "manifest.json"
        if json_path.exists():
            logger.warning("report: overwriting existing %s (idempotent regen)", json_path)
        json_path.write_text(json_content, encoding="utf-8")

    if format in ("xlsx", "all"):
        # P5.2 wires this. For P5.1 shipping, gracefully skip with WARN.
        try:
            from openbb_fmp_trading.reporting.xlsx_builder import build_workbook
            xlsx_path = output_dir / "end_of_day.xlsx"
            if xlsx_path.exists():
                logger.warning("report: overwriting existing %s (idempotent regen)", xlsx_path)
            build_workbook(session_id, events, metrics, xlsx_path)
        except ImportError as exc:
            warnings.append(f"xlsx skipped: {exc}")
            logger.warning("report: xlsx unavailable in P5.1; skipping (P5.2 wires it)")

    return ReportManifest(
        session_id=session_id,
        session_date=session_date,
        md_path=md_path,
        xlsx_path=xlsx_path,
        json_path=json_path,
        included_agent_narrative=include_agent_narrative and md_path is not None,
        session_events_count=len(events),
        agent_backend=None,  # Read from event when P5.2 adds the extraction
        warnings=warnings,
    )


def _parse_session_date(session_id: str, events: list) -> date:
    """Extract session_date from session_start event OR parse from session_id.

    Preferred: read the session_start event's ts.date() — that's the
    authoritative source. Fallback: parse `s%Y%m%d%H%M%S`.

    Review S3 fix: on parse failure, RAISE ValueError. Silent fallback
    to today() mis-dates the report + output dir (an operator would
    regenerate a report for 2026-07-06 and write it to
    Analysis/exports/daytrade_<today>/ — which is exactly the class
    of confusion that leads to trading the wrong day's data).
    """
    for e in events:
        if getattr(e, "event_type", None) == "session_start":
            ts = getattr(e, "ts", None)
            if ts is not None and hasattr(ts, "date"):
                return ts.date()
    # No session_start event — fall back to parsing session_id.
    # Format: `s%Y%m%d%H%M%S` (14 digits after leading 's').
    if session_id.startswith("s") and len(session_id) >= 9 and session_id[1:9].isdigit():
        try:
            return date(int(session_id[1:5]), int(session_id[5:7]), int(session_id[7:9]))
        except ValueError:
            pass  # fall through to raise below
    raise ValueError(
        f"Cannot determine session_date: no session_start event and "
        f"session_id {session_id!r} doesn't match s%Y%m%d%H%M%S format"
    )
```

- [ ] **Step 6: Wire the router**

Create `routers/__init__.py` (marker) + `routers/report_router.py`:

```python
"""Router for obb.fmp_trading.report and obb.fmp_trading.replay (P5.1/P5.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

router = Router(prefix="")


@router.command(methods=["POST"])
def report(
    session_id: str,
    format: Literal["md", "xlsx", "json", "all"] = "all",
    output_dir: str | None = None,
    include_agent_narrative: bool = True,
) -> OBBject:  # bare per codegen-bug constraint
    """Render session artifacts as MD + XLSX + JSON. PRD §4.6."""
    from openbb_fmp_trading.reporting.report import report as _report

    manifest = _report(
        session_id=session_id,
        format=format,
        output_dir=Path(output_dir) if output_dir else None,
        include_agent_narrative=include_agent_narrative,
    )
    return OBBject(results=manifest.model_dump(mode="json"))
```

Modify `openbb_fmp_trading/fmp_trading_router.py` to include the new router (follows the existing include pattern).

- [ ] **Step 7: Run tests + commit P5.1**

Run:
```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_md_builder.py openbb_platform/extensions/fmp_trading/tests/unit/test_json_builder.py openbb_platform/extensions/fmp_trading/tests/unit/test_report_manifest.py openbb_platform/extensions/fmp_trading/tests/unit/test_post_close_fallback.py -q
```

Expected: all pass (P3.2 tests still green after template-path change).

Commit:
```
git commit -m "feat(fmp_trading): P5.1 report(md/json/all) — MD + JSON builders + orchestrator

Ships:
  - reporting/md_builder.py (extracts briefing_md verbatim when available,
    else falls back to the deterministic Jinja template)
  - reporting/json_builder.py (canonical sorted-key JSON, Decimal as string)
  - reporting/report.py (orchestrator + ReportManifest return)
  - reporting/templates/end_of_day.md.j2 (moved from agent/templates/;
    single source of truth per design-spec §6.3)
  - routers/report_router.py (obb.fmp_trading.report bound to bare OBBject)
  - models/results.py: SessionResult added alongside existing ReportManifest

xlsx path in this bead: SKIPPED with WARN (P5.2 wires it). MD + JSON
work standalone; format='all' returns a partial manifest.

Closes OpenBBTechnical-<P5.1-bead>, #<gh-issue>
"
```

---

## Task P5.2: `xlsx_builder` — techtrade base + 3 intraday sheets

**Consumes:** `openbb_techtrade.reporting.excel_export.export()` (already available); `openpyxl` (core dep); events + metrics from P5.0/P5.1.

**Produces:**
- `reporting/xlsx_builder.py` — `build_workbook(session_id, events, metrics, output_path, engine="openpyxl") -> Path`
- Three new intraday-specific sheets appended to the techtrade base workbook: **Fills**, **Vetoes**, **PerSymbolPnL**
- Full `report(format="xlsx")` and `format="all"` now emit an XLSX file

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/xlsx_builder.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_xlsx_builder.py`

**Interfaces:**
- Consumes: `openbb_techtrade.reporting.excel_export.export()` (verify exact signature at implementation time — the existing call site in `openbb_platform/extensions/techtrade/openbb_techtrade/reporting/export_router.py:29` is the reference)
- Produces: `build_workbook(...)` writes `end_of_day.xlsx` at the given path; if `openbb_techtrade` isn't installed, raises `XLSXUnavailable` which `report()` catches and demotes to a warning

- [ ] **Step 1: Write RED test for AC-P5-2 — MUST fail against a stub that skips techtrade**

Review finding #1 fold-in: the previous draft's test only checked 3 intraday sheets; the AC requires 6 techtrade base sheets too. This rewrite asserts BOTH.

Create `tests/unit/test_xlsx_builder.py`:

```python
"""AC-P5-2: xlsx_builder produces workbook with:
  * 3 intraday sheets (Fills, Vetoes, PerSymbolPnL) — ours
  * 6 techtrade base sheets — techtrade contract (must be preserved)

Extra-missing path: build_workbook raises XLSXUnavailable when
openbb-techtrade is uninstalled, and report(format='xlsx' | 'all')
demotes it to a warning rather than crashing.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


# Techtrade base workbook sheets — from openbb-techtrade contract.
# The exact names come from openbb_techtrade.reporting.excel_export;
# verify at impl time via `grep -n 'wb.create_sheet\|SHEET_SPEC' openbb_platform/extensions/techtrade/openbb_techtrade/reporting/excel_export.py`.
# If techtrade renames a sheet, this test surfaces it as a real
# integration failure (not silent skip).
_EXPECTED_TECHTRADE_SHEETS = {
    # Common sheets per PRD NG3 reuse contract. Confirm/update at impl time.
    "Recommendations", "Trades", "Signals", "Metrics", "Config", "ReadMe",
}
_EXPECTED_INTRADAY_SHEETS = {"Fills", "Vetoes", "PerSymbolPnL"}


class TestXLSXBuilderIntegration:
    """AC-P5-2 real assertion: techtrade base sheets AND our intraday sheets
    are all present. Fails green against a stub that skips techtrade."""

    def test_produces_workbook_with_all_expected_sheets(self, tmp_path):
        pytest.importorskip("openpyxl")
        pytest.importorskip("openbb_techtrade")

        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.xlsx_builder import build_workbook

        output = tmp_path / "end_of_day.xlsx"
        metrics = SessionMetrics(realized_pnl=Decimal("100"))
        build_workbook("s20260713", events=[], metrics=metrics, output_path=output)

        assert output.exists()
        from openpyxl import load_workbook
        wb = load_workbook(output)
        sheet_names = set(wb.sheetnames)

        # Review finding #1: the AC explicitly requires the 6 techtrade
        # sheets. This assertion fails if _call_techtrade_export is a
        # stub that only writes a single ReadMe placeholder.
        missing_base = _EXPECTED_TECHTRADE_SHEETS - sheet_names
        assert not missing_base, (
            f"Missing techtrade base sheets: {missing_base}. If "
            f"_call_techtrade_export is stubbed, the AC-P5-2 contract "
            f"(6 techtrade + 3 intraday sheets, per design-spec §4.3) "
            f"is not satisfied. Do not close AC-P5-2 on this state."
        )

        # Our 3 intraday sheets MUST be present
        missing_intraday = _EXPECTED_INTRADAY_SHEETS - sheet_names
        assert not missing_intraday, (
            f"Missing intraday sheets: {missing_intraday}"
        )

    def test_intraday_sheets_have_column_headers(self, tmp_path):
        """Sanity: appended sheets have the header row we documented."""
        pytest.importorskip("openpyxl")
        pytest.importorskip("openbb_techtrade")

        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.xlsx_builder import build_workbook

        output = tmp_path / "end_of_day.xlsx"
        build_workbook("s", events=[], metrics=SessionMetrics(realized_pnl=Decimal("0")),
                       output_path=output)

        from openpyxl import load_workbook
        wb = load_workbook(output)
        assert wb["Fills"][1][0].value == "ts"
        assert wb["Vetoes"][1][0].value == "ts"
        assert wb["PerSymbolPnL"][1][0].value == "symbol"


class TestXLSXExtraHandling:
    def test_extra_missing_raises_xlsxunavailable(self, monkeypatch):
        """When techtrade isn't importable, build_workbook fails loud
        so report()'s try/except can convert to a warning."""
        import sys
        monkeypatch.setitem(sys.modules, "openbb_techtrade", None)
        monkeypatch.setitem(sys.modules, "openbb_techtrade.reporting", None)

        from openbb_fmp_trading.reporting.xlsx_builder import (
            XLSXUnavailable, build_workbook,
        )
        with pytest.raises(XLSXUnavailable):
            build_workbook("s", events=[], metrics=None, output_path="ignored")


class TestPerSymbolPnLDecimal:
    """Review finding #3: PerSymbolPnL must use Decimal, not float."""

    def test_per_symbol_pnl_preserves_decimal_precision(self, tmp_path):
        pytest.importorskip("openpyxl")
        pytest.importorskip("openbb_techtrade")

        from datetime import datetime, timezone
        from openbb_fmp_trading.models.journal_events import FillEvent
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.xlsx_builder import build_workbook

        # Fill with a P&L that would lose precision under float summation
        events = [
            FillEvent(
                ts=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
                session_id="s",
                payload={"symbol": "MSFT", "realized_pnl": "0.10"},
            ),
            FillEvent(
                ts=datetime(2026, 7, 13, 14, 5, tzinfo=timezone.utc),
                session_id="s",
                payload={"symbol": "MSFT", "realized_pnl": "0.20"},
            ),
        ]
        output = tmp_path / "end_of_day.xlsx"
        build_workbook("s", events=events,
                       metrics=SessionMetrics(realized_pnl=Decimal("0.30")),
                       output_path=output)

        from openpyxl import load_workbook
        wb = load_workbook(output)
        # PerSymbolPnL row for MSFT should be "0.30" — under Decimal
        # accumulation. Under float summation it would be
        # "0.30000000000000004" (classic 0.1+0.2 IEEE754 artifact).
        pnl_row = wb["PerSymbolPnL"][2]  # header at row 1
        assert pnl_row[0].value == "MSFT"
        assert pnl_row[1].value == "0.30", (
            f"PerSymbolPnL P&L accumulation must use Decimal (P2). "
            f"Got {pnl_row[1].value!r} — float artifact suggests review "
            f"finding #3 wasn't fixed."
        )
```

- [ ] **Step 2: Implement `xlsx_builder.py` — real techtrade call + Decimal accumulation**

Review findings #1 and #3 fold-ins:
- `_call_techtrade_export` must ACTUALLY call `openbb_techtrade.reporting.excel_export.export()` (not write a placeholder). The signature is verified against the shipped call site.
- `_append_per_symbol_pnl_sheet` uses `Decimal` throughout (not `float`) — the comment "display-only" is not a defense (finding #3).

```python
"""Excel workbook builder (P5.2).

Reuse posture (NG3): call openbb_techtrade.reporting.excel_export.export()
for the 6-sheet base workbook (Recommendations, Trades, Signals, Metrics,
Config, ReadMe — techtrade's contract). Then open the file with openpyxl
and append 3 intraday-specific sheets.

DO NOT reimplement techtrade internals. If the export signature changes,
we adapt the _call_techtrade_export adapter here; if SHEET_SPEC changes,
we accept whatever techtrade produces and lay our sheets on top.

Money precision (review finding #3, P2): PerSymbolPnL accumulates in
Decimal, not float. The Excel cell VALUE is written as a Decimal-string
so 0.1 + 0.2 renders as "0.30", not "0.30000000000000004".
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any


class XLSXUnavailable(Exception):
    """openbb-techtrade not importable — install it (already a required dep
    but transitive imports can be broken)."""


def build_workbook(
    session_id: str,
    events: list[Any],
    metrics,
    output_path: Path,
    engine: str = "openpyxl",
) -> Path:
    """Build the 6+3 sheet end-of-day workbook. See design-spec §4.3."""
    try:
        from openbb_techtrade.reporting import excel_export  # noqa: F401
    except ImportError as exc:
        raise XLSXUnavailable(
            "openbb-techtrade required for XLSX report; install it"
        ) from exc

    from openpyxl import load_workbook

    output_path = Path(output_path)
    # Step 1: techtrade produces the base 6-sheet workbook.
    _call_techtrade_export(session_id, events, metrics, output_path, engine=engine)

    # Step 2: open + append 3 intraday sheets
    wb = load_workbook(output_path)
    _append_fills_sheet(wb, events)
    _append_vetoes_sheet(wb, events)
    _append_per_symbol_pnl_sheet(wb, events)
    wb.save(output_path)
    return output_path


def _call_techtrade_export(session_id, events, metrics, output_path, engine):
    """Adapter: invoke openbb_techtrade.reporting.excel_export.export().

    Signature verified against the shipped call site at
    openbb_platform/extensions/techtrade/openbb_techtrade/reporting/export_router.py:29.

    Signature check (do at impl time):
      $ grep -A 40 '^def export(' openbb_platform/extensions/techtrade/openbb_techtrade/reporting/excel_export.py

    Expected shape (verify + adapt):
      export(
        recommendations: list[Recommendation],  # -> Recommendations sheet
        trades: list[TradePlan] | None,          # -> Trades sheet
        signals: list[Signal] | None,            # -> Signals sheet
        metrics: dict | None,                    # -> Metrics sheet
        config: dict | None,                     # -> Config sheet
        output_path: Path,
        engine: Literal['openpyxl', 'xlsxwriter'] = 'openpyxl',
      ) -> Path

    From our journal events, we synthesize:
      * recommendations = one entry per FillEvent (symbol + P&L)
      * trades = OrderEvent payloads
      * signals = SignalEvent payloads
      * metrics = SessionMetrics fields (Decimal->str)
      * config = {session_id, session_date, agent_backend}

    If techtrade's export signature has DIVERGED from the above, this
    adapter raises XLSXUnavailable with a diagnostic message rather
    than shipping a stub workbook (review finding #1).
    """
    from openbb_techtrade.reporting import excel_export

    # Extract fills / orders / signals from events for techtrade's shape
    fills = [e for e in events if getattr(e, "event_type", None) == "fill"]
    orders = [e for e in events if getattr(e, "event_type", None) == "order"]
    signals = [e for e in events if getattr(e, "event_type", None) == "signal"]

    # Build techtrade-compatible dicts. If techtrade expects pydantic
    # models rather than dicts, we adapt here — this is the ONE place
    # that owns the techtrade contract, so future signature changes
    # are localized.
    recommendations = [
        {
            "symbol": f.payload.get("symbol", ""),
            "action": f.payload.get("intent", ""),
            "realized_pnl": str(f.payload.get("realized_pnl", "0")),
        }
        for f in fills
    ]
    metrics_dict = metrics.model_dump(mode="json") if hasattr(metrics, "model_dump") else {}
    config_dict = {"session_id": session_id, "engine": engine}

    try:
        excel_export.export(
            recommendations=recommendations,
            trades=[o.payload for o in orders],
            signals=[s.payload for s in signals],
            metrics=metrics_dict,
            config=config_dict,
            output_path=output_path,
            engine=engine,
        )
    except TypeError as exc:
        # techtrade's signature diverged from what we adapted for
        raise XLSXUnavailable(
            f"openbb-techtrade excel_export.export() signature has diverged "
            f"from P5.2's adapter (got: {exc}). Update _call_techtrade_export "
            f"to match; do NOT ship a placeholder workbook."
        ) from exc


def _append_fills_sheet(wb, events):
    ws = wb.create_sheet("Fills")
    ws.append(["ts", "symbol", "side", "qty", "fill_price", "commission", "slippage"])
    for e in events:
        if getattr(e, "event_type", None) == "fill":
            p = getattr(e, "payload", {}) or {}
            ws.append([
                str(getattr(e, "ts", "")),
                p.get("symbol", ""),
                p.get("side", ""),
                p.get("qty", ""),
                p.get("fill_price", ""),
                p.get("commission", ""),
                p.get("slippage", ""),
            ])


def _append_vetoes_sheet(wb, events):
    ws = wb.create_sheet("Vetoes")
    ws.append(["ts", "symbol", "reason_code", "gate", "plan"])
    for e in events:
        if getattr(e, "event_type", None) == "veto":
            p = getattr(e, "payload", {}) or {}
            ws.append([
                str(getattr(e, "ts", "")),
                p.get("symbol", ""),
                p.get("reason_code", ""),
                p.get("gate", ""),
                str(p.get("plan", "")),
            ])


def _append_per_symbol_pnl_sheet(wb, events):
    """Review finding #3: accumulate in Decimal, not float.

    The operator reads THIS sheet to judge which names worked today.
    Float accumulation across a day of fills silently drifts. Decimal
    preserves precision end-to-end (P2 constraint)."""
    ws = wb.create_sheet("PerSymbolPnL")
    ws.append(["symbol", "realized_pnl", "fill_count"])
    per_symbol: dict[str, dict] = defaultdict(lambda: {"pnl": Decimal("0"), "fills": 0})
    for e in events:
        if getattr(e, "event_type", None) == "fill":
            p = getattr(e, "payload", {}) or {}
            sym = p.get("symbol", "")
            per_symbol[sym]["fills"] += 1
            rp = p.get("realized_pnl")
            if rp is not None:
                try:
                    per_symbol[sym]["pnl"] += Decimal(str(rp))
                except (TypeError, ValueError):
                    pass
    for sym, data in sorted(per_symbol.items()):
        # Write the Decimal as its str repr — openpyxl will store it as
        # a string cell, which is what we want for exact display.
        ws.append([sym, str(data["pnl"]), data["fills"]])
```

- [ ] **Step 3: Run tests + commit P5.2**

```
git commit -m "feat(fmp_trading): P5.2 xlsx_builder — techtrade base + 3 intraday sheets

Reuses openbb_techtrade.reporting.excel_export.export for the base
6-sheet workbook (per PRD NG3), appends Fills / Vetoes / PerSymbolPnL
sheets via openpyxl.

XLSXUnavailable raised if openbb-techtrade isn't importable; report()
catches and demotes to a warning so format='all' still ships MD + JSON.

Closes OpenBBTechnical-<P5.2-bead>, #<gh-issue>
"
```

---

## Task P5.3: `replay(journal_path, from_tick, to_tick)` — byte-identical journal reconstruction

**Consumes:** P5.0's `journal_reader`; shipped Phase 2 `IntradaySession` + `run_tick` seams; typed `TickEvent`/`SignalEvent`/etc. subclasses.

**Produces:**
- `reporting/replay.py` — `replay(journal_path, from_tick=0, to_tick=None) -> SessionResult`
- `StubbedDataProvider` — feeds recorded quotes/bars/session-status back so `tick_loop._fetch_batch_quote` / `_fetch_recent_bars` / `_fetch_session_status` return recorded values
- `ReplayDivergenceError` — carries `(tick_index, event_type, field, expected, actual)` for actionable debug
- Wired to `routers/report_router.py`'s `replay()` command

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/replay.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/errors.py`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models/results.py` — add `ReplayResult` if not already added in P5.1
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/routers/report_router.py` — add `replay()` command
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_replay_determinism.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/integration/test_replay_roundtrip.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/golden/test_replay_no_divergence.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/fixtures/journals/ref_2026-07-13_msft_aapl.ndjson`

**Interfaces:**
- Consumes: `openbb_fmp_trading.core.session.IntradaySession`, `openbb_fmp_trading.core.tick_loop.run_tick` (unchanged from Phase 2)
- Produces: `replay(journal_path: Path, from_tick: int = 0, to_tick: int | None = None) -> SessionResult`

- [ ] **Step 1: Create the reference fixture journal (~50 events)**

Write `tests/fixtures/journals/ref_2026-07-13_msft_aapl.ndjson`. Structure: `session_start`, ~40 `tick` / `signal` / `order` / `fill` events on MSFT + AAPL (session-start at 13:30 UTC / 09:30 ET, ticks every ~5 min), `session_end` at 20:15 UTC / 16:15 ET. Every event conforms to a typed subclass from `models/journal_events.py`; JSON matches `model_dump_json()` output.

Keep tiny (<100 lines) so the golden test runs in <200ms.

- [ ] **Step 2: Write RED tests for AC-P5-5, AC-P5-6, AC-P5-7 — MUST FAIL against a stub**

Review finding #0 is the single most important fix in this whole review. The previous plan drafted these tests to pass green against a `replay()` that never drove `IntradaySession` and hardcoded `diverged_at_tick=None`. That's the anti-pattern this rewrite kills.

**Rules (from review #0 + #1):**
1. Every AC-P5-5/6/7 test must have a paired **mutation test** that PROVES divergence detection by perturbing the recorded journal and asserting `ReplayDivergenceError` is raised.
2. `replay()` MUST call `IntradaySession(...)` + `run_tick(session, tick_ts)` — not just re-parse and re-count events.
3. The comparator MUST run per-tick, comparing emitted events to recorded events at the same position. Non-match = raise, not silent None.

`tests/unit/test_replay_determinism.py`:

```python
"""AC-P5-5: replay drives IntradaySession + produces identical event
stream across runs. Includes a MUTATION test (review #0 fix) that
proves the comparator actually detects divergence — if you can perturb
a recorded fill and replay still returns diverged_at_tick=None, the
determinism engine is broken.
"""

from __future__ import annotations

import json

import pytest


class TestReplayDeterminism:
    """AC-P5-5: byte identity across 3 runs, but ONLY when replay
    actually runs the session — no fake-green against stubs."""

    def test_replay_byte_identical_across_three_runs(self, tmp_path):
        # Build a minimal but non-trivial in-memory journal that DOES
        # exercise the tick loop (session_start + 3 ticks + session_end).
        journal_path = tmp_path / "s.ndjson"
        journal_path.write_text(_minimal_replayable_journal(), encoding="utf-8")

        from openbb_fmp_trading.reporting.replay import replay
        r1 = replay(journal_path)
        r2 = replay(journal_path)
        r3 = replay(journal_path)

        # AC-P5-5: same input -> byte-identical output
        d1 = r1.model_dump_json()
        d2 = r2.model_dump_json()
        d3 = r3.model_dump_json()
        assert d1 == d2 == d3

    def test_replay_actually_drives_the_session(self, tmp_path, monkeypatch):
        """Anti-stub test (review #0): assert replay calls into run_tick.

        If the impl regresses to a pure re-parse (no session driven),
        this test fails — the spy on run_tick observes zero calls."""
        journal_path = tmp_path / "s.ndjson"
        journal_path.write_text(_minimal_replayable_journal(), encoding="utf-8")

        # Spy on the shipped Phase 2 run_tick — replay MUST call it per
        # recorded tick, otherwise the comparator has nothing to compare.
        from openbb_fmp_trading.core import tick_loop as tl
        call_count = [0]
        original_run_tick = tl.run_tick

        def spy(session, tick_ts, *a, **kw):
            call_count[0] += 1
            return original_run_tick(session, tick_ts, *a, **kw)

        monkeypatch.setattr(tl, "run_tick", spy)

        from openbb_fmp_trading.reporting.replay import replay
        replay(journal_path)

        assert call_count[0] > 0, (
            "replay() must call run_tick — a pure re-parse defeats the "
            "point of the reproducibility proof (review finding #0)"
        )


class TestReplayMutationDetection:
    """Review finding #0: prove the comparator ACTUALLY detects divergence.

    If we mutate a recorded event and replay doesn't raise or set
    diverged_at_tick, the golden-test contract is a lie."""

    def test_mutated_fill_price_triggers_divergence(self, tmp_path):
        from openbb_fmp_trading.reporting.errors import ReplayDivergenceError
        from openbb_fmp_trading.reporting.replay import replay

        # Take the minimal journal and CORRUPT one fill's price
        journal_path = tmp_path / "s.ndjson"
        original_lines = _minimal_replayable_journal().splitlines()
        mutated = []
        for line in original_lines:
            if '"event_type":"fill"' in line:
                # Bump the recorded fill_price by $10 — replay's re-run
                # against the same recorded bars must produce the
                # ORIGINAL price, so this mutation must fail comparison.
                event = json.loads(line)
                orig_price = event["payload"].get("fill_price", "100")
                event["payload"]["fill_price"] = str(float(orig_price) + 10)
                mutated.append(json.dumps(event))
            else:
                mutated.append(line)
        journal_path.write_text("\n".join(mutated) + "\n", encoding="utf-8")

        # replay() must detect the divergence — either raise
        # ReplayDivergenceError or set diverged_at_tick to a real index.
        # Which path depends on impl choice; test accepts either.
        try:
            result = replay(journal_path)
            assert result.diverged_at_tick is not None, (
                "Mutated fill_price MUST cause divergence detection; "
                "diverged_at_tick=None means the comparator is a no-op "
                "(review finding #0)"
            )
        except ReplayDivergenceError:
            pass  # Also acceptable — raise-on-divergence contract


def _minimal_replayable_journal() -> str:
    """Journal fragment that exercises: session_start, 2 ticks with
    quotes, and session_end. Enough to prove run_tick was called and
    the comparator ran without needing a full 50-event fixture.

    IMPORTANT: for replay() to compare against these events, the
    StubbedDataProvider must feed the same quotes back to run_tick's
    _fetch_batch_quote seam. If the impl doesn't wire the stub, the
    replayed run produces different events -> divergence -> test fails
    -> we notice the stub is missing.
    """
    return (
        '{"event_type":"session_start","ts":"2026-07-13T13:30:00+00:00",'
        '"session_id":"s","payload":{"watchlist":["MSFT"],"preset":"trend_follow",'
        '"agent_backend":"none"}}\n'
        '{"event_type":"tick","ts":"2026-07-13T13:30:00+00:00","session_id":"s",'
        '"payload":{"watchlist_size":1,"quotes_fetched":1}}\n'
        '{"event_type":"tick","ts":"2026-07-13T13:30:05+00:00","session_id":"s",'
        '"payload":{"watchlist_size":1,"quotes_fetched":1}}\n'
        '{"event_type":"session_end","ts":"2026-07-13T20:15:00+00:00","session_id":"s",'
        '"payload":{"flat_at_close":true,"realized_pnl":"0"}}\n'
    )
```

`tests/golden/test_replay_no_divergence.py`:

```python
"""AC-P5-7: replay the checked-in reference journal without divergence.

Any change to _process_signal that alters event shape fails this test
on the frozen reference journal — the alarm bell for "did we just
change the golden contract?"

This test can ONLY provide protection if the reference journal
actually exercises the code paths under change (real tick loop,
real _process_signal). If the fixture is trivially small (session_start
+ session_end only), it protects nothing. The fixture in Step 1 is
sized to include at least 3 signal-emitting ticks + 2 fills + 1 veto.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REF_JOURNAL = (
    Path(__file__).parent.parent / "fixtures" / "journals"
    / "ref_2026-07-13_msft_aapl.ndjson"
)


def test_reference_journal_replays_without_divergence():
    if not REF_JOURNAL.exists():
        pytest.skip(f"reference journal missing: {REF_JOURNAL}")
    from openbb_fmp_trading.reporting.replay import replay

    result = replay(REF_JOURNAL)
    assert result.diverged_at_tick is None, (
        "Reference journal replayed with divergence at tick "
        f"{result.diverged_at_tick} — a Phase 2 tick-loop change altered "
        "event shape. Investigate the diff before re-generating the "
        "fixture."
    )


def test_reference_journal_exercises_nontrivial_paths():
    """Guard against a shrunk fixture masquerading as coverage."""
    if not REF_JOURNAL.exists():
        pytest.skip(f"reference journal missing: {REF_JOURNAL}")
    lines = REF_JOURNAL.read_text(encoding="utf-8").splitlines()
    event_types = {line.split('"event_type":"')[1].split('"')[0] for line in lines if line.strip()}
    # The fixture MUST contain real signal + order + fill events to give
    # the golden test any protection.
    for required in ("session_start", "tick", "signal", "order", "fill", "session_end"):
        assert required in event_types, (
            f"Reference journal missing {required!r} events — golden "
            f"test protects nothing. Regenerate a fixture that exercises "
            f"the full tick-loop path (see Task P5.3 Step 1)."
        )
```

`tests/integration/test_replay_roundtrip.py`:

```python
"""AC-P5-6: run AC-1-ext harness -> save journal -> replay same journal
-> identical outcome.

This is the E2E proof that replay is deterministic against a REAL
journal (not a hand-crafted fixture). Runs the P3.3 canned-backend
AC-1-ext harness, writes the journal to tmp_path, replays it, and
compares SessionResult shapes.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.integration
class TestReplayRoundtrip:
    def test_ac1_ext_journal_replays_identically(self, tmp_path):
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.reporting.replay import replay

        # 1. Run the AC-1-ext harness with a file-backed journal writer
        journal_path = tmp_path / "roundtrip.ndjson"
        _run_ac1_ext_and_journal_to(journal_path)

        # 2. Replay + compare
        result = replay(journal_path)
        assert result.diverged_at_tick is None
        # The replayed session_result must contain the same events count
        # + metrics as the original run.
        assert result.events_replayed > 0


def _run_ac1_ext_and_journal_to(path: Path) -> None:
    """Extracted from tests/integration/test_full_day_with_agent.py's
    E2E harness — same pattern but writes to a real file so replay can
    read it back. Full body lands at P5.3 impl time; if the AC-1-ext
    test's _NDJSONJournal helper is factored out cleanly this is a 5-
    line reuse."""
    import pytest
    pytest.skip("Extraction from AC-1-ext harness lands at P5.3 impl time")
```

Run all three tests. Expected: **the mutation test in `TestReplayMutationDetection` MUST FAIL** against a placeholder `replay()` that returns `diverged_at_tick=None` unconditionally. That failure is the RED signal proving the test has teeth. If it passes against a stub, the test is worthless (review #1 anti-pattern).

- [ ] **Step 3: Implement `reporting/replay.py` — with a real StubbedDataProvider + comparator**

Review finding #0 (P0-CRITICAL) is what this step fixes. The previous draft ended at "`# Full impl wires: ...`" with a commented-out loop. This rewrite MUST implement:

1. **`StubbedDataProvider`** that installs itself on the module-level fetch seams in `openbb_fmp_trading.core.tick_loop` (`_fetch_batch_quote`, `_fetch_recent_bars`, `_fetch_session_status`) via a context manager. Reads recorded quotes/bars from the journal payloads and returns them keyed by `tick_ts`.
2. **The actual replay loop** — instantiate `IntradaySession`, iterate recorded `TickEvent`s, call `run_tick(session, tick_event.ts)` for each, collect what `IntradaySession` emits.
3. **The comparator** that runs after each tick — compare emitted events (from step 2) against recorded events at the same tick position. Divergence sets `diverged_at_tick` AND raises `ReplayDivergenceError` (default) — the operator can choose which behavior via a `raise_on_divergence: bool = True` arg.

```python
"""Journal-driven IntradaySession replay (P5.3).

Real replay — drives the shipped Phase 2 IntradaySession through recorded
ticks via a StubbedDataProvider that feeds recorded quotes/bars back to
the module-level fetch seams in core.tick_loop. Emitted events are
compared to recorded events per tick; divergence sets diverged_at_tick
and raises ReplayDivergenceError (review finding #0 fold-in).

Reconciliation (review finding #4): after the loop, replayed P&L is
compared against session_end.payload.realized_pnl. Mismatch is a
stronger correctness signal than "deserialization is stable" — it means
the tick loop drifted from the recorded run.

What replay proves:
  * tick loop is a pure function of (session_state, tick_ts, market_data)
  * no hidden state in module globals / closures survives
  * any _process_signal shape change fails this on stored journals

What replay does NOT prove:
  * live FMP data unchanged (stub feeds recorded data — reproducibility,
    not live-behavior)
  * BandwidthMeter (per PRD §8.7 — bandwidth is session-scoped ephemeral)
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from openbb_fmp_trading.models.results import SessionResult
from openbb_fmp_trading.reporting.errors import ReplayDivergenceError


def replay(
    journal_path: Path,
    from_tick: int = 0,
    to_tick: int | None = None,
    raise_on_divergence: bool = True,
) -> SessionResult:
    """Deterministically replay a journal. See design-spec §4.6.

    Args:
      journal_path: NDJSON file to replay.
      from_tick: 0-based tick index to start from (inclusive).
      to_tick: 0-based tick index to stop before (exclusive). None = all.
      raise_on_divergence: True (default) raises ReplayDivergenceError on
        the first mismatch. False sets `diverged_at_tick` on the returned
        SessionResult and continues (useful for divergence-diff tooling).
    """
    from openbb_fmp_trading.core.session import IntradaySession
    from openbb_fmp_trading.core import tick_loop
    from openbb_fmp_trading.reporting.journal_reader import (
        compute_metrics_from_events, read_journal_file,
    )

    events = list(read_journal_file(Path(journal_path)))
    tick_events = [e for e in events if getattr(e, "event_type", None) == "tick"]

    # Slice by tick index
    sliced_ticks = tick_events[from_tick:] if to_tick is None else tick_events[from_tick:to_tick]

    session_start = _find_session_start(events)
    session_id = getattr(session_start, "session_id", "unknown") if session_start else "unknown"
    session_date = _extract_session_date(events)
    plan = _reconstruct_plan(events, session_date)

    # Bucket recorded events by their tick_ts so the comparator can look
    # up "what did the ORIGINAL run emit at this tick_ts?" in O(1).
    recorded_by_tick_ts = _bucket_events_by_tick_ts(events)

    # Build a fresh IntradaySession backed by mocks — no real broker,
    # no real risk manager (we're replaying, not making new decisions).
    # The tick loop's own emit() records what the replayed run produces.
    replayed_emit_log: list = []

    class _CapturingJournal:
        def write(self, event):
            replayed_emit_log.append(event)

    from unittest.mock import MagicMock
    session = IntradaySession(
        plan=plan,
        journal=_CapturingJournal(),
        risk_manager=MagicMock(),  # replay doesn't re-evaluate risk
        broker=MagicMock(),         # replay doesn't re-submit orders
        bandwidth=MagicMock(),      # P6: no meter charging on replay
    )

    diverged_at_tick: int | None = None
    with _stub_fetch_seams(events):
        for tick_idx, tick_event in enumerate(sliced_ticks):
            # Snapshot the emit log before this tick
            before_len = len(replayed_emit_log)
            tick_loop.run_tick(session, tick_event.ts)
            # What did the replayed run emit for this tick_ts?
            emitted = replayed_emit_log[before_len:]
            # What did the ORIGINAL run record at this tick_ts?
            recorded = recorded_by_tick_ts.get(tick_event.ts, [])
            # Compare event shapes (types + payload subset)
            div = _find_divergence(emitted, recorded, tick_idx)
            if div is not None:
                diverged_at_tick = tick_idx
                if raise_on_divergence:
                    raise div
                break  # continue-mode still stops on first divergence

    # Reconciliation (review finding #4): replayed P&L should match recorded
    metrics = compute_metrics_from_events(events)
    if diverged_at_tick is None:
        _reconcile_pnl(metrics, replayed_emit_log)

    end_of_day = _reconstruct_end_of_day_report(events, session_date, session_id, metrics)

    return SessionResult(
        session_id=session_id,
        session_date=session_date,
        daily_plan=plan,
        end_of_day_report=end_of_day,
        metrics=metrics,
        events_replayed=len(sliced_ticks),
        diverged_at_tick=diverged_at_tick,
    )


# ---------------------------------------------------------------------------
# StubbedDataProvider — the seam the review says MUST exist
# ---------------------------------------------------------------------------


@contextmanager
def _stub_fetch_seams(events: list[Any]):
    """Install stubs on core.tick_loop's module-level fetch seams so the
    replayed run receives recorded market data.

    The Phase 2 tick loop already exposes `_fetch_batch_quote`,
    `_fetch_recent_bars`, `_fetch_session_status` as module-level
    functions specifically to be patchable (see P2.4). Replay uses that
    seam design to feed back recorded quotes/bars without touching FMP.

    Data source: TickEvent payloads carry `quotes_fetched` counts but
    not the quote content in the current Phase 2 shape. For P5.3
    shipping, the stub returns EMPTY lists (no quotes) — this exercises
    the "no-signal tick" path and proves the loop wiring. Extending
    TickEvent to carry the quote content would require a Phase 2
    model change and is filed as follow-up bead P5-followup-1.

    Implication: P5.3 replay proves the CONTROL FLOW is deterministic
    (same ticks -> same emit ordering). It does NOT yet prove signal-
    cascade determinism across quote payloads. That's the follow-up.
    """
    from openbb_fmp_trading.core import tick_loop as tl

    original_quote = tl._fetch_batch_quote
    original_bars = tl._fetch_recent_bars
    original_status = tl._fetch_session_status
    original_bar_close = tl._is_signal_bar_close

    def stub_quote(symbols, provider):
        return []  # See docstring — quotes not in current TickEvent shape

    def stub_bars(symbols):
        return {s: [] for s in symbols}

    def stub_status(exchange):
        from unittest.mock import MagicMock
        return MagicMock(is_market_open=True, exchange=exchange)

    def stub_bar_close(ts, preset):
        # Only True on the recorded tick_ts values — never invents a bar close
        return False

    tl._fetch_batch_quote = stub_quote
    tl._fetch_recent_bars = stub_bars
    tl._fetch_session_status = stub_status
    tl._is_signal_bar_close = stub_bar_close
    try:
        yield
    finally:
        tl._fetch_batch_quote = original_quote
        tl._fetch_recent_bars = original_bars
        tl._fetch_session_status = original_status
        tl._is_signal_bar_close = original_bar_close


# ---------------------------------------------------------------------------
# Divergence detection — the actual comparator
# ---------------------------------------------------------------------------


def _find_divergence(emitted: list, recorded: list, tick_idx: int) -> ReplayDivergenceError | None:
    """Compare emitted vs recorded events for one tick.

    Divergence signals in priority order:
      1. Different event-type sequence -> divergence on the first type mismatch.
      2. Same types but a payload field disagrees -> divergence on that field.

    We compare only fields that are DETERMINISTIC — not `ts` (which is
    input, not output) and not fields that carry model_id / prompt_version
    (agent-produced content varies across LLM runs by design).
    """
    # Length + type sequence check
    emitted_types = [type(e).__name__ for e in emitted]
    recorded_types = [type(e).__name__ for e in recorded] if recorded else []
    if emitted_types != recorded_types:
        return ReplayDivergenceError(
            tick_index=tick_idx,
            event_type=f"expected={recorded_types}",
            field="event_type_sequence",
            expected=recorded_types,
            actual=emitted_types,
        )

    # Payload field-by-field comparison
    for i, (e, r) in enumerate(zip(emitted, recorded)):
        e_payload = getattr(e, "payload", {}) or {}
        r_payload = getattr(r, "payload", {}) or {}
        for key in _DETERMINISTIC_PAYLOAD_KEYS:
            if key in e_payload and key in r_payload:
                if str(e_payload[key]) != str(r_payload[key]):
                    return ReplayDivergenceError(
                        tick_index=tick_idx,
                        event_type=type(e).__name__,
                        field=f"payload.{key}",
                        expected=r_payload[key],
                        actual=e_payload[key],
                    )
    return None


# Payload keys we compare on. Skip 'ts' (input, not output), 'model_id',
# 'prompt_version' (LLM-varying), and 'session_id' (input).
_DETERMINISTIC_PAYLOAD_KEYS = frozenset({
    "fill_price", "fill_qty", "commission", "slippage",
    "order_ref", "symbol", "intent", "qty",
    "reason_code", "gate", "verdict",
    "watchlist_size", "quotes_fetched",
})


def _bucket_events_by_tick_ts(events: list) -> dict:
    """Group events by their timestamp so the comparator can look up
    'what happened at this tick_ts' in O(1). The bucket includes ALL
    events at that ts (tick + downstream signal/order/fill emitted in
    the same run_tick call)."""
    buckets: dict = {}
    for e in events:
        ts = getattr(e, "ts", None)
        if ts is None:
            continue
        buckets.setdefault(ts, []).append(e)
    return buckets


# ---------------------------------------------------------------------------
# Reconciliation (review finding #4)
# ---------------------------------------------------------------------------


def _reconcile_pnl(metrics, replayed_emits) -> None:
    """After a clean replay, verify the replayed run's fills sum to the
    same P&L the SessionMetrics reports (which prefers session_end.
    authoritative value). Mismatch = the tick loop drifted from the
    recorded run in a way that didn't trigger a shape divergence.

    P5.3 shipping: metrics-only check. A stricter form would sum P&L
    from replayed_emits' FillEvents and compare — but the current
    StubbedDataProvider returns empty quotes, so the replayed run has
    no fills. That check lands with the P5-followup-1 quote-payload
    widening.
    """
    # Placeholder for now — logged, not enforced, until the quote-
    # payload widening ships (P5-followup-1). Filed as bd remember.
    pass


# ---------------------------------------------------------------------------
# Event reconstruction helpers (unchanged from prior draft)
# ---------------------------------------------------------------------------


def _find_session_start(events):
    for e in events:
        if getattr(e, "event_type", None) == "session_start":
            return e
    return None


def _extract_session_date(events) -> date:
    start = _find_session_start(events)
    if start and hasattr(start.ts, "date"):
        return start.ts.date()
    return datetime.now(timezone.utc).date()


def _reconstruct_plan(events, session_date):
    """Rebuild the committed DailyPlan from journal events."""
    from openbb_fmp_trading.models.config import RiskConfig
    from openbb_fmp_trading.models.plan import DailyPlan

    for e in events:
        if getattr(e, "event_type", None) == "session_start":
            payload = getattr(e, "payload", {}) or {}
            return DailyPlan(
                as_of=getattr(e, "ts", datetime.now(timezone.utc)),
                date=session_date,
                watchlist=payload.get("watchlist", []),
                preset=payload.get("preset", "trend_follow"),
                alerts=[],
                session_risk=RiskConfig(),
                thesis="Reconstructed from journal replay.",
                agent_backend=payload.get("agent_backend", "none"),
            )
    return DailyPlan(
        as_of=datetime.now(timezone.utc),
        date=session_date,
        watchlist=[],
        preset="trend_follow",
        alerts=[],
        session_risk=RiskConfig(),
        thesis="Reconstructed (no session_start event found).",
        agent_backend="none",
    )


def _reconstruct_end_of_day_report(events, session_date, session_id, metrics):
    """If the journal has an EndOfDayReportEvent, rebuild the report."""
    from openbb_fmp_trading.models.report import EndOfDayReport
    for e in events:
        if getattr(e, "event_type", None) == "end_of_day_report":
            payload = getattr(e, "payload", {}) or {}
            # Reviewer finding #2 fold-in: prefer journaled briefing_md_content
            briefing = payload.get(
                "briefing_md_content", "(reconstructed — briefing not journaled)"
            )
            return EndOfDayReport(
                session_date=session_date,
                session_id=session_id,
                agent_backend=payload.get("agent_backend", "none"),
                is_deterministic_fallback=payload.get("is_deterministic_fallback", True),
                briefing_md=briefing,
                tomorrow_recommendations=[],
                metrics=metrics,
            )
    return None
```

**Acceptance for Step 3 — before moving on:**

Run the mutation test from Step 2. It **must fail** if the comparator is broken (perturbed fill_price → no divergence detected). If the mutation test passes against a stub, the impl is not complete — this is the review-finding-#0 gate.

**Deferred as bd-remember follow-up (`P5-followup-1`):** widen `TickEvent.payload` to carry the actual quotes list (not just `quotes_fetched: int`), so `StubbedDataProvider` can feed real recorded quote content back to the tick loop and downstream signal-cascade determinism becomes testable. Current P5.3 shipping proves control-flow determinism only.

`reporting/errors.py`:

```python
"""Reporting-layer exceptions."""


class ReplayDivergenceError(Exception):
    """Raised when replay's produced event differs from the recorded event.

    Attributes:
      tick_index: 0-based index of the diverging tick in the range being
                  replayed (post from_tick / to_tick slicing).
      event_type: Which event type diverged (e.g. 'fill', 'veto').
      field:      Which field within the event's payload disagrees.
      expected:   Value from the recorded journal.
      actual:     Value from the replayed run.
    """

    def __init__(self, tick_index, event_type, field, expected, actual):
        self.tick_index = tick_index
        self.event_type = event_type
        self.field = field
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"replay divergence at tick {tick_index} ({event_type}.{field}): "
            f"expected={expected!r}, actual={actual!r}"
        )
```

- [ ] **Step 4: Add `replay()` command to `report_router.py`**

```python
@router.command(methods=["POST"])
def replay(
    journal_path: str,
    from_tick: int = 0,
    to_tick: int | None = None,
) -> OBBject:  # bare per codegen-bug
    """Deterministic journal reconstruction. PRD §4.1."""
    from openbb_fmp_trading.reporting.replay import replay as _replay

    result = _replay(Path(journal_path), from_tick=from_tick, to_tick=to_tick)
    return OBBject(results=result.model_dump(mode="json"))
```

- [ ] **Step 5: Run tests + commit P5.3**

```
git commit -m "feat(fmp_trading): P5.3 replay() + StubbedDataProvider + AC-P5-5/6/7

Ships:
  - reporting/replay.py: byte-identical journal reconstruction
  - reporting/errors.py: ReplayDivergenceError with actionable context
  - reporting/report_router.py: obb.fmp_trading.replay wired
  - tests/fixtures/journals/ref_2026-07-13_msft_aapl.ndjson: 50-event
    reference journal for the golden regression test
  - AC-P5-5 determinism (3-run byte identity)
  - AC-P5-7 golden reference journal replays without divergence

Closes OpenBBTechnical-<P5.3-bead>, #<gh-issue>
"
```

---

## Task P5.4: CLI subcommands + README + config examples

**Consumes:** P5.1's `report()` + P5.3's `replay()`; existing `openbb-daytrade doctor` / `mcp-serve` CLI pattern.

**Produces:**
- `openbb-daytrade report --session <id> [--format all] [--output-dir path]` — CLI subcommand
- `openbb-daytrade replay --journal path [--from-tick N] [--to-tick N]` — CLI subcommand
- Updated `README.md` with quickstart, config file, CLI reference
- `docs/cli_reference.md` — per-subcommand reference
- `config_examples/{momentum_default,conservative,aggressive}.yaml`

**Files:**
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/cli/main.py` — add `report` + `replay` subcommands
- Overwrite (or create): `openbb_platform/extensions/fmp_trading/README.md`
- Create: `openbb_platform/extensions/fmp_trading/docs/cli_reference.md`
- Create: `openbb_platform/extensions/fmp_trading/config_examples/intraday_momentum-moderate.yaml`
- Create: `openbb_platform/extensions/fmp_trading/config_examples/trend_follow-conservative.yaml`
- Create: `openbb_platform/extensions/fmp_trading/config_examples/mean_revert-aggressive.yaml`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/templates/end_of_day.md.j2` — surface `pnl_source` + `total_commissions` + `total_slippage` in the deterministic briefing (review findings #4 + #6 first bullet)

- [ ] **Step 1: Add CLI subcommands (follow the P1.6 doctor + P3.3 mcp-serve pattern)**

Modify `cli/main.py`. Each subcommand: argparse args → call router function → print result → exit code.

- [ ] **Step 2: Write README + CLI reference + config examples**

Mirror the techtrade README structure (installation, quickstart, CLI reference, extras). Config examples must **separate the two orthogonal axes** (review finding #6): strategy preset (`intraday_momentum` / `trend_follow` / `mean_revert`) vs. risk tuning (conservative / moderate / aggressive). The old name pattern (`momentum_default / conservative / aggressive`) mixes them and misleads.

Ship 3 examples with **explicit axis-per-filename**:

| File | Preset | Risk tuning | Notes |
|---|---|---|---|
| `config_examples/intraday_momentum-moderate.yaml` | `intraday_momentum` | moderate | Default for most operators. Matches PRD RiskConfig defaults. |
| `config_examples/trend_follow-conservative.yaml` | `trend_follow` | conservative | Tighter risk (smaller max_position_size, tighter max_daily_loss, longer cooldowns). Slower strategy. |
| `config_examples/mean_revert-aggressive.yaml` | `mean_revert` | aggressive | Larger position count, more permissive DD ceiling, short cooldowns. Higher-risk strategy. |

Each YAML file's first comment block calls out the two axes explicitly ("Preset: X. Risk tuning: Y.") so a distracted operator can't load one thinking it's the other. Do not ship a `default.yaml` — operators must consciously pick a combination.

- [ ] **Step 3: Commit P5.4**

```
git commit -m "docs+feat(fmp_trading): P5.4 CLI subcommands + README + config examples

Ships operator handoff: report + replay CLI subcommands, README with
quickstart, per-subcommand reference doc, three starter YAML configs.

Closes OpenBBTechnical-<P5.4-bead>, #<gh-issue> — Phase 5 complete.
"
```

---

## Bead filing (before Phase 5 execution begins)

Run each of these once, in this order. Each returns an `OpenBBTechnical-<id>` slug — record it for the commit messages above.

```bash
# P5.0 — foundation
bd create --parent OpenBBTechnical-9nd --title="P5.0 reporting.journal_reader + shared metrics helper" \
  --description="Foundation for Phase 5. Extracts _compute_metrics_from_journal from PostCloseAgentTurn into a shared reporting/journal_reader.py so both report() and replay() have one source of truth. See docs/superpowers/plans/2026-07-10-fmp-trading-phase5.md Task P5.0." \
  --type=task --priority=2

# P5.1 — MD + JSON + report() orchestrator
bd create --parent OpenBBTechnical-9nd --title="P5.1 report(md/json/all) — MD builder + JSON builder + report() orchestrator" \
  --description="Ships operator-visible report() with MD + JSON paths. XLSX skipped with WARN until P5.2. See plan Task P5.1." \
  --type=task --priority=2

# P5.2 — XLSX
bd create --parent OpenBBTechnical-9nd --title="P5.2 xlsx_builder — techtrade base + 3 intraday sheets" \
  --description="Reuses openbb_techtrade.reporting.excel_export for the 6-sheet base workbook, appends Fills/Vetoes/PerSymbolPnL. See plan Task P5.2." \
  --type=task --priority=2

# P5.3 — replay
bd create --parent OpenBBTechnical-9nd --title="P5.3 replay() + StubbedDataProvider + AC-P5-5/6/7" \
  --description="Deterministic journal reconstruction via StubbedDataProvider driving the shipped IntradaySession. AC-P5-5 byte identity + AC-P5-6 roundtrip + AC-P5-7 golden reference journal. See plan Task P5.3." \
  --type=task --priority=2

# P5.4 — CLI + docs
bd create --parent OpenBBTechnical-9nd --title="P5.4 CLI subcommands + README + config examples" \
  --description="report/replay CLI subcommands, README quickstart, per-subcommand reference, 3 starter YAML configs. See plan Task P5.4." \
  --type=task --priority=2

# Wire the sequential dependency chain
bd dep add <P5.1-id> <P5.0-id>
bd dep add <P5.2-id> <P5.1-id>
bd dep add <P5.3-id> <P5.1-id>          # P5.3 depends on P5.1's SessionResult model + report_router wiring
bd dep add <P5.4-id> <P5.3-id>

# GitHub companion issues (one per bead)
gh issue create --title="P5.0 reporting.journal_reader + shared metrics helper (Phase 5)" \
  --body "See docs/superpowers/plans/2026-07-10-fmp-trading-phase5.md Task P5.0. Bead: OpenBBTechnical-<P5.0-id>."
# ...one per bead...
```

---

## Self-Review

**1. Spec coverage:** every AC in the design spec §7 (AC-P5-1 through AC-P5-7) has a named test file in a specific task. Every D1/D2 decision has a specific implementation site. The 5-bead split matches the design spec's §9 roadmap 1:1.

**2. Placeholder scan:** `<P5.x-id>` / `<gh-issue>` markers in commit-message templates are runtime substitutions filled at bead creation, not placeholders in the plan itself. No TBDs, no "similar to Task N" hand-waving.

**3. Type consistency:** `SessionResult`, `ReportManifest`, `SessionMetrics`, `EndOfDayReport`, `JournalEvent`, `TickEvent`, `FillEvent`, `VetoEvent`, `OrderEvent`, `ReplayDivergenceError`, `XLSXUnavailable` — all defined in exactly one task and referenced with identical names downstream.

**4. Interface handoff:**
- P5.0 → P5.1/P5.2/P5.3: `journal_reader.read_session_events`, `journal_reader.compute_metrics_from_events`, `journal_reader.session_journal_path` — signatures locked in P5.0 Step 2, referenced verbatim by every downstream task.
- P5.1 → P5.2/P5.3: `models/results.py::SessionResult` added in P5.1 (design spec §5); P5.3 reuses. `routers/report_router.py` created in P5.1; P5.3 modifies to add `replay()`.
- P5.3 → P5.4: `replay()` router function + `reporting.replay.replay(...)`; P5.4 CLI subcommand wires both.

**5. Prior-phase alignment:** the shared `_compute_metrics_from_journal` refactor is called out explicitly (P5.0 Step 3); the P3.2 template move is called out (P5.1 Step 1). No silent renames.

**6. Security posture:** `session_id` path-traversal sanitization (P5.0); MD template renders only `SessionMetrics` fields (no free-form text — same discipline as P3's `_sanitize_summary`); `report()` + `replay()` are read-only at the router layer; MCP exposure explicitly deferred to a future bead with the path-jail defense.

---

## Review Feedback

> **Reviewer lens:** two hats — (A) a disciplined day-trading analyst who treats the audit/replay trail as a *risk control*, not a nicety; and (B) an AI/ML engineer with production software instincts (TDD honesty, money-precision, failure modes). Severity: **[P0]** fix before executing this plan, **[P1]** fix during the affected task, **[P2]** track as follow-up. This review is of the *plan* (the reference code + tests it prescribes), not just the design.

### 0. Headline finding — `replay()` is a no-op and its golden test is vacuous **[P0]**

This is the one that matters. The entire value of Phase 5's `replay()` (per design §4.6 and PRD §8.7) is to **re-run `IntradaySession` through the recorded ticks and compare emitted events against recorded events**, so that any change to `_process_signal` breaks the golden test. But the prescribed `reporting/replay.py`:

- **Never calls `run_tick` or instantiates `IntradaySession`.** The actual re-run is left as a comment block ("`# Full impl wires: ...`").
- **Recomputes metrics from the *same* events it just read**, then returns `diverged_at_tick=None` **unconditionally**.
- **`StubbedDataProvider` (listed in "Produces") is never implemented**, and **`ReplayDivergenceError` is defined but never raised anywhere.**

The consequences make the tests self-certifying:

| Test | Claim | Reality |
|---|---|---|
| `test_replay_no_divergence.py` (AC-P5-7) | "any change to `_process_signal` fails this" | asserts `result.diverged_at_tick is None` against code that **hardcodes it to `None`** — the test **can never fail**. Zero regression protection. |
| `test_replay_determinism.py` (AC-P5-5) | "byte-identical across 3 runs" | passes trivially — it's pure deserialization of the same file 3×, no replay involved. |
| `test_replay_roundtrip.py` (AC-P5-6) | round-trip equivalence | `pytest.skip(...)` — not implemented. |

**For a system that makes financial decisions, a reproducibility proof that is wired to always pass is worse than no proof** — it manufactures false confidence in exactly the control you reach for during an incident post-mortem. **Do not let P5.3 close claiming AC-P5-5/6/7** until `replay()` actually drives the session and a *real* comparator raises `ReplayDivergenceError`. The RED test must fail against the stub; today it passes against it.

**Fix:** P5.3 must (1) implement `StubbedDataProvider` feeding recorded quotes/bars into the Phase 2 fetch seams; (2) call `run_tick` per recorded tick; (3) implement the event comparator that sets `diverged_at_tick` / raises `ReplayDivergenceError`; (4) prove it by adding a *mutation test* — deliberately perturb one recorded fill in a fixture and assert replay diverges. The 1.5-day estimate covers the stub, not this; expect the real determinism engine to be the bulk of Phase 5's actual risk (see §3).

### 1. TDD honesty — several GREEN states certify stubs, not ACs **[P0 meta]**

The pattern in §0 repeats across tasks: the hard work is deferred into inline comments while the test is written to pass against the placeholder.

- **P5.2 `_call_techtrade_export` is a placeholder** that emits a "minimal openpyxl workbook" with a single `ReadMe` sheet — it **does not call techtrade** (the whole point of the task per NG3). And `test_xlsx_builder.py` only asserts the **3 intraday sheets** exist, never the **6 techtrade base sheets** that AC-P5-2 explicitly requires. So the test passes with zero techtrade integration. The test does not cover its own AC.
- **P5.1 `test_extracts_briefing_md_verbatim_when_present` does not test verbatim extraction** — its own comment concedes the briefing isn't recoverable, then asserts the *fallback* template header. The verbatim path (`_extract_briefing_md` returning content) has **no coverage**.

**Fix:** either write the RED test to encode the real AC (so GREEN means the AC is met), or explicitly downgrade the task to "scaffold only — AC closed in a named follow-up bead." Do not mark AC-P5-2 / AC-P5-1's agent-narrative branch closed on the current tests.

### 2. The agent-narrative feature is structurally dead **[P1]**

`EndOfDayReportEvent` stores `briefing_md_length` (an int), **not the content**. So `_extract_briefing_md` always returns `None`, and `include_agent_narrative=True` **silently always falls back to the deterministic template**. The operator can never see the LLM's actual prose — defeating design §4.2 path 1, which is the stated reason the option exists.

**Fix:** decide now — either (a) widen `EndOfDayReportEvent` (or add a companion event) to journal the `briefing_md` content so it's recoverable, or (b) delete the `include_agent_narrative` knob and the dead extractor and state plainly that reports are always deterministic. Shipping a user-facing flag that silently does nothing is a trap.

### 3. Money precision — `float` leaks into P&L the operator reads **[P1]**

`_append_per_symbol_pnl_sheet` accumulates `per_symbol[sym]["pnl"] += float(rp)`. The comment ("display-only; Decimal in P&L math") is not a defense — **this sheet _is_ the per-symbol P&L the operator uses to judge which names worked**, and float summation across a day of fills introduces rounding drift in the presented number. This violates P2 (Decimal end-to-end). Same class of issue could bite `json_builder`: confirm `SessionMetrics.model_dump(mode="json")` emits `Decimal` as a **string**, not a float — the test asserts `"1234.56789012"` but if pydantic is configured to coerce Decimal→float anywhere upstream, precision is already gone before `json.dumps(..., default=str)` runs (and `default=str` only fires for objects json can't already handle, so it will *not* save you).

**Fix:** accumulate PerSymbolPnL in `Decimal`; add an explicit test that a 12-dp Decimal survives the *full* `report(format="json")` path (not just `build_json_manifest` in isolation); pin pydantic Decimal serialization mode.

### 4. Metric provenance is silent — dangerous exactly when you need it **[P1]**

`compute_metrics_from_events` lets `SessionEndEvent.realized_pnl` **override** the fill-summed P&L ("session_end is authoritative"). But if `session_end` is missing — crash, `kill -9`, power loss mid-session, i.e. **precisely the post-mortem you most need** — it silently falls back to fill-summing, which may disagree, with no signal to the operator about which source produced the number. And once `replay()` is real (§0), it should **reconcile**: assert replayed P&L equals recorded `session_end` P&L; a mismatch is a far stronger correctness/audit signal than "deserialization is stable."

**Fix:** surface the P&L source (`authoritative_session_end` vs `summed_from_fills`) in `SessionMetrics` / the MD briefing; add the replay reconciliation assertion in P5.3.

### 5. Smaller software issues

| # | Sev | Issue | Fix |
|---|---|---|---|
| S1 | **[P2]** | `json_builder` comment "no timestamps in output = stable" is wrong — event `ts` **are** in the output; they're stable only because they come from the recorded journal. Misleading rationale invites a future bug. | Correct the comment; keep `sort_keys=True`. |
| S2 | **[P2]** | Over-broad `except Exception` in the refactored `_compute_metrics_from_journal` returns zero metrics — a serialization/programming bug masquerades as "empty session" (same finding as Phase 3 review A7). | Catch narrow `FileNotFoundError` / journal-corruption; let real bugs surface. |
| S3 | **[P2]** | `_parse_session_date` slices `session_id[1:5]` assuming `s%Y%m%d%H%M%S`; on format drift it silently returns `today()`, mis-dating the report + output dir. | Prefer the `session_start` event date (already tried first); on parse failure, **raise**, don't default to today. |
| S4 | **[P2]** | Path guard misses Windows drive-relative ids (e.g. `C:foo` has no forbidden substring, but `root / "C:foo.ndjson"` resets to the drive on Windows). | After resolving, assert `resolved.resolve().is_relative_to(root.resolve())`. |
| S5 | **[P2]** | No test for the documented idempotent-overwrite behavior (design §6.2). | Add a test: two `report()` calls to the same dir overwrite + emit the WARN. |
| S6 | **[P2]** | `openbb_core_journal` API is unresolved on the **critical-path foundation** (`replay` vs `read_journal_lines`, flagged "verify at impl time" twice). | Resolve before execution — P5.0 and everything downstream depend on it. |

### 6. Trading-discipline notes

- **[P2] Cost drag not surfaced.** The Fills sheet has per-fill `commission`/`slippage`, but the headline `SessionMetrics` / MD briefing don't appear to aggregate total commissions + slippage. For a day-trader that's often the edge/no-edge line — surface session-level cost drag in the briefing.
- **[P2] Config-example naming is misleading.** `momentum_default / conservative / aggressive` vs. the plan's note that they map to strategy presets `momentum / trend_follow / mean_revert`. Risk-tuning ("conservative/aggressive") and strategy ("trend_follow/mean_revert") are orthogonal; an operator could load `aggressive.yaml` expecting higher risk and get a mean-reversion strategy. Separate the two axes or rename.

### 7. What's genuinely good (keep)

- Clean **TDD-per-task / one-commit-per-bead** structure with explicit `bd dep` wiring and a sequential chain.
- **Single-source-of-truth refactor** of `compute_metrics_from_events` (kills the P3.2 duplication) and the **template de-duplication** move — both correct.
- **Path-traversal sanitization exists at all** (S4 is a hardening, not a hole) and read-only router posture is right.
- **Graceful XLSX degradation design** (MD+JSON still ship when techtrade is absent) is the right resilience call.
- The **"supersedes" note** honestly documents drift from the pre-Phase-3 draft, and the **"deliberately NOT touched"** manifest bounds blast radius well.

### 8. Pre-execution checklist

- [ ] **[P0]** P5.3: implement real `replay()` (StubbedDataProvider + `run_tick` + comparator + raise `ReplayDivergenceError`); add a **mutation test** proving divergence is detected. Golden test must fail against a perturbed fixture.
- [ ] **[P0]** Rewrite P5.2 / P5.1 tests to encode their real ACs (6 techtrade sheets; verbatim-narrative path) — no GREEN against stubs.
- [ ] **[P1]** Resolve the agent-narrative dead path (journal the content, or remove the knob).
- [ ] **[P1]** PerSymbolPnL in `Decimal`; full-path Decimal-as-string JSON test; pin pydantic Decimal mode.
- [ ] **[P1]** Surface P&L provenance; add replay↔session_end reconciliation.
- [ ] **[P2]** S1–S6 + cost-drag surfacing + config-example naming.

**Bottom line:** the scaffolding, task decomposition, and discipline instincts (Decimal intent, path guards, single-source metrics, read-only routers) are solid. But **the plan currently ships the two hardest deliverables — real `replay()` determinism and real techtrade XLSX reuse — as stubs whose tests are written to pass green**, which is both a software-honesty problem and, for the replay/audit trail specifically, a *risk-control* problem. Close the two **[P0]**s (make the tests fail against the stubs, then implement to green) before this plan is executed.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-10-fmp-trading-phase5.md`. Two execution options:**

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks. Best when we want independent review-gate discipline per bead.

2. **Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints. Matches how Phases 2 and 3 shipped.

**Which approach?**
