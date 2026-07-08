# FMP Day-Trading Automation — Phase 5 (Reporting + Polish) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the reporting + user-facing polish surface of `openbb-fmp-trading` — the `obb.fmp_trading.report()` command (MD + XLSX + JSON), the `obb.fmp_trading.replay()` command (deterministic journal → SessionResult), and the first user-consumable docs (README + CLI reference + config examples). Closes PRD §10 Phase 5.

**Architecture:** Three thin renderer modules under `reporting/` (one per output format) plus a `core/replay.py` reconstructor that reads an NDJSON journal event-by-event and produces the same `SessionResult` byte-for-byte across runs (AC-8). The XLSX path **does not reimplement Excel writing** — it imports `openbb_techtrade.reporting.excel_export` for the 6-sheet workbook chassis and layers on three intraday-specific sheets (per-tick summary, alert log, position ledger). The MD renderer is a Jinja-free string-builder for determinism; the JSON manifest is a pure `model_dump()` over `SessionResult`. The `replay()` command routes through the same `IntradaySession` state-machine as `run()` — it just replays journal-recorded ticks instead of fetching live quotes.

**Tech Stack:** Python 3.10-3.13, Pydantic v2, `openpyxl` (default engine, ships with core install) + `xlsxwriter` (opt-in via extra, imported lazily from techtrade), `openbb-techtrade >= 0.1.0` at runtime. Env: `.venv_win`. Provider always `fmp_cached`.

**PRD references:** §4.6 (report command), §4.1 (replay command), §10 Phase 5, §2.3 AC-8 (byte-identical replay), §3.6 (failure modes), NG3 (Excel reuses techtrade).

---

## Critical Design Constraints — READ FIRST

1. **Codegen bug (inherited from Phase 1):** every router command annotates return type as **bare `OBBject`**, never `OBBject[ReportManifest]` or `OBBject[SessionResult]`. The static package builder emits the parametrized model name into generated signatures without importing it → `NameError` on first namespace access. See phase-1 scaffold plan for the full trace; same rule applies here without exception.

2. **Excel reuse posture (NG3):** `xlsx_renderer.py` **imports** `openbb_techtrade.reporting.excel_export` and calls its public entry point to produce the base 6-sheet workbook, then opens the returned file with `openpyxl.load_workbook(...)` and appends the three intraday sheets. Do NOT reimplement `SHEET_SPEC`, `FORMAT_SPEC`, `_apply_openpyxl_cf`, or any techtrade internals — those are covered by techtrade's own golden tests and any drift here silently forks the report format.

3. **Replay determinism (AC-8):** the golden test replays the same fixture journal 3 times and asserts `SessionResult.model_dump_json() == SessionResult.model_dump_json()` across all three runs. Any source of non-determinism (dict iteration order, `datetime.now()`, unseeded RNG, floating-point accumulation) will surface here. Use `Decimal` for money, sort dict keys before serialization, and never call `datetime.now()` inside the replay path — the journal is the clock.

4. **Provider posture (from PRD §5.4):** no `provider="fmp"` literal anywhere in this phase's code. The CI grep test already added in Phase 1 covers `openbb_fmp_trading/`. `reporting/` never fetches — it only reads the journal — so provider selection is not a concern here. `replay()` may call `obb.fmp_trading.*` fetchers to rehydrate bars for signals; those must pass `provider="fmp_cached"`.

**Tracker:** GitHub issue for this phase is the Phase-5 tracker beads/issue (`bd ready` → find the P5 tracker; reference it in every commit). Do NOT invent a bd id.

**Branch:** `fmp_trading` (per PRD). No worktree.

---

## File Structure

All paths under `openbb_platform/extensions/fmp_trading/`:

