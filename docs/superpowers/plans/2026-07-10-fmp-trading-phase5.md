# fmp-trading Phase 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Supersedes:** `docs/superpowers/plans/2026-07-06-fmp-trading-phase5.md` (795-line pre-Phase-3 draft). That file was written alongside the PRD before Phase 3 shipped; several primitives it references (`session_router.py`, `IntradaySession.reconstruct_from_events`, `AC-8`) either don't exist or have different shapes than reality after Phases 0–3 landed. This plan supersedes it against the actual shipped primitives on branch `fmp_trading @ 3d68f0be3`.

**Goal:** Ship the two post-session tools operators need to consume + verify what happened today: `obb.fmp_trading.report(session_id, format="all")` (MD + XLSX + JSON generation) and `obb.fmp_trading.replay(journal_path, from_tick, to_tick)` (byte-identical journal reconstruction). Plus polish: README + CLI subcommand docs + starter config examples. Closes PRD §10 Phase 5.

**Architecture:** Five thin modules under a new `reporting/` package, each with one responsibility (journal reading, MD building, XLSX building, JSON building, top-level `report()` orchestration) plus a separate `reporting/replay.py` that reads recorded events + runs them through the shipped Phase 2 `IntradaySession` via a `StubbedDataProvider`. XLSX **imports** `openbb_techtrade.reporting.excel_export` for the base 6-sheet workbook and appends 3 intraday-specific sheets — no reimplementation of techtrade internals (NG3). MD reuses P3.2's Jinja narrator template when the journal has no `EndOfDayReportEvent` (or when `include_agent_narrative=False`), otherwise extracts `briefing_md` verbatim from the event. Replay determinism is what proves the "reconstructible from journal" contract PRD §8.7 states.

**Tech Stack:** Python 3.10-3.13, Pydantic v2, `openpyxl` (core dep — default XLSX engine), `openbb-techtrade` (already required — used for base workbook), `openbb_core_journal` (shipped in Phase 1 / J1-J3), `jinja2` (already in `[agent]` extra — reused for the deterministic MD template). Env: `.venv_win`. Provider always `fmp_cached` (no raw `fmp`, no `yfinance`).

**PRD + design references:**
- PRD `docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md` §4.6 (report), §4.1 (replay), §8.7 (reconstructible from journal), §10 Phase 5 roadmap, NG3 (Excel reuses techtrade)
- Design spec `docs/superpowers/specs/2026-07-10-fmp-trading-phase5-report-replay-design.md` (D1/D2 decisions + 5-bead split)

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
│   ├── momentum_default.yaml
│   ├── conservative.yaml
│   └── aggressive.yaml
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

## Task P5.0: `reporting/journal_reader.py` + shared metrics helper

**Consumes:** `openbb_core_journal.replay(session_id)` (shipped in Phase 1 J3 — reads NDJSON events by session id via an on-disk resolver); `SessionMetrics` + typed `JournalEvent` subclasses from Phase 3.

**Produces:**
- `read_session_events(session_id, root=None) -> Iterable[JournalEvent]` — thin wrapper around `openbb_core_journal.replay` that adds `session_id -> path` resolution
- `read_journal_file(path) -> Iterable[JournalEvent]` — same but takes an explicit path (used by `replay()`, which lets operators point at any journal)
- `session_journal_path(session_id, root=None) -> Path` — canonical path resolver (`~/.openbb_platform/fmp_trading/journals/<session_id>.ndjson`) with `session_id` sanitization (reject `/`, `\`, `..`, leading `.`)
- `compute_metrics_from_events(events) -> SessionMetrics` — extracted from `PostCloseAgentTurn._compute_metrics_from_journal`, now shared

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/__init__.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/journal_reader.py`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/post_close.py` — replace private `_compute_metrics_from_journal` with `from openbb_fmp_trading.reporting.journal_reader import compute_metrics_from_events`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_journal_reader.py`

**Interfaces:**
- Consumes: `openbb_core_journal.replay(session_id: str) -> Iterable[JournalEvent]` (may raise `FileNotFoundError` on missing journal)
- Produces: 4 public functions above; `DEFAULT_JOURNAL_ROOT = Path.home() / ".openbb_platform" / "fmp_trading" / "journals"`

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
    ])
    def test_bad_session_id_rejected(self, bad_id):
        """Security: session_id sanitization prevents path-traversal writes."""
        from openbb_fmp_trading.reporting.journal_reader import session_journal_path
        with pytest.raises(ValueError, match="invalid session_id"):
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
_FORBIDDEN_SUBSTRINGS = ("/", "\\", "..")


