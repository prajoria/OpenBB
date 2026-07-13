# openbb-fmp-trading

Intraday day-trading automation extension for the OpenBB Platform.

Deterministic execution core (Phase 2) with an opt-in agentic discovery
layer (Phase 3, `[agent]` extra) and post-session reporting + replay
(Phase 5). Composes on `openbb-techtrade` unchanged; talks only to
`fmp_cached` (never raw `fmp` in application code).

**Design docs:**
- PRD: `docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md`
- Phase 3 design: `docs/superpowers/specs/2026-07-10-fmp-trading-phase3-agent-turns-design.md`
- Phase 5 design: `docs/superpowers/specs/2026-07-10-fmp-trading-phase5-report-replay-design.md`

## Status

| Phase | Status | Highlights |
|---|---|---|
| Phase 0 — Prerequisites | ✅ | FMP + fmp_cached parity guardrails |
| Phase 1 — Core primitives | ✅ | `openbb_core_journal`, RiskManager (8 gates), BandwidthMeter, doctor |
| Phase 2 — Market-hours execution | ✅ | Tier-1 caching, `IntradaySession`, tick loop, flat-by-close, AC-1/5/6 |
| Phase 3 — Agentic discovery | ✅ | `[agent]` extra, PreOpen + PostClose turns, MCP server (closes #84 + #85) |
| Phase 4 — AlertManager | ⏸️ | Deferred |
| Phase 5 — Reporting + polish | ✅ | `report()` (MD + XLSX + JSON), `replay()`, README |
| Phase 6 — Validation, launch | ⏸️ | Backtest bridge, live-integration validation |

## Installation

```bash
# Core (deterministic execution only)
pip install -e openbb_platform/extensions/fmp_trading

# With the [agent] extra (adds Claude backend + MCP server + Jinja narrator)
pip install -e "openbb_platform/extensions/fmp_trading[agent]"
```

Both trigger the platform rebuild (`obb.build()`) automatically.

## Configuration

Standard OpenBB credentials in `~/.openbb_platform/user_settings.json`:

```json
{
  "credentials": {
    "fmp_cached_api_key": "YOUR_KEY_HERE",
    "mysql_host": "localhost",
    "mysql_port": 3306,
    "mysql_user": "openbb_user",
    "mysql_password": "your_password",
    "mysql_database": "openbb_cache"
  }
}
```

Plus optional per-day config at `~/.openbb_platform/fmp_trading/today.yaml`
(see `config_examples/` for starter templates).

## Quickstart

```bash
# 1. Verify your environment
openbb-daytrade doctor

# 2. Start the MCP server (optional; requires [agent] extra)
openbb-daytrade mcp-serve

# 3. After a session ends — render the report
openbb-daytrade report --session s20260713143025 --format all

# 4. Replay a session deterministically (regression testing / audit)
openbb-daytrade replay --session s20260713143025
```

## CLI Reference

Full per-subcommand reference: [`docs/cli_reference.md`](docs/cli_reference.md).

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `FMP_TRADING_REPORTS_ROOT` | Jail root for `report()` output. `output_dir` outside this path is rejected. | `Analysis/exports/` (relative to cwd) |
| `ANTHROPIC_API_KEY` | Required for `[agent]` extra's `ClaudeAgentBackend`. | — |

## Config Examples

`config_examples/` ships three starter templates. Filenames encode BOTH
axes (strategy preset + risk tuning) so an operator can't accidentally
load an "aggressive" file expecting momentum and get mean-reversion.

| File | Preset | Risk tuning |
|---|---|---|
| `intraday_momentum-moderate.yaml` | intraday_momentum | moderate (PRD defaults) |
| `trend_follow-conservative.yaml` | trend_follow | conservative (tighter G-gates) |
| `mean_revert-aggressive.yaml` | mean_revert | aggressive (looser G-gates, higher position count) |

## Journal + Replay

Journal + replay use the shared `openbb-core-journal` primitive
(`openbb_platform/core/openbb_core_journal/`, epic #408) — no local
SessionJournal module in this extension. Typed event subclasses for
fmp_trading (TickEvent, SignalEvent, OrderEvent, FillEvent, VetoEvent,
AlertFiredEvent, RiskStateChangeEvent, SessionStart/EndEvent,
DailyPlanCommittedEvent, EndOfDayReportEvent, AgentFallbackEvent,
PromptInjectionRejectedEvent) live in
`openbb_fmp_trading/models/journal_events.py`.

Journals are on-disk NDJSON at
`~/.openbb_platform/fmp_trading/journals/<session_id>.ndjson`. `replay()`
drives a fresh `IntradaySession` through the recorded ticks and compares
emitted vs recorded events — divergence surfaces as
`ReplayDivergenceError` with `(tick_index, event_type, field, expected,
actual)` context.

## Provider rule

`fmp_cached` is the only provider used in application code. Never raw
`fmp`; never `yfinance`. Enforced by
`openbb_platform/tests/architecture/test_provider_purity.py`.