| File | Responsibility |
|---|---|
| `openbb_fmp_trading/reporting/__init__.py` | Package marker; re-exports `render_md`, `render_xlsx`, `render_json`, `write_report`. |
| `openbb_fmp_trading/reporting/md_renderer.py` | Deterministic Markdown day-summary builder; string-only, no Jinja. |
| `openbb_fmp_trading/reporting/xlsx_renderer.py` | Delegates to `openbb_techtrade.reporting.excel_export`; appends 3 intraday sheets via `openpyxl`. |
| `openbb_fmp_trading/reporting/json_manifest.py` | Serializes `SessionResult` + full journal to canonical JSON. |
| `openbb_fmp_trading/reporting/report_router.py` | Router: `obb.fmp_trading.report()` command (bare `OBBject`). |
| `openbb_fmp_trading/core/replay.py` | Journal → `SessionResult` reconstruction driving `IntradaySession` deterministically. |
| `README.md` | User-facing entry doc (mirrors techtrade README structure). |
| `docs/cli_reference.md` | Per-subcommand reference for `openbb-daytrade`. |
| `config_examples/momentum_default.yaml` | Sample `DailyConfig` — matches PRD defaults. |
| `config_examples/conservative.yaml` | Tight risk / small watchlist / larger cooldowns. |
| `config_examples/aggressive.yaml` | Larger position count / looser day-DD / short cooldowns. |
| `tests/unit/test_md_renderer.py` | Renderer smoke + golden text-length invariants. |
| `tests/unit/test_xlsx_renderer.py` | Asserts 3 extra sheets present + techtrade base sheets untouched. |
| `tests/unit/test_json_manifest.py` | Round-trip JSON serialization + key-order stability. |
| `tests/unit/test_report_router.py` | Router surface: `format="all"` writes 3 files, `format="md"` writes 1. |
| `tests/golden/test_replay_determinism.py` | AC-8: same fixture journal → 3 identical `SessionResult` dumps. |
| `tests/fixtures/journals/2026-06-30_msft_aapl.ndjson` | Frozen tiny replay fixture (~50 events). |

Modified outside `reporting/`:
- `openbb_fmp_trading/session_router.py` — add `replay()` command wired to `core/replay.py`.
- `pyproject.toml` — ensure `openbb-techtrade >= 0.1.0` in `[tool.poetry.dependencies]`; `[xlsxwriter]` extra proxies through to techtrade.

> **Out of scope for Phase 5** (deferred to Phase 6 or v2, do NOT create here):
> - Backtest bridge / `validate` command → P6.1
> - HTML/PDF renderers → v2
> - Email / webhook / push delivery of the report → v2 (NG7)
> - `next_day_hints` auto-apply logic → Q2 in PRD open questions

---

## Task 1: `json_manifest.py` — canonical serialization (RED first)

**Files:**
- Test: `openbb_platform/extensions/fmp_trading/tests/unit/test_json_manifest.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/__init__.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/json_manifest.py`

**Consumes:** `SessionResult` (from `openbb_fmp_trading.models.results`), `list[JournalEvent]` (from `openbb_fmp_trading.models.session_state`).
**Produces:** UTF-8 JSON bytes with sorted keys, ISO-8601 tz-aware timestamps, `Decimal` rendered as string.

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for the canonical JSON manifest renderer."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from openbb_fmp_trading.reporting.json_manifest import render_json


def test_render_json_is_stable_across_calls(tmp_session_result, tmp_journal):
    a = render_json(tmp_session_result, tmp_journal)
    b = render_json(tmp_session_result, tmp_journal)
    assert a == b, "JSON manifest must be byte-identical across calls with same inputs"


def test_decimal_serializes_as_string(tmp_session_result, tmp_journal):
    payload = json.loads(render_json(tmp_session_result, tmp_journal))
    assert isinstance(payload["session"]["final_pnl"]["realized_pnl"], str)


def test_keys_are_sorted(tmp_session_result, tmp_journal):
    payload = render_json(tmp_session_result, tmp_journal)
    parsed = json.loads(payload)
    keys = list(parsed.keys())
    assert keys == sorted(keys)
```

- [ ] **Step 2: Run the test — expect fail**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_json_manifest.py -q`
Expected: FAIL — `ModuleNotFoundError: openbb_fmp_trading.reporting.json_manifest`.

- [ ] **Step 3: Create `reporting/__init__.py`**

```python
"""fmp_trading reporting: MD / XLSX / JSON day-summary renderers."""

from openbb_fmp_trading.reporting.json_manifest import render_json
from openbb_fmp_trading.reporting.md_renderer import render_md
from openbb_fmp_trading.reporting.xlsx_renderer import render_xlsx

__all__ = ["render_json", "render_md", "render_xlsx"]
```