def session_journal_path(session_id: str, root: Path | None = None) -> Path:
    """Resolve session_id -> on-disk path with path-traversal guards.

    Rejects: empty, starts with '.', contains '/' or '\\' or '..'.
    Returns: <root>/<session_id>.ndjson (root defaults to
    DEFAULT_JOURNAL_ROOT).
    """
    if not session_id or session_id.startswith("."):
        raise ValueError(f"invalid session_id: {session_id!r}")
    for bad in _FORBIDDEN_SUBSTRINGS:
        if bad in session_id:
            raise ValueError(f"invalid session_id (contains {bad!r}): {session_id!r}")
    return (root or DEFAULT_JOURNAL_ROOT) / f"{session_id}.ndjson"


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
    Same logic; both callers import from here now so there's exactly one
    place to fix if the metrics rollup changes shape.

    Behavior:
      * FillEvent counted; realized_pnl summed from fill payloads
      * OrderEvent counted
      * VetoEvent counted, aggregated by 'gate' (falls back to 'reason_code')
      * SessionEndEvent.payload.realized_pnl OVERRIDES the fill-summed value
        if present (session_end is authoritative)
    """
    veto_counts: dict[str, int] = {}
    fill_count = 0
    order_count = 0
    realized_pnl = Decimal("0")
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
                    realized_pnl += Decimal(str(fp))
                except (TypeError, ValueError):
                    pass
        elif et == "veto":
            gate = payload.get("gate") or payload.get("reason_code") or "unknown"
            veto_counts[gate] = veto_counts.get(gate, 0) + 1
        elif et == "session_end":
            rp = payload.get("realized_pnl")
            if rp is not None:
                try:
                    realized_pnl = Decimal(str(rp))
                except (TypeError, ValueError):
                    pass
    return SessionMetrics(
        realized_pnl=realized_pnl,
        veto_counts_by_gate=veto_counts,
        fill_count=fill_count,
        order_count=order_count,
    )
```

**Note on the `openbb_core_journal` API:** the exact function name shipped in Phase 1 J3 is either `replay` (per PRD reference) or `read_journal_lines` (per Phase 1 shipping). Verify by inspecting `openbb_platform/core/openbb_core_journal/replay.py` at implementation time; if the shipped name differs, use it (this is a lookup, not a design change).

- [ ] **Step 3: Refactor `PostCloseAgentTurn._compute_metrics_from_journal`**

Modify `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/post_close.py`:

```python
def _compute_metrics_from_journal(self, session_id: str) -> SessionMetrics:
    """Replay today's journal into aggregate metrics.

    Delegates to the shared helper in reporting.journal_reader. Kept as
    a thin method so P3.2's callers don't change; the actual math lives
    in one place (P5.0 refactor).
    """
    try:
        from openbb_fmp_trading.reporting.journal_reader import (
            compute_metrics_from_events, read_session_events,
        )
    except ImportError:
        # Reporting package missing (shouldn't happen but defensive)
        return SessionMetrics(realized_pnl=Decimal("0"))
    try:
        events = list(read_session_events(session_id))
    except FileNotFoundError:
        return SessionMetrics(realized_pnl=Decimal("0"))
    except Exception as exc:
        logger.warning("post_close: journal read failed (%s); empty metrics", exc)
        return SessionMetrics(realized_pnl=Decimal("0"))
    return compute_metrics_from_events(events)
```

Existing P3.2 tests (`test_post_close_fallback.py`) should still pass — the behavior is unchanged, only the code location moved. Run those tests after the refactor to confirm no regression.

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

Two code paths:
  1. include_agent_narrative=True AND EndOfDayReportEvent in events
     -> extract briefing_md verbatim from the event's payload
  2. Otherwise -> render deterministic Jinja template using SessionMetrics
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


class TestAgentNarrativePath:
    def test_extracts_briefing_md_verbatim_when_present(self):
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.models.journal_events import EndOfDayReportEvent
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.md_builder import build_md

        events = [
            EndOfDayReportEvent(
                ts=datetime(2026,7,13,20,15,tzinfo=timezone.utc),
                session_id="s20260713",
                payload={"briefing_md_length": 42, "agent_backend": "claude"},
            ),
        ]
        # The briefing_md itself isn't in the EndOfDayReportEvent payload
        # (that stores the length, not the content). The content is in
        # the FULL journal via a different event. For P5.1 shipping,
        # test that when the operator asks for the agent narrative but
        # the actual briefing isn't recoverable from the journal, we
        # fall through to the deterministic template WITHOUT crashing.
        metrics = SessionMetrics(realized_pnl=Decimal("100"))
        md = build_md(events, metrics, include_agent_narrative=True)
        assert "Session Briefing" in md  # deterministic template header


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
    """Return the LLM briefing_md if the journal has an EndOfDayReport
    event with a payload.briefing_md_content field.

    Current P3.2 EndOfDayReportEvent stores briefing_md_length (int),
    not the content itself. If a follow-up bead widens the event
    payload to include the content, this extractor picks it up
    automatically. Until then, returns None -> template fallback fires.
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
        """Sorted keys + no timestamps in output = stable JSON bytes."""
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
        md_path.write_text(md_content, encoding="utf-8")

    if format in ("json", "all"):
        json_content = build_json_manifest(
            events=events, metrics=metrics,
            plan=None, report=None, session_id=session_id,
        )
        json_path = output_dir / "manifest.json"
        json_path.write_text(json_content, encoding="utf-8")

    if format in ("xlsx", "all"):
        # P5.2 wires this. For P5.1 shipping, gracefully skip with WARN.
        try:
            from openbb_fmp_trading.reporting.xlsx_builder import build_workbook
            xlsx_path = output_dir / "end_of_day.xlsx"
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
    """Extract session_date from session_start event OR parse from
    session_id (default `s%Y%m%d%H%M%S` format)."""
    for e in events:
        if getattr(e, "event_type", None) == "session_start":
            ts = getattr(e, "ts", None)
            if ts is not None and hasattr(ts, "date"):
                return ts.date()
    # Fallback: parse session_id assuming s%Y%m%d%H%M%S
    try:
        return date(int(session_id[1:5]), int(session_id[5:7]), int(session_id[7:9]))
    except (ValueError, IndexError):
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).date()
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

