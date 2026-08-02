"""Techtrade Trading-Desk story — 12 steps mapped to NB01-NB06.

Design spec: docs/superpowers/specs/2026-08-01-browser-test-harness-design.md §6.2
Preview guide: docs/browser_test_harness/preview_guides/techtrade-manual-guide-preview.md
"""

from __future__ import annotations

from ..steps import ActionKind, Persona, Step, Story

_STEPS: tuple[Step, ...] = (
    # ==================================================================
    # Act 1 — Morning Scan (T1) — NB01/NB02
    # ==================================================================
    Step(
        id="T1.morning-scan",
        story="techtrade",
        notebook_ref="notebooks/techtrade/02-morning-scan.ipynb",
        persona=Persona.SYSTEMATIC_TRADER,
        tab_id="morning-scan",
        action=ActionKind.OBSERVE,
        human_title="Step T1 — Read the segment movers + scan table",
        human_description="Open the Morning Scan tab, read both widgets.",
        human_expected="6 segment rows (3 gainers, 3 losers) and 6 ticker rows.",
        endpoint="tt/scan/segment-movers",
    ),
    Step(
        id="T1.filter",
        story="techtrade",
        notebook_ref="notebooks/techtrade/02-morning-scan.ipynb",
        persona=Persona.SYSTEMATIC_TRADER,
        tab_id="morning-scan",
        action=ActionKind.INPUT,
        human_title="Step T1 — Filter the scan table by segment",
        human_description="Set segment=Technology on tt_scan_table.",
        human_expected="3 rows: NVDA, AAPL, MSFT.",
        endpoint="tt/scan/table",
        params={"segment": "Technology"},
    ),
    # ==================================================================
    # Act 2 — Position Workbench (T2) — NB03
    # ==================================================================
    Step(
        id="T2.signal-card",
        story="techtrade",
        notebook_ref="notebooks/techtrade/03-single-position-deep-dive.ipynb",
        persona=Persona.SYSTEMATIC_TRADER,
        tab_id="position-workbench",
        action=ActionKind.OBSERVE,
        human_title="Step T2 — Read the signal card for NVDA",
        human_description="Set symbol=NVDA, read tt_signal_card.",
        human_expected="Signal type BREAKOUT, direction LONG, confidence 0.87.",
        endpoint="tt/position/signal-card",
        params={"symbol": "NVDA"},
    ),
    Step(
        id="T2.plan-card",
        story="techtrade",
        notebook_ref="notebooks/techtrade/03-single-position-deep-dive.ipynb",
        persona=Persona.SYSTEMATIC_TRADER,
        tab_id="position-workbench",
        action=ActionKind.OBSERVE,
        human_title="Step T2 — Read the plan card",
        human_description="Read tt_plan_card.",
        human_expected="Entry $173.50, Stop $168.20, Target $189.00, R:R 2.9x.",
        endpoint="tt/position/plan-card",
        params={"symbol": "NVDA"},
    ),
    Step(
        id="T2.order-legs",
        story="techtrade",
        notebook_ref="notebooks/techtrade/03-single-position-deep-dive.ipynb",
        persona=Persona.SYSTEMATIC_TRADER,
        tab_id="position-workbench",
        action=ActionKind.OBSERVE,
        human_title="Step T2 — Read the order legs table",
        human_description="Read tt_order_legs.",
        human_expected="3 rows (ENTRY, STOP, TARGET) with side, quantity, price, order_type.",
        endpoint="tt/position/order-legs",
        params={"symbol": "NVDA"},
    ),
    Step(
        id="T2.simulate",
        story="techtrade",
        notebook_ref="notebooks/techtrade/03-single-position-deep-dive.ipynb",
        persona=Persona.SYSTEMATIC_TRADER,
        tab_id="position-workbench",
        action=ActionKind.OBSERVE,
        human_title="Step T2 — Read the simulated P&L chart",
        human_description="Read tt_simulate_result.",
        human_expected="15 daily P&L values ranging 0 to 118 with two drawdown wobbles.",
        endpoint="tt/position/simulate",
        params={"symbol": "NVDA"},
    ),
    # ==================================================================
    # Act 3 — Validation (T3) — NB04
    # ==================================================================
    Step(
        id="T3.verdict",
        story="techtrade",
        notebook_ref="notebooks/techtrade/04-validation-gate.ipynb",
        persona=Persona.SYSTEMATIC_TRADER,
        tab_id="validation",
        action=ActionKind.OBSERVE,
        human_title="Step T3 — Read the validation verdict",
        human_description="Read tt_validation_verdict on the Validation tab.",
        human_expected=(
            "4 rows: PBO 0.18/PASS, DSR 1.47/PASS, OOS Sharpe 1.62/PASS, "
            "Verdict PASS. Verdict is a discrete gate — PASS or FAIL only."
        ),
        endpoint="tt/validation/verdict",
        params={"symbol": "AAPL"},
    ),
    # ==================================================================
    # Act 4 — Tuning (T4) — NB05
    # ==================================================================
    Step(
        id="T4.tuning",
        story="techtrade",
        notebook_ref="notebooks/techtrade/05-tuning-per-sector.ipynb",
        persona=Persona.SYSTEMATIC_TRADER,
        tab_id="tuning",
        action=ActionKind.OBSERVE,
        human_title="Step T4 — Read the tuning report",
        human_description="Read tt_tuning_report.",
        human_expected=(
            "4 param rows (atr_period, sma_fast, sma_slow, risk_pct) with "
            "current, proposed, delta, and per-param validate_gate PASS or FAIL."
        ),
        endpoint="tt/tuning/report",
        params={"symbol": "AAPL"},
    ),
    # ==================================================================
    # Act 5 — Engine Status + Execute Bridge (T5) — NB06
    # ==================================================================
    Step(
        id="T5.engine-status",
        story="techtrade",
        notebook_ref="notebooks/techtrade/06-audit-and-replay.ipynb",
        persona=Persona.SYSTEMATIC_TRADER,
        tab_id="engine-status",
        action=ActionKind.OBSERVE,
        human_title="Step T5 — Read the engine status",
        human_description="Read tt_engine_status on the Engine Status tab.",
        human_expected="Scheduler RUNNING, Signal engine READY, Execution engine IDLE.",
        endpoint="tt/engine/status",
    ),
    Step(
        id="T5.execute-blocked",
        story="techtrade",
        notebook_ref="notebooks/techtrade/06-audit-and-replay.ipynb",
        persona=Persona.SYSTEMATIC_TRADER,
        tab_id="engine-status",
        action=ActionKind.ASSERT,
        human_title="Step T5 — Verdict FAIL blocks the execute bridge",
        human_description=(
            "Set verdict=FAIL on tt_execute_bridge. Body MUST contain BLOCKED "
            "and MUST NOT contain READY (belt-and-suspenders per PR #1720)."
        ),
        human_expected="Markdown body reads 'Execute Bridge: BLOCKED'.",
        endpoint="tt/execute/bridge",
        params={"verdict": "FAIL"},
        tags=("safety", "checker:blocked-not-ready"),
    ),
    Step(
        id="T5.execute-ready",
        story="techtrade",
        notebook_ref="notebooks/techtrade/06-audit-and-replay.ipynb",
        persona=Persona.SYSTEMATIC_TRADER,
        tab_id="engine-status",
        action=ActionKind.ASSERT,
        human_title="Step T5 — Verdict PASS unblocks the execute bridge",
        human_description="Set verdict=PASS. Body should contain READY.",
        human_expected="Markdown body reads 'Execute Bridge: READY'.",
        endpoint="tt/execute/bridge",
        params={"verdict": "PASS"},
        tags=("safety", "checker:ready-signal-present"),
    ),
    # ==================================================================
    # Act 6 — Audit Journal (T6) — NB06
    # ==================================================================
    Step(
        id="T6.audit",
        story="techtrade",
        notebook_ref="notebooks/techtrade/06-audit-and-replay.ipynb",
        persona=Persona.SYSTEMATIC_TRADER,
        tab_id="audit",
        action=ActionKind.OBSERVE,
        human_title="Step T6 — Read the audit journal",
        human_description="Read tt_audit_journal on the Audit tab.",
        human_expected="5 rows with bar_date, replay_pnl, forward_pnl, deviation_bps.",
        endpoint="tt/audit/journal",
        params={"symbol": "AAPL"},
    ),
)

STORY = Story(
    id="techtrade",
    title="Techtrade Trading-Desk (T1-T6)",
    notebook_series_root="notebooks/techtrade/",
    steps=_STEPS,
)