- [ ] **Step 4: Implement `json_manifest.py`**

```python
"""Canonical JSON serialization of a SessionResult + full journal."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from openbb_fmp_trading.models.results import SessionResult
from openbb_fmp_trading.models.session_state import JournalEvent


def _default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    raise TypeError(f"Cannot serialize {type(obj).__name__}")


def render_json(session: SessionResult, journal: list[JournalEvent]) -> str:
    """Render the canonical JSON manifest for a completed session."""
    payload = {
        "journal": [ev.model_dump(mode="json") for ev in journal],
        "manifest_version": 1,
        "session": session.model_dump(mode="json"),
    }
    return json.dumps(payload, sort_keys=True, default=_default, indent=2)
```

- [ ] **Step 5: Add pytest fixtures**

Create `openbb_platform/extensions/fmp_trading/tests/unit/conftest.py`:

```python
"""Shared fixtures for reporting unit tests."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from openbb_fmp_trading.models.results import SessionResult
from openbb_fmp_trading.models.session_state import JournalEvent, PnLSnapshot


@pytest.fixture
def tmp_journal() -> list[JournalEvent]:
    ts = datetime(2026, 6, 30, 14, 30, tzinfo=timezone.utc)
    return [
        JournalEvent(ts=ts, session_id="2026-06-30", event_type="session_start", payload={}),
        JournalEvent(ts=ts, session_id="2026-06-30", event_type="tick", payload={"symbol": "MSFT"}),
        JournalEvent(ts=ts, session_id="2026-06-30", event_type="session_end", payload={}),
    ]


@pytest.fixture
def tmp_session_result(tmp_path, tmp_journal) -> SessionResult:
    return SessionResult(
        session_id="2026-06-30",
        date=date(2026, 6, 30),
        exchange="NASDAQ",
        started_at=tmp_journal[0].ts,
        ended_at=tmp_journal[-1].ts,
        exit_code=0,
        daily_plan=None,
        final_pnl=PnLSnapshot(
            ts=tmp_journal[-1].ts, realized_pnl=Decimal("125.50"),
            unrealized_pnl=Decimal("0"), day_pnl=Decimal("125.50"),
            day_dd_pct=0.0, positions_open=0, positions_closed=1, win_rate_today=1.0,
        ),
        final_bandwidth=None, total_ticks=1, total_signals=0, total_orders=1,
        total_fills=1, total_vetoes=0, total_alerts_fired=0,
        flat_at_close=True, journal_path=tmp_path / "journal.ndjson",
    )
```

- [ ] **Step 6: Rerun test, expect PASS + commit**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_json_manifest.py -q`
Expected: `3 passed`.

```
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/__init__.py openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/json_manifest.py openbb_platform/extensions/fmp_trading/tests/unit/test_json_manifest.py openbb_platform/extensions/fmp_trading/tests/unit/conftest.py
git commit -m "feat(fmp_trading): canonical JSON manifest renderer (P5.1)"
```

---

## Task 2: `md_renderer.py` — deterministic Markdown day-summary

**Files:**
- Test: `openbb_platform/extensions/fmp_trading/tests/unit/test_md_renderer.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/md_renderer.py`

**Consumes:** `SessionResult`, optional agent narrative string (from `PostCloseAgentTurn.submit_end_of_day_md`).
**Produces:** UTF-8 Markdown string with: session header, PnL block, trade table, preset review, next-day hints, agent narrative (if provided).

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for the Markdown day-summary renderer."""

from __future__ import annotations

from openbb_fmp_trading.reporting.md_renderer import render_md


def test_md_contains_session_id(tmp_session_result, tmp_journal):
    md = render_md(tmp_session_result, tmp_journal, agent_narrative=None)
    assert "2026-06-30" in md
    assert "NASDAQ" in md


def test_md_contains_disclaimer(tmp_session_result, tmp_journal):
    md = render_md(tmp_session_result, tmp_journal)
    assert "paper" in md.lower() and "not investment advice" in md.lower()


def test_md_is_deterministic(tmp_session_result, tmp_journal):
    a = render_md(tmp_session_result, tmp_journal, agent_narrative="text")
    b = render_md(tmp_session_result, tmp_journal, agent_narrative="text")
    assert a == b


def test_md_without_agent_narrative_still_renders(tmp_session_result, tmp_journal):
    md = render_md(tmp_session_result, tmp_journal, agent_narrative=None)
    assert "# Session 2026-06-30" in md
```