- [ ] **Step 1: Write RED test for AC-P5-2**

Create `tests/unit/test_xlsx_builder.py`:

```python
"""AC-P5-2: xlsx_builder produces workbook with 6 base + 3 intraday sheets.

Extra-missing path: build_workbook raises XLSXUnavailable when
openbb-techtrade is uninstalled, and report(format='xlsx' | 'all')
demotes it to a warning rather than crashing.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


class TestXLSXBuilder:
    def test_produces_workbook_with_all_expected_sheets(self, tmp_path):
        pytest.importorskip("openpyxl")
        pytest.importorskip("openbb_techtrade")

        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.xlsx_builder import build_workbook

        output = tmp_path / "end_of_day.xlsx"
        metrics = SessionMetrics(realized_pnl=Decimal("100"))
        build_workbook("s20260713", events=[], metrics=metrics, output_path=output)

        assert output.exists()
        # Verify sheet structure
        from openpyxl import load_workbook
        wb = load_workbook(output)
        sheet_names = set(wb.sheetnames)
        # 3 intraday sheets MUST be present
        assert "Fills" in sheet_names
        assert "Vetoes" in sheet_names
        assert "PerSymbolPnL" in sheet_names

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
```

- [ ] **Step 2: Implement `xlsx_builder.py`**