- [ ] **Step 2: Implement `md_renderer.py`**

```python
"""Deterministic Markdown day-summary renderer."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from openbb_fmp_trading.models.results import SessionResult
from openbb_fmp_trading.models.session_state import JournalEvent

DISCLAIMER = "Research/paper output - not investment advice."


def _fmt_money(v: Decimal | None) -> str:
    return f"${v:,.2f}" if v is not None else "-"


def render_md(
    session: SessionResult,
    journal: list[JournalEvent],
    agent_narrative: str | None = None,
) -> str:
    """Render the end-of-day markdown summary."""
    lines: list[str] = []
    lines.append(f"# Session {session.session_id}")
    lines.append("")
    lines.append(f"_{DISCLAIMER}_")
    lines.append("")
    lines.append("## Overview")
    lines.append("")
    lines.append(f"- **Exchange:** {session.exchange}")
    lines.append(f"- **Started:** {session.started_at.isoformat()}")
    lines.append(f"- **Ended:** {session.ended_at.isoformat()}")
    lines.append(f"- **Exit code:** {session.exit_code}")
    lines.append(f"- **Flat at close:** {'yes' if session.flat_at_close else 'NO (see warning)'}")
    lines.append("")
    lines.append("## P&L")
    lines.append("")
    pnl = session.final_pnl
    lines.append(f"- **Realized:** {_fmt_money(pnl.realized_pnl)}")
    lines.append(f"- **Unrealized:** {_fmt_money(pnl.unrealized_pnl)}")
    lines.append(f"- **Day P&L:** {_fmt_money(pnl.day_pnl)}")
    lines.append(f"- **Day DD %:** {pnl.day_dd_pct:+.2f}%")
    lines.append(f"- **Positions closed:** {pnl.positions_closed}")
    lines.append("")
    lines.append("## Journal counters")
    lines.append("")
    lines.append(f"- Ticks: {session.total_ticks}")
    lines.append(f"- Signals: {session.total_signals}")
    lines.append(f"- Orders: {session.total_orders}")
    lines.append(f"- Fills: {session.total_fills}")
    lines.append(f"- Vetoes: {session.total_vetoes}")
    lines.append(f"- Alerts fired: {session.total_alerts_fired}")
    lines.append("")
    if agent_narrative:
        lines.append("## Post-close agent narrative")
        lines.append("")
        lines.append(agent_narrative.rstrip())
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 3: Rerun tests + commit**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_md_renderer.py -q`
Expected: `4 passed`.

```
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/md_renderer.py openbb_platform/extensions/fmp_trading/tests/unit/test_md_renderer.py
git commit -m "feat(fmp_trading): deterministic markdown day-summary renderer (P5.1)"
```

---

## Task 3: `xlsx_renderer.py` — reuse techtrade + append intraday sheets

**Files:**
- Test: `openbb_platform/extensions/fmp_trading/tests/unit/test_xlsx_renderer.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/xlsx_renderer.py`

**Consumes:** `SessionResult`, `list[JournalEvent]`, `list[TradePlan]` (reconstructed by replay path).
**Produces:** `.xlsx` file with 6 techtrade sheets (Recommendations / Levels / Reasoning / Orders / Fills / Summary) **plus** 3 intraday sheets (`TickSummary`, `AlertLog`, `PositionLedger`).

- [ ] **Step 1: Write the failing test + implementation**