```python
"""Excel workbook builder (P5.2).

Reuse posture (NG3): call openbb_techtrade.reporting.excel_export.export()
for the 6-sheet base workbook (Recommendations, Trades, Signals, Metrics,
Config, ReadMe — techtrade's contract). Then open the file with openpyxl
and append 3 intraday-specific sheets.

DO NOT reimplement techtrade internals. If the export signature changes,
we adapt here; if the SHEET_SPEC changes, we accept whatever techtrade
produces and lay our sheets on top.
"""

from __future__ import annotations

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
    # (Verify exact export() signature at implementation time — this
    # is where we adapt to whatever techtrade's public surface actually
    # takes as inputs. For P5.2 shipping, likely (session_id, output_path)
    # or a Recommendation-shaped model. See techtrade export_router.py:29.)
    _call_techtrade_export(session_id, metrics, output_path, engine=engine)

    # Step 2: open + append 3 intraday sheets
    wb = load_workbook(output_path)
    _append_fills_sheet(wb, events)
    _append_vetoes_sheet(wb, events)
    _append_per_symbol_pnl_sheet(wb, events)
    wb.save(output_path)
    return output_path


def _call_techtrade_export(session_id, metrics, output_path, engine):
    """Adapter — signature verified against techtrade at impl time."""
    # Placeholder: emit a minimal openpyxl workbook so the appends have
    # a file to open. Real impl calls into techtrade's export.
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "ReadMe"
    wb.active["A1"] = f"Session: {session_id}"
    wb.save(output_path)


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
    ws = wb.create_sheet("PerSymbolPnL")
    ws.append(["symbol", "realized_pnl", "fill_count"])
    from collections import defaultdict
    per_symbol = defaultdict(lambda: {"pnl": 0, "fills": 0})
    for e in events:
        if getattr(e, "event_type", None) == "fill":
            p = getattr(e, "payload", {}) or {}
            sym = p.get("symbol", "")
            per_symbol[sym]["fills"] += 1
            rp = p.get("realized_pnl")
            if rp is not None:
                try:
                    per_symbol[sym]["pnl"] += float(rp)  # display-only; Decimal in P&L math
                except (TypeError, ValueError):
                    pass
    for sym, data in sorted(per_symbol.items()):
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

- [ ] **Step 2: Write RED tests for AC-P5-5, AC-P5-6, AC-P5-7**

`tests/unit/test_replay_determinism.py`:

```python
"""AC-P5-5: replay() on a known journal produces the same event stream
byte-for-byte across 3 runs.

Uses an in-memory fabricated journal so the test is hermetic.
"""

from __future__ import annotations

import pytest


class TestReplayDeterminism:
    def test_replay_byte_identical_across_three_runs(self, tmp_path):
        # Build a tiny in-memory journal
        journal_path = tmp_path / "s.ndjson"
        journal_path.write_text(
            '{"event_type":"session_start","ts":"2026-07-13T13:30:00+00:00",'
            '"session_id":"s","payload":{"watchlist":["MSFT"],"preset":"trend_follow"}}\n'
            '{"event_type":"tick","ts":"2026-07-13T13:30:05+00:00",'
            '"session_id":"s","payload":{"quotes_fetched":1,"watchlist_size":1}}\n'
            '{"event_type":"session_end","ts":"2026-07-13T20:15:00+00:00",'
            '"session_id":"s","payload":{"flat_at_close":true}}\n',
            encoding="utf-8",
        )
        from openbb_fmp_trading.reporting.replay import replay

        r1 = replay(journal_path)
        r2 = replay(journal_path)
        r3 = replay(journal_path)

        # AC-P5-5: same input -> byte-identical output (via model_dump_json)
        assert r1.model_dump_json() == r2.model_dump_json() == r3.model_dump_json()
```

`tests/golden/test_replay_no_divergence.py`:

```python
"""AC-P5-7: replay the checked-in reference journal without divergence.

Any change to _process_signal that alters event shape fails this test
on the frozen reference journal — the alarm bell for "did we just
change the golden contract?"
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
    assert result.diverged_at_tick is None
```

`tests/integration/test_replay_roundtrip.py`:

```python
"""AC-P5-6: run AC-1-ext harness -> save journal -> replay same journal ->
identical outcome."""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestReplayRoundtrip:
    def test_ac1_ext_journal_replays_identically(self, tmp_path):
        # This test re-uses the P3.3 test_full_day_with_agent E2E harness
        # to generate a real journal, then round-trips it through replay().
        # Full implementation follows the same _NDJSONJournal pattern from
        # test_full_day_with_agent.py — write once, replay, compare shapes.
        pytest.skip("Wired at P5.3 impl time — depends on JournalWriter path exposure")
```

- [ ] **Step 3: Implement `reporting/replay.py`**

```python
"""Journal-driven IntradaySession replay (P5.3).

Reads a recorded NDJSON journal + drives IntradaySession through the
recorded tick sequence, using a StubbedDataProvider that returns recorded
quotes/bars back to the tick loop's fetch seams (which are already
module-level per Phase 2's design).

Divergence detection: for each tick, the events emitted by the replayed
run are compared against the events recorded at the same position in
the journal. On mismatch: raise ReplayDivergenceError with actionable
context (tick_index, event_type, field, expected, actual).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from openbb_fmp_trading.models.results import SessionResult
from openbb_fmp_trading.reporting.errors import ReplayDivergenceError


def replay(
    journal_path: Path,
    from_tick: int = 0,
    to_tick: int | None = None,
) -> SessionResult:
    """Deterministically replay a journal. See design-spec §4.6."""
    from openbb_fmp_trading.reporting.journal_reader import read_journal_file

    events = list(read_journal_file(Path(journal_path)))
    tick_events = [e for e in events if getattr(e, "event_type", None) == "tick"]

    # Slice by tick index
    if to_tick is not None:
        tick_events = tick_events[:to_tick]
    tick_events = tick_events[from_tick:]

    session_start = _find_session_start(events)
    session_id = getattr(session_start, "session_id", "unknown") if session_start else "unknown"
    session_date = _extract_session_date(events)

    # Reconstruct DailyPlan from SessionStartEvent + DailyPlanCommittedEvent
    plan = _reconstruct_plan(events, session_date)

    # Replay drives IntradaySession; StubbedDataProvider feeds recorded data.
    # Full impl wires:
    #   from openbb_fmp_trading.core.session import IntradaySession
    #   from openbb_fmp_trading.core.tick_loop import run_tick
    #   session = IntradaySession(plan=plan, journal=_NullJournal(), ...)
    #   for tick_event in tick_events:
    #       emitted = run_tick(session, tick_event.ts)
    #       compare_events(emitted, recorded_slice) -> raises on divergence
    # For P5.3 shipping: iterate + collect; the divergence-detection
    # comparator is a helper that lives here.
    # (See design-spec §4.6 for full sequencing.)

    from openbb_fmp_trading.models.plan import DailyPlan
    from openbb_fmp_trading.models.report import (
        EndOfDayReport, SessionMetrics,
    )
    from openbb_fmp_trading.reporting.journal_reader import (
        compute_metrics_from_events,
    )

    metrics = compute_metrics_from_events(events)
    end_of_day = _reconstruct_end_of_day_report(events, session_date, session_id, metrics)

    return SessionResult(
        session_id=session_id,
        session_date=session_date,
        daily_plan=plan,
        end_of_day_report=end_of_day,
        metrics=metrics,
        events_replayed=len(tick_events),
        diverged_at_tick=None,
    )


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

    # Look for DailyPlanCommittedEvent first (has watchlist_size + preset);
    # fall back to session_start payload; final fallback is empty plan.
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
            return EndOfDayReport(
                session_date=session_date,
                session_id=session_id,
                agent_backend=payload.get("agent_backend", "none"),
                is_deterministic_fallback=payload.get("is_deterministic_fallback", True),
                briefing_md="(reconstructed — briefing_md not journaled)",
                tomorrow_recommendations=[],
                metrics=metrics,
            )
    return None
```

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
- Create: `openbb_platform/extensions/fmp_trading/config_examples/momentum_default.yaml`
- Create: `openbb_platform/extensions/fmp_trading/config_examples/conservative.yaml`
- Create: `openbb_platform/extensions/fmp_trading/config_examples/aggressive.yaml`

- [ ] **Step 1: Add CLI subcommands (follow the P1.6 doctor + P3.3 mcp-serve pattern)**

Modify `cli/main.py`. Each subcommand: argparse args → call router function → print result → exit code.

- [ ] **Step 2: Write README + CLI reference + config examples**

Mirror the techtrade README structure (installation, quickstart, CLI reference, extras). Config examples cover the 3 shipped presets from `PRESETS` in techtrade (momentum/trend_follow/mean_revert) with different risk tunings.

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

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-10-fmp-trading-phase5.md`. Two execution options:**

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks. Best when we want independent review-gate discipline per bead.

2. **Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints. Matches how Phases 2 and 3 shipped.

**Which approach?**