Test file:
```python
"""Unit tests for the XLSX renderer that layers intraday sheets on top of techtrade's workbook."""

from __future__ import annotations

import pytest
from openpyxl import load_workbook

from openbb_fmp_trading.reporting.xlsx_renderer import (
    INTRADAY_SHEETS,
    TECHTRADE_BASE_SHEETS,
    render_xlsx,
)


def test_render_xlsx_writes_all_nine_sheets(tmp_session_result, tmp_journal, tmp_path):
    out_path = tmp_path / "session.xlsx"
    render_xlsx(tmp_session_result, tmp_journal, plans=[], out_path=out_path)
    wb = load_workbook(out_path, read_only=True)
    for sheet in TECHTRADE_BASE_SHEETS:
        assert sheet in wb.sheetnames, f"missing techtrade sheet: {sheet}"
    for sheet in INTRADAY_SHEETS:
        assert sheet in wb.sheetnames, f"missing intraday sheet: {sheet}"


def test_intraday_sheets_appended_after_base(tmp_session_result, tmp_journal, tmp_path):
    out_path = tmp_path / "session.xlsx"
    render_xlsx(tmp_session_result, tmp_journal, plans=[], out_path=out_path)
    wb = load_workbook(out_path, read_only=True)
    idx_base_last = wb.sheetnames.index(TECHTRADE_BASE_SHEETS[-1])
    idx_intra_first = wb.sheetnames.index(INTRADAY_SHEETS[0])
    assert idx_intra_first > idx_base_last, "intraday sheets must be appended after techtrade sheets"
```

Implementation:
```python
"""XLSX renderer — thin layer on top of techtrade's 6-sheet workbook."""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook
from openpyxl.workbook import Workbook

from openbb_fmp_trading.models.results import SessionResult
from openbb_fmp_trading.models.session_state import JournalEvent

TECHTRADE_BASE_SHEETS: tuple[str, ...] = (
    "Recommendations", "Levels", "Reasoning", "Orders", "Fills", "Summary",
)
INTRADAY_SHEETS: tuple[str, ...] = ("TickSummary", "AlertLog", "PositionLedger")


def render_xlsx(
    session: SessionResult,
    journal: list[JournalEvent],
    plans: list,
    out_path: Path,
    engine: str = "openpyxl",
) -> Path:
    """Render the 9-sheet workbook. Delegates base workbook to techtrade."""
    from openbb_techtrade.reporting.excel_export import write_workbook  # lazy import

    write_workbook(plans=plans, path=out_path, engine=engine)

    wb: Workbook = load_workbook(out_path)
    _append_tick_summary(wb, journal)
    _append_alert_log(wb, journal)
    _append_position_ledger(wb, journal)
    wb.save(out_path)
    return out_path


def _append_tick_summary(wb: Workbook, journal: list[JournalEvent]) -> None:
    ws = wb.create_sheet("TickSummary")
    ws.append(["ts", "watchlist_size", "quotes_fetched", "mode"])
    for ev in (e for e in journal if e.event_type == "tick"):
        p = ev.payload
        ws.append([ev.ts.isoformat(), p.get("watchlist_size"), p.get("quotes_fetched"), p.get("mode")])


def _append_alert_log(wb: Workbook, journal: list[JournalEvent]) -> None:
    ws = wb.create_sheet("AlertLog")
    ws.append(["ts", "alert_id", "symbol", "condition"])
    for ev in (e for e in journal if e.event_type == "alert"):
        p = ev.payload
        ws.append([ev.ts.isoformat(), p.get("alert_id"), p.get("symbol"), p.get("condition")])


def _append_position_ledger(wb: Workbook, journal: list[JournalEvent]) -> None:
    ws = wb.create_sheet("PositionLedger")
    ws.append(["ts", "symbol", "action", "qty", "price"])
    for ev in (e for e in journal if e.event_type in ("order", "fill")):
        p = ev.payload
        ws.append([ev.ts.isoformat(), p.get("symbol"), p.get("intent"), p.get("qty"), p.get("price")])
```

- [ ] **Step 2: Run test + commit**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_xlsx_renderer.py -q`
Expected: `2 passed`.

```
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/xlsx_renderer.py openbb_platform/extensions/fmp_trading/tests/unit/test_xlsx_renderer.py
git commit -m "feat(fmp_trading): XLSX renderer reuses techtrade + adds 3 intraday sheets (P5.2)"
```

---

## Task 4: `report_router.py` — `obb.fmp_trading.report()` command

**Files:**
- Test: `openbb_platform/extensions/fmp_trading/tests/unit/test_report_router.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/report_router.py`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/fmp_trading_router.py` (register `report_router`)

**Consumes:** `session_id: str`, `format: Literal["md","xlsx","json","all"]`, `output_dir: Path | None`, `include_agent_narrative: bool`.
**Produces:** `OBBject` (bare!) whose `results` is a `ReportManifest` dict with paths to written files.

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for obb.fmp_trading.report() surface."""

from __future__ import annotations

from pathlib import Path

from openbb_fmp_trading.reporting.report_router import write_report


def test_format_md_writes_only_md(tmp_session_result, tmp_journal, tmp_path):
    manifest = write_report(
        session=tmp_session_result, journal=tmp_journal, plans=[],
        fmt="md", output_dir=tmp_path, include_agent_narrative=False,
    )
    assert manifest.md_path and manifest.md_path.exists()
    assert manifest.xlsx_path is None
    assert manifest.json_path is None


def test_format_all_writes_three_files(tmp_session_result, tmp_journal, tmp_path):
    manifest = write_report(
        session=tmp_session_result, journal=tmp_journal, plans=[],
        fmt="all", output_dir=tmp_path, include_agent_narrative=False,
    )
    assert manifest.md_path.exists()
    assert manifest.xlsx_path.exists()
    assert manifest.json_path.exists()
```

- [ ] **Step 2: Implement `report_router.py`**

```python
"""Router: obb.fmp_trading.report() — MD + XLSX + JSON."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_fmp_trading.models.results import ReportManifest, SessionResult
from openbb_fmp_trading.models.session_state import JournalEvent
from openbb_fmp_trading.reporting.json_manifest import render_json
from openbb_fmp_trading.reporting.md_renderer import render_md
from openbb_fmp_trading.reporting.xlsx_renderer import render_xlsx

router = Router(prefix="")


def _default_output_dir(session_id: str) -> Path:
    return Path("Analysis/exports") / f"daytrade_{session_id}"


def write_report(
    session: SessionResult,
    journal: list[JournalEvent],
    plans: list,
    fmt: Literal["md", "xlsx", "json", "all"],
    output_dir: Path,
    include_agent_narrative: bool,
    agent_narrative: str | None = None,
) -> ReportManifest:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = xlsx_path = json_path = None

    if fmt in ("md", "all"):
        md_path = output_dir / "end_of_day.md"
        md_path.write_text(
            render_md(session, journal, agent_narrative if include_agent_narrative else None),
            encoding="utf-8",
        )
    if fmt in ("xlsx", "all"):
        xlsx_path = render_xlsx(session, journal, plans, output_dir / "end_of_day.xlsx")
    if fmt in ("json", "all"):
        json_path = output_dir / "session_manifest.json"
        json_path.write_text(render_json(session, journal), encoding="utf-8")

    return ReportManifest(
        session_id=session.session_id,
        md_path=md_path, xlsx_path=xlsx_path, json_path=json_path,
        included_agent_narrative=include_agent_narrative and agent_narrative is not None,
    )


@router.command(methods=["POST"])
def report(
    session_id: str,
    format: Literal["md", "xlsx", "json", "all"] = "all",
    output_dir: Path | None = None,
    include_agent_narrative: bool = True,
) -> OBBject:
    """Render session artifacts (md / xlsx / json). PRD §4.6."""
    from openbb_fmp_trading.core.session_store import load_session, load_journal, load_plans

    session = load_session(session_id)
    journal = load_journal(session_id)
    plans = load_plans(session_id)
    out_dir = output_dir or _default_output_dir(session_id)
    manifest = write_report(
        session=session, journal=journal, plans=plans,
        fmt=format, output_dir=out_dir,
        include_agent_narrative=include_agent_narrative,
    )
    return OBBject(results=manifest.model_dump(mode="json"))
```

- [ ] **Step 3: Register the router, run tests, verify codegen, commit**

Add to `fmp_trading_router.py`:
```python
from openbb_fmp_trading.reporting.report_router import router as report_router
router.include_router(report_router)
```

Run:
```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_report_router.py -q
.venv_win\Scripts\python.exe -c "import openbb; openbb.build()"
.venv_win\Scripts\python.exe -c "from openbb import obb; print(callable(obb.fmp_trading.report))"
.venv_win\Scripts\python.exe -c "s=open('openbb_platform/core/openbb/package/fmp_trading.py').read(); assert 'OBBject[' not in s; print('codegen clean')"
```

Expected: `2 passed`; `True`; `codegen clean`.

```
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/reporting/report_router.py openbb_platform/extensions/fmp_trading/openbb_fmp_trading/fmp_trading_router.py openbb_platform/extensions/fmp_trading/tests/unit/test_report_router.py
git commit -m "feat(fmp_trading): report() router command — md/xlsx/json/all (P5.1)"
```

---

## Task 5: `core/replay.py` — deterministic journal reconstruction

**Files:**
- Test: `openbb_platform/extensions/fmp_trading/tests/golden/test_replay_determinism.py`
- Fixture: `openbb_platform/extensions/fmp_trading/tests/fixtures/journals/2026-06-30_msft_aapl.ndjson`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/replay.py`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/session_router.py` (add `replay()` command)

**Consumes:** journal `Path`, `from_tick: int`, `to_tick: int | None`.
**Produces:** `SessionResult` reconstructed by feeding recorded ticks through the same `IntradaySession` state-machine used by `run()`. AC-8: byte-identical across 3 runs.

- [ ] **Step 1: Create the fixture journal (~50 events, tiny)**

Write `openbb_platform/extensions/fmp_trading/tests/fixtures/journals/2026-06-30_msft_aapl.ndjson` — one JSON object per line covering: `session_start`, ~40 `tick`/`signal`/`plan`/`order`/`fill` events on MSFT + AAPL, `session_end`. Keep it tiny (<100 lines) so the golden test is fast.

- [ ] **Step 2: Write the failing determinism test**

```python
"""Golden: AC-8 — same fixture journal → same SessionResult byte-for-byte across 3 runs."""

from __future__ import annotations

from pathlib import Path

import pytest

from openbb_fmp_trading.core.replay import replay_from_journal
from openbb_fmp_trading.reporting.json_manifest import render_json

FIXTURE = Path(__file__).parent.parent / "fixtures" / "journals" / "2026-06-30_msft_aapl.ndjson"


def test_replay_is_byte_identical_across_three_runs():
    a = replay_from_journal(FIXTURE)
    b = replay_from_journal(FIXTURE)
    c = replay_from_journal(FIXTURE)
    dump_a = render_json(a.session_result, a.journal)
    dump_b = render_json(b.session_result, b.journal)
    dump_c = render_json(c.session_result, c.journal)
    assert dump_a == dump_b == dump_c, "replay must be byte-identical across 3 runs (AC-8)"


def test_replay_range_slicing():
    partial = replay_from_journal(FIXTURE, from_tick=0, to_tick=10)
    assert partial.session_result.total_ticks <= 10
```

- [ ] **Step 3: Implement `core/replay.py`**

```python
"""Deterministic journal → SessionResult reconstruction (PRD §4.1, AC-8)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from openbb_fmp_trading.models.results import SessionResult
from openbb_fmp_trading.models.session_state import JournalEvent


@dataclass(frozen=True)
class ReplayResult:
    session_result: SessionResult
    journal: list[JournalEvent]


def _read_journal(path: Path) -> list[JournalEvent]:
    events: list[JournalEvent] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            events.append(JournalEvent.model_validate_json(line))
    return events


def replay_from_journal(
    journal_path: Path,
    from_tick: int = 0,
    to_tick: int | None = None,
) -> ReplayResult:
    """Reconstruct a SessionResult from a journal deterministically."""
    from openbb_fmp_trading.core.intraday_session import IntradaySession  # lazy

    events = _read_journal(journal_path)
    tick_indices = [i for i, e in enumerate(events) if e.event_type == "tick"]
    if to_tick is not None and to_tick < len(tick_indices):
        cutoff = tick_indices[to_tick]
        events = events[: cutoff + 1]
    if from_tick > 0 and from_tick < len(tick_indices):
        start = tick_indices[from_tick]
        events = events[start:]

    session = IntradaySession.reconstruct_from_events(events)
    return ReplayResult(session_result=session.finalize(), journal=events)
```

- [ ] **Step 4: Add `replay()` command to `session_router.py`**

```python
@router.command(methods=["POST"])
def replay(
    journal_path: Path,
    from_tick: int = 0,
    to_tick: int | None = None,
) -> OBBject:
    """Replay a journal deterministically → SessionResult. PRD §4.1."""
    from openbb_fmp_trading.core.replay import replay_from_journal
    result = replay_from_journal(journal_path, from_tick=from_tick, to_tick=to_tick)
    return OBBject(results=result.session_result.model_dump(mode="json"))
```

- [ ] **Step 5: Run golden + rebuild + commit**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/golden/test_replay_determinism.py -v
.venv_win\Scripts\python.exe -c "import openbb; openbb.build()"
.venv_win\Scripts\python.exe -c "from openbb import obb; print(callable(obb.fmp_trading.replay))"
```

Expected: `2 passed`; `True`.

```
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/replay.py openbb_platform/extensions/fmp_trading/openbb_fmp_trading/session_router.py openbb_platform/extensions/fmp_trading/tests/golden/test_replay_determinism.py openbb_platform/extensions/fmp_trading/tests/fixtures/journals/2026-06-30_msft_aapl.ndjson
git commit -m "feat(fmp_trading): replay() command + AC-8 byte-identical golden test (P5.3)"
```

---

## Task 6: `README.md` — user-facing entry doc

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/README.md`

Mirror the techtrade README structure: codegen constraint note at the top → install → quickstart → commands → extras matrix → For Contributors. Full content template in the working reference. Commit with `docs(fmp_trading): user-facing README with install + quickstart + commands (P5.4)`.

---

## Task 7: `docs/cli_reference.md` — per-subcommand reference

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/docs/cli_reference.md`

One section per `openbb-daytrade` subcommand: `run`, `plan`, `snapshot`, `alert`, `replay`, `report`, `doctor`. Each section: flags table, example, exit codes (0/1/2/3/4/5/78). Commit with `docs(fmp_trading): per-subcommand CLI reference (P5.4)`.

---

## Task 8: `config_examples/*.yaml` — three starter configs

Three YAMLs (`momentum_default.yaml`, `conservative.yaml`, `aggressive.yaml`) plus a round-trip test asserting each validates against `DailyConfig.model_validate()`. Commit with `docs(fmp_trading): three starter config examples + round-trip test (P5.4)`.

---

## Task 9: Final acceptance gates — lint, rebuild, whole-suite green

- [ ] **Step 1: Ruff clean** — `.venv_win\Scripts\python.exe -m ruff check openbb_platform/extensions/fmp_trading` → `All checks passed!`
- [ ] **Step 2: Full unit + golden suite** — `pytest -m "not integration" -v` — all Phase 1..5 tests pass
- [ ] **Step 3: Rebuild + namespace probe (bare `OBBject` proof)** — `openbb.build()` exit 0; `obb.fmp_trading.report/replay` callable; `'OBBject[' not in fmp_trading.py`
- [ ] **Step 4: Techtrade suite unaffected** — regression check
- [ ] **Step 5: Generated files NOT staged** — `git status --porcelain openbb_platform/core/openbb/package/`
- [ ] **Step 6: Report status; do NOT push without user confirmation**

---

## Self-Review Notes

**PRD §10 Phase 5 coverage:**
- P5.1 `report()` MD + XLSX + JSON → Tasks 1–4. ✓
- P5.2 techtrade XLSX reuse + 3 intraday sheets → Task 3. ✓
- P5.3 `replay()` byte-identical → Task 5 + AC-8 golden. ✓
- P5.4 README + CLI docs + config examples → Tasks 6–8. ✓

**Global constraints respected:**
- Provider always `fmp_cached`
- Every router command returns bare `OBBject` — verified in Task 4 Step 3 and Task 9 Step 3
- `Decimal` for prices
- Deterministic serialization (sorted keys, Decimal→str, no `datetime.now()`)

**Deferred:**
- Backtest bridge / `validate` → P6.1
- HTML/PDF renderers → v2
- Webhook / email / push delivery → v2 (NG7)
- `next_day_hints` auto-apply → PRD Q2
