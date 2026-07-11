# PRD & Functional Spec: FMP Day-Trading Automation (`openbb-fmp-trading`)

**Status:** Draft / Proposal — for review (Sections 1-13 + appendices complete)
**Author:** Trading Automation working group
**Target component:** `openbb-fmp-trading` — new first-party OpenBB extension
**Branch:** `fmp_trading`
**Date:** 2026-07-06
**Closes epics:** #87, #84, #85, #231 (+ absorbs #88, #91)
**Companion documents:**
- [`docs/Specs/TechnicalTrading-Engine-PRD.md`](../../Specs/TechnicalTrading-Engine-PRD.md) — parent techtrade PRD; this extension composes on it unchanged
- [`docs/Specs/Backtesting-Engine-PRD.md`](../../Specs/Backtesting-Engine-PRD.md) — `openbb-backtest`, validation dependency
- [`docs/OpenBBPlatform/architecture/providers/fmp-cached.md`](../../OpenBBPlatform/architecture/providers/fmp-cached.md) — fmp/fmp_cached two-tier caching architecture

**Decision posture:** Industry-standard intraday day-trading automation. Deterministic execution core (mirrors techtrade doctrine); agentic discovery layer confined to pre-open and post-close. Hold no bars on ambition; explicit non-goals on live routing + options + UX.

**Provider posture:** `fmp` and `fmp_cached` maintained in **full parity** — every new fetcher this PRD adds ships in both providers in the same commit. Tier-1 gap-detection caching for high-volume time-series (intraday bars, aftermarket quotes); tier-2 passthrough for the rest. Never call raw `fmp` in application code — always `fmp_cached`.

---

## Table of Contents

1. [Extension Identity & Epic-Fill Mapping](#1-extension-identity--epic-fill-mapping)
2. [Goals, Principles, and Success Criteria](#2-goals-principles-and-success-criteria)
3. [Architecture](#3-architecture)
4. [Capability Modules (Command Surface)](#4-capability-modules-command-surface)
5. [FMP / fmp_cached Parity Matrix](#5-fmp--fmp_cached-parity-matrix)
6. [Data Models](#6-data-models)
7. [Agent Turns Specification](#7-agent-turns-specification)
8. [Risk Manager & Session State](#8-risk-manager--session-state)
9. [Non-Functional Requirements](#9-non-functional-requirements)
10. [Phased Delivery Roadmap](#10-phased-delivery-roadmap)
11. [Testing Strategy](#11-testing-strategy)
12. [Risks & Mitigations](#12-risks--mitigations)
13. [Open Questions](#13-open-questions)
14. [Appendix A — FMP Endpoint Inventory](#appendix-a--fmp-endpoint-inventory)
15. [Appendix B — Glossary](#appendix-b--glossary)

---

## 1. Extension Identity & Epic-Fill Mapping

**Extension name:** `openbb-fmp-trading`
**Implementation path:** `openbb_platform/extensions/fmp_trading/`
**CLI entrypoint:** `openbb-daytrade`
**Router prefix:** `obb.fmp_trading.*`
**Layout:** Mirrors `openbb-techtrade` — `openbb_fmp_trading/{models,router,core,engine,agent}/`.

### 1.1 Epics closed by this PRD

| Epic | Title | Scope covered |
|---|---|---|
| **#87** | P9 (future) — streaming/intraday + live broker | (a) O(1) streaming indicators via `talipp`; (b) hourly/minute bars via new fetchers; (c) `BrokerInterface` swap-in path documented for Alpaca (no live routing in v1 — NG1 stays intact); (d) full parity with techtrade batch pipeline |
| **#84** | Narrator (deterministic briefing) | Delivered as the **post-close agent turn** in Approach C; deterministic fallback template when the agent extra is absent |
| **#85** | MCP tool exposure + core-unchanged-when-removed test | Whole `obb.fmp_trading.*` surface exposed via MCP under `[agent]` extra with the same enforced test pattern #85 requires |
| **#231** | Design specs for #84 + #85 | This PRD is that spec |
| **#88** | Dual entry options (market + limit) | Absorbed into intraday `EntryRule`; limit + market both supported with ATR-based limit-offset presets |
| **#91** | 3-tier FMP/CBOE historical-data fallback | Repurposed as intraday 3-tier: fmp_cached → fmp → cboe (options context only); reuses the 1088-LoC fallback that's currently orphaned |
| **Analysis #279/#280/#281** | Options integration via cboe | **Not absorbed** (out of scope), but the cboe provider work these define is a **prerequisite dependency** — flagged in Roadmap |

### 1.2 Non-goals (explicit)

- **NG1** — No live order routing in v1. Same posture as techtrade #78. `BrokerInterface` is live-ready; Alpaca/IBKR implementation is a future PR with its own legal + UX review.
- **NG2** — No new signal math. Every quantitative operation calls `obb.techtrade.*` or `obb.technical.*`. Missing capability files a techtrade issue as a blocking dependency, not a workaround here.
- **NG3** — No UX / desktop / notebook work. CLI + agent + MCP only. Excel export reused from `techtrade[xlsxwriter]`.
- **NG4** — No options trading. FMP has no options surface. Options *context* (IV/RV) can inform signals once Analysis Phase-D2 lands cboe; options orders/positions are out of v1 scope.
- **NG5** — No sub-minute scalping. Minimum bar interval 1min (FMP's minimum). Poll cadence 5-15s for quotes, 1-5min for bars.
- **NG6** — Not a general-purpose trading platform. FMP is sole data primary; cboe is opt-in for options context only. No yfinance/polygon/tradier fallbacks.
- **NG7** — AlertManager v1 delivers only to session log + agent context. No email, SMS, push, or webhook. All external-delivery is v2.

### 1.3 Follow-up issues this PRD files

1. `fmp: migrate equity_gainers/losers/most_active fetchers to /stable/* endpoints` — tech-debt, low priority. Current fetchers still call legacy `/api/v3/stock_market/*`; FMP has migrated to `/stable/biggest-*`. Behavior identical today; no deprecation date announced.
2. `openbb-fmp-trading v2: AlertManager delivery (webhook, push, email)` — deferred per NG7.
3. `openbb-fmp-trading v2: pattern-based alerts (breakout, wedge, chart-formation ML)` — deferred per NG7.

---

## 2. Goals, Principles, and Success Criteria

### 2.1 Goals

- **G1** — Fill epic #87 with a shipping deliverable. By end of PRD roadmap: `openbb-fmp-trading` is installable, green test suite, drives PaperBroker fills against real intraday data. Epic #87 closable.
- **G2** — Full `fmp`/`fmp_cached` parity for intraday. Every intraday endpoint the extension needs exists in both providers on the same PR. Tier-1 caching for the two high-volume endpoints (intraday bars, aftermarket quotes); tier-2 passthrough for the rest.
- **G3** — Reuse techtrade unchanged. No signal math, no indicator math, no confluence math written here. Every quantitative operation calls `obb.techtrade.*` or `obb.technical.*`.
- **G4** — Deterministic execution, agentic discovery. Market-hours order execution is a pure function of (config, tick sequence, market data). Agent turns confined to pre-open (07:00-09:30 ET) and post-close (16:00-17:00 ET); each is one-shot and auditable.
- **G5** — Live-broker-ready without live routing. `BrokerInterface` swap is a documented one-file diff. Paper broker stays the only implementation in v1 (NG1).
- **G6** — Agent surface without agent lock-in. Everything the agent turn does is also callable from the CLI as a deterministic command. The agent extra is a Poetry `[agent]` optional dependency — the "core-unchanged-when-removed" test from #85 applies identically.
- **G7** — Session-first observability. Every session writes an NDJSON journal — one row per tick, signal, order, fill, alert. Excel end-of-day report + JSON manifest for downstream analytics.

### 2.2 Guiding principles

Inherited from techtrade:
- **P1** — Deterministic signal core, agent is optional shell
- **P2** — `Decimal` for money and share counts; no float drift
- **P3** — No look-ahead: signal on bar-t → fill at t+1, enforced by golden test

Intraday-specific:
- **P4** — **No overnight positions in v1.** Every open position flattened by 15:55 ET (5-min buffer before close) unless `--allow-overnight` is passed with an explicit hold reason. The single most important risk control in day trading.
- **P5** — **Every clock decision uses `exchange_calendars`.** No naive `datetime.now()`. Pre-market start, RTH open, half-days, holidays, exchange-specific — all through the calendar. Testable with frozen clocks.
- **P6** — **Bandwidth is a first-class constraint.** Every FMP call carries an estimated payload size against session budget. At 80% of monthly bandwidth, session enters "conservation mode" (short-quote endpoints only, longer polling intervals, no full-batch snapshots). Asserted in tests per tier.
- **P7** — **RiskManager veto is the source of truth on trade admission.** Neither CLI, agent, nor direct `plan()` call can bypass it. Every path funnels through `risk_manager.propose_trade(plan) → APPROVED | REJECTED(reason)`.

### 2.3 Success criteria — how we know v1 is done

| # | Criterion | How measured |
|---|---|---|
| **AC-1** | Full paper session runs end-to-end without operator intervention from pre-open agent turn through post-close narrative | Integration test: mock FMP → simulated 6.5h trading day → assert NDJSON journal has expected event counts + `flat_at_close=True` |
| **AC-2** | Every intraday FMP fetcher has an `fmp_cached` twin registered in the same commit | CI test: `set(fmp.fetchers) ⊂ set(fmp_cached.fetchers)` |
| **AC-3** | Tier-1 caching for intraday bars hits ≥ 95% on a 1-day session replay after the first tick | Test: replay same day twice, assert 2nd run makes < 5% of the FMP calls of the 1st |
| **AC-4** | Removing the `[agent]` extra leaves every deterministic command working | The "core-unchanged-when-removed" test from #85 |
| **AC-5** | No look-ahead in intraday: bar-t 5-min close signal fills at t+1 5-min open | Golden test locking the pattern like techtrade #78 |
| **AC-6** | RiskManager rejects every attempt to add a position after 15:50 ET | Test: submit order at 15:51 → assert `REJECTED(reason="flat_by_close_window")` |
| **AC-7** | Bandwidth conservation mode triggers correctly | Test: fake 80% budget consumed → assert next tick uses `quote-short` instead of `batch-quote` |
| **AC-8** | Deterministic-only session (no agent) produces identical NDJSON journal across 3 runs of the same day-replay | Golden equality test |
| **AC-9** | v1 delivers all four target epics per §1.1 | Each epic closable with reference to this PRD's implementation issues |

---

## 3. Architecture

### 3.1 Component diagram

```
┌────────────────────────────────────────────────────────────────────────────┐
│ USER MACHINE                                                                │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │ CLI: openbb-daytrade                                                   │ │
│  │   subcommands: run | plan | replay | report | alert | doctor          │ │
│  └────────────────┬──────────────────────────────────────────────────────┘ │
│                   │                                                          │
│  ┌────────────────▼──────────────────────────────────────────────────────┐ │
│  │ IntradayOrchestrator (owns the day, top-level state machine)           │ │
│  │                                                                        │ │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐   │ │
│  │  │ PreOpenAgentTurn│──▶ │ IntradaySession │ ──▶│ PostCloseAgentTurn│  │ │
│  │  │ (one-shot LLM)  │    │ (deterministic  │    │  (one-shot LLM)  │   │ │
│  │  │ 07:00–09:29 ET  │    │  tick loop)     │    │  16:00–17:00 ET  │   │ │
│  │  │                 │    │ 09:30–15:55 ET  │    │                  │   │ │
│  │  │  outputs:       │    │                 │    │  reads: journal  │   │ │
│  │  │  DailyPlan      │    │  reads:DailyPl  │    │  outputs:        │   │ │
│  │  │                 │    │  writes:journal │    │  end_of_day.md   │   │ │
│  │  │                 │    │  emits: alerts  │    │  preset_review   │   │ │
│  │  │                 │    │  flat-by-close  │    │  next_day_hints  │   │ │
│  │  └─────────────────┘    └────────┬────────┘    └─────────────────┘   │ │
│  │                                  │                                     │ │
│  │  ┌──────────────────────────────▼────────────────────────────────┐   │ │
│  │  │ RiskManager (single source of truth on trade admission)        │   │ │
│  │  │  gates: max_position_size, day_dd, sector_cap, flat_by_close,  │   │ │
│  │  │         open_position_count, per_symbol_cooldown_after_stopout │   │ │
│  │  │  interface: propose_trade(plan) → APPROVED | REJECTED(reason)  │   │ │
│  │  └────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                        │ │
│  │  ┌──────────────────────────┐    ┌───────────────────────────────┐   │ │
│  │  │ AlertManager v1          │    │ SessionJournal (NDJSON writer)│   │ │
│  │  │  eval(alerts, tick)      │    │  events: tick, signal, order, │   │ │
│  │  │  emits: session log +    │    │          fill, alert, veto,   │   │ │
│  │  │  agent context           │    │          risk_state, mode     │   │ │
│  │  └──────────────────────────┘    └───────────────────────────────┘   │ │
│  │                                                                        │ │
│  │  ┌────────────────────────────────────────────────────────────────┐   │ │
│  │  │ BandwidthMeter (P6: bandwidth as first-class constraint)       │   │ │
│  │  │  budgets calls per endpoint, tracks month-to-date consumption, │   │ │
│  │  │  triggers "conservation mode" at 80%, hard-caps at 95%         │   │ │
│  │  └────────────────────────────────────────────────────────────────┘   │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌────────────────── REUSED (unchanged) ────────────────────────────────┐  │
│  │  obb.techtrade.*                                                      │  │
│  │    signals, plan, orders, simulate, PaperBroker,                      │  │
│  │    Recommendation, movers, segments, panels, confluence, presets      │  │
│  │  obb.equity.discovery.*  (gainers/losers/actives — via fmp_cached)    │  │
│  │  obb.news.*  (company_news for pre-open agent)                        │  │
│  │  obb.regulators.sec.*  (8-K feed for pre-open agent)                  │  │
│  │  obb.equity.ownership.*  (insider + government_trades)                │  │
│  │  obb.technical.*  (fallback indicator adapter — techtrade owns first) │  │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌────────────────── NEW providers (in this PRD) ───────────────────────┐  │
│  │  obb.fmp_trading.*  (this extension's router)                         │  │
│  │  openbb_fmp: 6 new fetchers (intraday bars, aftermarket q/t, etc.)    │  │
│  │  openbb_fmp_cached: same 6 registered (2 tier-1, 4 tier-2)            │  │
│  └───────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Session lifecycle (one trading day)

```
07:00 ET  IntradayOrchestrator boots
          ├─ load DailyConfig from ~/.openbb_platform/fmp_trading/today.yaml
          ├─ verify FMP credentials, MySQL cache health, BandwidthMeter reset if new month
          ├─ verify exchange_calendars: is today a trading day? early-close?
          └─ if not trading day → exit code 78 ("no-op day")

07:30 ET  PreOpenAgentTurn fires (one-shot; ~2-5 min of agent time)
          ├─ agent tools available: gainers/losers/actives, news, 8-K filings,
          │                        insider_trading, government_trades,
          │                        earnings_calendar, market_snapshot,
          │                        techtrade.movers, sector_performance
          ├─ agent must produce DailyPlan:
          │    watchlist:      list[str]         # 10-30 symbols
          │    preset:         str              # "intraday_momentum" | "intraday_gap" | custom
          │    alerts:         list[AlertSpec]  # symbol × condition rules
          │    session_risk:   RiskConfig       # max_positions, day_dd_pct, sector_caps
          │    thesis:         str              # LLM's narrative "why today"
          └─ DailyPlan validated + written to journal + committed to session

09:30 ET  IntradaySession begins tick loop
          poll_interval = 5s for quotes, 60s for bars, driven by preset
          for each tick t:
              ├─ fetch: batch_quote(watchlist), aftermarket if pre-open, session-status
              ├─ every N ticks: fetch intraday bars, rebuild panels, run confluence
              ├─ evaluate: signals → plan → orders → RiskManager.propose_trade(plan)
              ├─          alerts.evaluate(alerts, tick) → alert events
              ├─ approved trades: PaperBroker.simulate() → Fill
              ├─ rejected trades: journal(REJECTED, reason)
              ├─ open positions: check stop/target/time_stop/trailing → exit orders
              ├─ BandwidthMeter.charge(estimated_bytes)
              │   if >80%: switch to conservation mode (short quotes only)
              └─ SessionJournal.write(all events)

15:50 ET  Flat-by-close window opens
          RiskManager rejects all new opens
          existing positions get MARKET SELL orders queued for 15:55

15:55 ET  Position-flatten window
          all remaining positions closed at next-bar-open (15:56 or 15:57 ET)

16:00 ET  Session closes; final journal flush; NDJSON manifest written

16:15 ET  PostCloseAgentTurn fires (one-shot)
          agent reads journal + writes:
              ├─ end_of_day.md (narrative)
              ├─ preset_review (which votes worked; suggested weight tilts)
              ├─ next_day_hints (symbols to watch tomorrow based on today's setups)
              └─ end_of_day.xlsx (via existing techtrade.export machinery)

17:00 ET  Orchestrator exits code 0 (or 1 on any risk breach mid-session)
```

### 3.3 The tick loop in detail

```
                          ┌─────────────────────┐
                          │  Tick clock (5s)    │
                          └──────────┬──────────┘
                                     │
        ┌─── every 5s ────┐          │           ┌──── every 5min ────┐
        │                 │          │           │                     │
        ▼                 ▼          ▼           ▼                     ▼
  batch_quote_short   fetch aftermkt  fetch bars_intraday   techtrade.signals
       ↓                    ↓              ↓                        ↓
       └──────────┬─────────┴──────────────┴────────────┬───────────┘
                  │                                      │
                  ▼                                      ▼
          AlertManager.eval               techtrade.plan → TradePlan
                  │                                      │
                  ▼                                      ▼
          alert events (journal + agent)     RiskManager.propose_trade
                                                        │
                                       ┌────────────────┴─────────────┐
                                       ▼                              ▼
                                 APPROVED                        REJECTED(reason)
                                       │                              │
                                       ▼                              ▼
                          PaperBroker.simulate            journal(veto, reason)
                                       │
                                       ▼
                                     Fill
                                       │
                                       ▼
                          journal(order, fill)
                          update RiskManager.state
```

**Key correctness invariant** (P3): confluence signal computed off the close of bar `t` results in an order that fills no earlier than the open of bar `t+1`. Same discipline as techtrade #78 applied at 5min granularity. Golden test replicates the pattern (AC-5).

### 3.4 Agent boundary — what agents can and cannot do

The safety story that makes Approach C viable.

| Capability | Pre-open agent | Intraday (no agent) | Post-close agent |
|---|---|---|---|
| Read: market snapshot, news, filings, calendars | ✅ | — | ✅ (via journal) |
| Read: session journal, positions, P&L | ✅ (yesterday's) | — | ✅ (today's) |
| Write: DailyPlan (watchlist, preset, alerts, risk config) | ✅ | ❌ | ❌ |
| Write: `end_of_day.md`, preset_review, next_day_hints | ❌ | ❌ | ✅ |
| Submit orders / positions / trades | ❌ | ❌ (only IntradaySession, no LLM) | ❌ |
| Modify RiskManager gates mid-session | ❌ | ❌ | ❌ |
| Cancel/mutate open positions | ❌ | ❌ | ❌ |
| Adjust bandwidth budget | ❌ | ❌ | ❌ |
| Persist knowledge for tomorrow | ❌ | ❌ | ✅ (as hints, not auto-applied) |

Invariant: **an LLM never touches an order, a position, or the RiskManager state**. The agent influences *what the deterministic loop will do today* (pre-open) or *what humans should consider tomorrow* (post-close), but never *what the loop does right now*.

### 3.5 Live-broker swap path

`BrokerInterface` is the same Protocol techtrade #78 defined:
```python
@runtime_checkable
class BrokerInterface(Protocol):
    def submit(self, order: Order, bar: Bar) -> Fill | None: ...
    def cancel(self, order_ref: str) -> bool: ...
    def positions(self) -> list[Position]: ...
```

In v1, only `PaperBroker` implements it (unchanged, imported from techtrade). To land live trading later, `AlpacaBroker(BrokerInterface)` is a single new file that:
- Wraps `alpaca-py` in the same Protocol
- Requires its own credential store + user opt-in with legal ack
- Ships behind a **separate** Poetry extra `[live-broker-alpaca]` (never bundled)
- Is not part of this PRD's v1 scope (NG1)

**Design decision now:** IntradaySession, RiskManager, and every downstream consumer type-hint `BrokerInterface`, never `PaperBroker`. Adding Alpaca later is a one-file diff with no core refactors.

### 3.6 Failure modes and how they're handled

| Failure | Response |
|---|---|
| FMP rate-limit (429) | Exponential backoff + jitter; 3 attempts, then skip tick, log, continue |
| FMP 5xx | Same as 429 |
| FMP 401 (bad credentials) | Halt session, log, exit code 2 |
| MySQL cache down | Fall back to direct fmp (already the fmp_cached tier-1 pattern); log |
| Bandwidth exhausted (95%) | Halt new fetches, close all open positions, exit code 3 |
| Exchange half-day not detected | Session runs anyway; flat-by-close auto-adjusts via exchange_calendars |
| DailyPlan agent turn fails (LLM error) | Fall back to deterministic default (yesterday's watchlist + `trend_follow` preset), log downgrade |
| PostClose agent turn fails | Deterministic Recommendation-narrator template runs instead (identical to techtrade #84's fallback) |
| RiskManager veto storm (>10 vetoes/hour) | Halt session, log all vetoes with reasons, exit code 4 — likely a config bug |

---

## 4. Capability Modules (Command Surface)

The user-facing surface. Every command is callable from Python (`obb.fmp_trading.*`), REST (`/api/v1/fmp_trading/*`), CLI (`openbb-daytrade <subcommand>`), and MCP (when `[agent]` extra installed). Grouped by responsibility.

### 4.1 Session orchestration (`obb.fmp_trading.*`)

The high-level commands that own the day.

```python
obb.fmp_trading.run(
    config: DailyConfig | str | Path,       # inline object or path to today.yaml
    date: date | None = None,               # None = today; else replay
    dry_run: bool = False,                  # skip agent turns and PaperBroker fills
    allow_overnight: bool = False,          # opt-out of flat-by-close (§8 warn)
    agent_backend: str = "claude",          # "claude" | "openai" | "none"
) → OBBject[SessionResult]

obb.fmp_trading.replay(
    journal_path: Path,                     # NDJSON from a prior session
    from_tick: int = 0,
    to_tick: int | None = None,
) → OBBject[SessionResult]

obb.fmp_trading.doctor() → OBBject[HealthReport]
# Checks: FMP creds, MySQL cache health, bandwidth budget remaining,
# exchange_calendars data present, techtrade installed at compatible version,
# [agent] extra availability, [xlsxwriter] extra availability
```

**CLI mappings:**
```bash
openbb-daytrade run --config today.yaml
openbb-daytrade run --dry-run                     # smoke-test the wiring
openbb-daytrade replay --journal 2026-07-06.ndjson
openbb-daytrade doctor                             # health check before first session
```

### 4.2 Pre-open discovery (`obb.fmp_trading.market_snapshot`, `.build_daily_plan`)

Article-inspired snapshot primitive + the pre-open agent's DailyPlan builder.

```python
obb.fmp_trading.market_snapshot(
    top_n: int = 10,
    include: list[Literal["gainers","losers","actives"]] = ["gainers","losers","actives"],
    volatility_threshold_pct: float | None = None,     # filter to |change%| > threshold
    sector_rollup: bool = False,                        # join equity.profile.sector (cached)
    exchange: str = "NASDAQ",                           # single exchange filter
) → OBBject[MarketSnapshot]

obb.fmp_trading.build_daily_plan(
    agent: bool = True,                                 # False = deterministic default
    universe_hint: list[str] | None = None,             # nudge the agent
    max_watchlist_size: int = 20,
    preset_hint: str | None = None,                     # "intraday_momentum" | ...
) → OBBject[DailyPlan]
# When agent=True and [agent] extra installed: runs PreOpenAgentTurn (§7).
# When agent=False: deterministic default = yesterday's top-5 gainers + techtrade
# scan's top-15 movers, preset="intraday_momentum".
```

**CLI:**
```bash
openbb-daytrade plan --print-only                      # dry-run the DailyPlan without running
openbb-daytrade snapshot --top-n 20 --volatility 5
```

### 4.3 Intraday market data (`obb.fmp_trading.bars_*`, `.quote_*`, `.aftermarket_*`)

The new fetchers. All have fmp + fmp_cached parity per §5.

```python
obb.fmp_trading.bars_intraday(
    symbols: list[str],
    interval: Literal["1min","5min","15min","30min","1hour","4hour"] = "5min",
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    extended_hours: bool = False,
    provider: str = "fmp_cached",                       # NEVER call raw fmp in app code
) → OBBject[list[IntradayBar]]

obb.fmp_trading.quote_batch(
    symbols: list[str],
    short: bool = True,                                 # short=True by default (P6 bandwidth)
    provider: str = "fmp_cached",
) → OBBject[list[Quote]]

obb.fmp_trading.aftermarket_quote(
    symbols: list[str],
    provider: str = "fmp_cached",
) → OBBject[list[AftermarketQuote]]

obb.fmp_trading.aftermarket_trade(
    symbols: list[str],
    provider: str = "fmp_cached",
) → OBBject[list[AftermarketTrade]]

obb.fmp_trading.session_status(
    exchange: str = "NASDAQ",
    provider: str = "fmp_cached",
) → OBBject[SessionStatus]
# is_market_open, is_pre_market, is_after_market, next_open, next_close

obb.fmp_trading.technical_indicator(
    symbol: str,
    indicator: Literal["ADX","RSI","EMA","SMA","WMA","DEMA","TEMA","WilliamsR","StdDev"],
    period_length: int = 14,
    timeframe: Literal["1min","5min","15min","30min","1hour","4hour","1day"] = "5min",
    provider: str = "fmp_cached",
) → OBBject[list[IndicatorValue]]
# FMP's server-computed indicators — optional; techtrade's adapter is the primary path
```

### 4.4 AlertManager v1 (`obb.fmp_trading.alert.*`)

Threshold-based alerts. v1 delivery: session log + agent context only (NG7).

```python
obb.fmp_trading.alert.create(spec: AlertSpec) → OBBject[Alert]
# AlertSpec is a Union of:
#   PriceThresholdSpec(symbol, crosses="up"|"down", price=Decimal)
#   PercentChangeSpec(symbol, threshold_pct=float, window="session"|"1h"|"5m")
#   VolumeSpikeSpec(symbol, ratio_vs_avg=float, avg_window=20)

obb.fmp_trading.alert.list(active_only: bool = True) → OBBject[list[Alert]]
obb.fmp_trading.alert.delete(alert_id: str) → OBBject[StatusResult]
obb.fmp_trading.alert.evaluate(
    alerts: list[Alert],
    tick: TickData,
) → OBBject[list[AlertEvent]]
# Pure function; called every tick by IntradaySession.
# AlertEvent goes to: session journal (always), agent context (if agent listening).
# NO webhook, NO email, NO push in v1 (NG7).

obb.fmp_trading.alert.history(session_id: str) → OBBject[list[AlertEvent]]
```

**CLI:**
```bash
openbb-daytrade alert create --symbol AAPL --type price --up 180
openbb-daytrade alert list
openbb-daytrade alert delete <id>
```

### 4.5 Session state (`obb.fmp_trading.session.*`)

Read-only introspection into the live session. Never used to *mutate* state — that's the RiskManager's job.

```python
obb.fmp_trading.session.positions() → OBBject[list[Position]]
obb.fmp_trading.session.orders(status: str | None = None) → OBBject[list[Order]]
obb.fmp_trading.session.pnl() → OBBject[PnLSnapshot]
# realized_pnl, unrealized_pnl, day_pnl, day_dd_pct, positions_open, positions_closed
obb.fmp_trading.session.risk_state() → OBBject[RiskState]
# gates_active, gates_tripped_today, cooldowns, flat_by_close_window_open
obb.fmp_trading.session.bandwidth() → OBBject[BandwidthState]
# month_used_bytes, month_budget_bytes, mode="normal"|"conservation"|"halted"
obb.fmp_trading.session.journal(
    since: datetime | None = None,
    event_types: list[str] | None = None,
) → OBBject[list[JournalEvent]]
```

### 4.6 Post-close reporting (`obb.fmp_trading.report`)

Renders the session artifacts.

```python
obb.fmp_trading.report(
    session_id: str,
    format: Literal["md","xlsx","json","all"] = "all",
    output_dir: Path | None = None,        # default: Analysis/exports/daytrade_<date>/
    include_agent_narrative: bool = True,   # False = deterministic template only
) → OBBject[ReportManifest]
# md: end_of_day.md — narrative + trade table + preset review + next_day_hints
# xlsx: reuses techtrade.export (6-sheet workbook) + adds intraday sheets
# json: session manifest — every event, every fill, every alert
```

**CLI:**
```bash
openbb-daytrade report --session 2026-07-06 --format all
```

### 4.7 Router registration (following techtrade pattern)

```python
# openbb_fmp_trading/__init__.py
from openbb_core.app.router import Router

router = Router(prefix="/fmp_trading")
router.include_router(session_router,       prefix="")           # run/replay/doctor at root
router.include_router(snapshot_router,      prefix="")           # market_snapshot / build_daily_plan
router.include_router(data_router,          prefix="")           # bars_intraday / quote_batch / etc
router.include_router(alert_router,         prefix="/alert")
router.include_router(session_state_router, prefix="/session")
router.include_router(report_router,        prefix="")
```

After `pip install -e openbb_platform/extensions/fmp_trading` and platform rebuild:
- Python: `obb.fmp_trading.*`
- REST: `http://127.0.0.1:8000/api/v1/fmp_trading/*`
- CLI: `openbb-daytrade` (entry-point in `pyproject.toml`)
- MCP: all commands exposed under `[agent]` extra with `mcp_tools.py`

### 4.8 What the `[agent]` extra adds

Poetry extras:
```toml
[tool.poetry.extras]
agent = ["anthropic", "openai", "openbb-agents"]          # LLM backends
xlsxwriter = ["xlsxwriter"]                                # techtrade sibling
validation = ["openbb-backtest"]                           # techtrade validate bridge
```

The `[agent]` extra lights up:
- `PreOpenAgentTurn` (§7) — otherwise falls back to deterministic default
- `PostCloseAgentTurn` (§7) — otherwise falls back to techtrade Recommendation narrator
- MCP tool server (`openbb-daytrade mcp-serve`) exposing every §4.1-4.6 command as an MCP tool
- The **"core-unchanged-when-removed" test** from #85: uninstall `[agent]` → all non-agent commands still pass

---

## 5. FMP / fmp_cached Parity Matrix

Every new fetcher this PRD adds ships in **both** providers in the same commit. Two tier-1 (real caching), four tier-2 (passthrough). This section is the enforceable contract.

### 5.1 Parity matrix (at a glance)

| # | Endpoint | New fetcher class | fmp registration | fmp_cached tier | Cache key | Freshness rule | Rationale |
|---|---|---|---|---|---|---|---|
| 1 | `/stable/historical-chart/{interval}` | `EquityIntradayHistorical` | `equity_intraday_historical.py` | **Tier-1** (gap detection) | `symbol × interval × date` | Same-day: append-only, tail may extend; prior days: immutable | Highest-volume call — polled every 60s per symbol; caching saves 95%+ traffic on replays |
| 2 | `/stable/aftermarket-quote` | `AftermarketQuote` | `aftermarket_quote.py` | **Tier-1** (short-TTL) | `symbol` with 60s TTL | Ephemeral: max staleness 60s | Second-highest-volume — polled during pre-market and after-hours; 60s TTL delivers ~12x cache hit rate |
| 3 | `/stable/aftermarket-trade` | `AftermarketTrade` | `aftermarket_trade.py` | Tier-2 (passthrough) | — | — | Low volume; last-print only fetched on demand |
| 4 | `/stable/batch-quote-short` | `EquityQuoteBatchShort` | `equity_quote_batch_short.py` | Tier-2 (passthrough) | — | — | Deliberately uncached: this IS the "quick and cheap poll" — caching would defeat its purpose |
| 5 | `/stable/all-exchange-market-hours` | `ExchangeMarketHours` | `exchange_market_hours.py` | Tier-2 with **24h TTL** override | `date × exchange` | Daily-invalidated | Rarely changes; 24h TTL saves 1000+ redundant calls/day |
| 6 | `/stable/technical-indicators/{indicator}` | `TechnicalIndicatorIntraday` | `technical_indicator_intraday.py` | Tier-2 (passthrough) | — | — | Optional / rarely used (techtrade computes indicators client-side); no caching investment justified |

### 5.2 Tier-1 caching detail

**`EquityIntradayHistorical` — the big one:**

Table `equity_intraday_historical`:
```sql
CREATE TABLE equity_intraday_historical (
    symbol           VARCHAR(20)       NOT NULL,
    interval_type    VARCHAR(10)       NOT NULL,   -- '1min','5min','15min','30min','1hour','4hour'
    ts               DATETIME(0)       NOT NULL,   -- bar-start timestamp, tz-naive in exchange TZ
    open_price       DECIMAL(18,6),
    high_price       DECIMAL(18,6),
    low_price        DECIMAL(18,6),
    close_price      DECIMAL(18,6),
    volume           BIGINT,
    is_extended      BOOLEAN           DEFAULT FALSE,
    cached_at        DATETIME(0)       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_valid         BOOLEAN           DEFAULT TRUE,
    additional_fields JSON,
    PRIMARY KEY (symbol, interval_type, ts),
    INDEX idx_symbol_interval_ts (symbol, interval_type, ts DESC)
);
```

Gap detection mirrors `_analyze_cache_gaps` from `equity_historical.py`, adapted for intraday granularity. Excludes non-trading hours per `exchange_calendars`. `_detect_missing_ranges` returns ranges to fetch; cached ranges served instantly.

**Critical correctness rule:** the *most recent* bar may extend during the same session (a 5-min bar opened at 10:00 doesn't finalize until 10:05). The cache marks the tail bar `is_valid=FALSE` when served from same-session cache, forcing re-fetch on the next tick. Prior-session bars are immutable and never re-fetched.

**`AftermarketQuote` — short-TTL variant:**

Table `aftermarket_quote`:
```sql
CREATE TABLE aftermarket_quote (
    symbol           VARCHAR(20)       PRIMARY KEY,
    price            DECIMAL(18,6),
    bid              DECIMAL(18,6),
    ask              DECIMAL(18,6),
    bid_size         INTEGER,
    ask_size         INTEGER,
    volume           BIGINT,
    timestamp        DATETIME(0)       NOT NULL,
    cached_at        DATETIME(0)       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_valid         BOOLEAN           DEFAULT TRUE
);
```

TTL logic: cache HIT if `cached_at > now - 60s`; else MISS (fetch → UPSERT). No gap detection — single-row-per-symbol.

### 5.3 Tier-2 registration pattern (unchanged from existing)

The four tier-2 fetchers use the existing `create_fallback_fetcher_class()` wrapper from `fmp_cached/models/base_cached.py`:

```python
# fmp_cached/openbb_fmp_cached/__init__.py additions
from openbb_fmp_cached.models.base_cached import create_fallback_fetcher_class
from openbb_fmp.models.aftermarket_trade import FMPAftermarketTradeFetcher
from openbb_fmp.models.equity_quote_batch_short import FMPEquityQuoteBatchShortFetcher
from openbb_fmp.models.exchange_market_hours import FMPExchangeMarketHoursFetcher
from openbb_fmp.models.technical_indicator_intraday import FMPTechnicalIndicatorIntradayFetcher

_tier2_new_fetchers = {
    "AftermarketTrade": create_fallback_fetcher_class(FMPAftermarketTradeFetcher, "AftermarketTrade"),
    "EquityQuoteBatchShort": create_fallback_fetcher_class(FMPEquityQuoteBatchShortFetcher, "EquityQuoteBatchShort"),
    # ExchangeMarketHours uses the bespoke 24h TTL wrapper (§5.5)
    "TechnicalIndicatorIntraday": create_fallback_fetcher_class(FMPTechnicalIndicatorIntradayFetcher, "TechnicalIndicatorIntraday"),
}
```

Credential translation (`fmp_cached_api_key → fmp_api_key`) is handled by the wrapper; no new plumbing.

### 5.4 What NEVER goes in the extension code

Enforcement of the provider posture:

```python
# ANTI-PATTERN — CI grep test fails on this:
result = obb.equity.price.historical(symbol="AAPL", provider="fmp")  # ← BAD

# CORRECT:
result = obb.equity.price.historical(symbol="AAPL", provider="fmp_cached")  # ← GOOD
```

A CI grep test (`tests/ci/test_provider_purity.py`) walks `openbb_fmp_trading/` and asserts no string literal `"fmp"` appears in a `provider=` context. Only `"fmp_cached"` is allowed. Approved exceptions:
- `openbb_fmp_trading/core/parity_test.py` — the parity oracle *needs* to call both to compare
- `openbb_fmp_trading/tests/**` — tests may exercise both providers

### 5.5 The 24h-TTL wrapper for `ExchangeMarketHours`

The existing `create_fallback_fetcher_class` wrapper doesn't natively support TTLs beyond same-session. Add `create_ttl_wrapper_class(fetcher, name, ttl_seconds)` to `base_cached.py` — a ~30 LoC addition that serves this fetcher plus future 24h-cached endpoints (holidays, market status).

Alternatives considered and rejected:
- Repurpose Tier-1 with a single-column table — overkill for market hours (48 exchange × date combinations per year).
- Skip caching and accept ~1000 daily redundant calls — wastes bandwidth budget per P6.

### 5.6 The article-adjacent parity tech debt (deferred, §1.3 follow-up)

Current state:
- `openbb_fmp/models/equity_gainers.py` → `/api/v3/stock_market/gainers`
- `openbb_fmp/models/equity_losers.py` → `/api/v3/stock_market/losers`
- `openbb_fmp/models/equity_most_active.py` → `/api/v3/stock_market/actives`

FMP has migrated to `/stable/biggest-gainers`, `/stable/biggest-losers`, `/stable/most-actives`. Both paths work today; no deprecation date. This PRD **files a follow-up issue** but does not migrate in-flight — the fetchers work, and behavior-drift risk during active PRD development outweighs the URL-cleanup benefit.

### 5.7 Acceptance criteria for §5

- **AC-parity-1** — CI test: `set(fmp_provider.fetcher_dict.keys()) ⊂ set(fmp_cached_provider.fetcher_dict.keys())`
- **AC-parity-2** — CI grep test in §5.4 passes
- **AC-parity-3** — Tier-1 cache hit rate ≥ 95% on a replay (AC-3 from §2.3)
- **AC-parity-4** — Tier-2 fetchers demonstrably fall back to direct-fmp when MySQL cache is unavailable (integration test with cache stopped mid-test)
- **AC-parity-5** — All six new fetchers pass round-trip tests with fixtures captured from real FMP responses

---

## 6. Data Models

Pydantic v2 models. Grouped by responsibility. Every model round-trips through `OBBject`, JSON-serializable, importable by MCP tools. All inherit from `openbb_core.provider.abstract.data.Data`.

### 6.1 Reused from `openbb_techtrade.models` (unchanged)

| Type | Purpose | Notes |
|---|---|---|
| `Order` | Broker-ready order (entry / exit_stop / exit_target / exit_time / exit_signal) | Decimal quantity/prices; carries `intent` enum |
| `Fill` | Executed order fill with slippage + commission | Emitted by `PaperBroker.simulate()` |
| `TradePlan` | Per-symbol bundle: signal + rule + size + orders + fills + recommendation | Populated stage-by-stage through the pipeline |
| `Recommendation` | Deterministic per-symbol verdict with action, conviction, levels, reasoning | From techtrade #80 |
| `Position` | Open position: symbol, qty (signed), avg_price, current_price, unrealized_pnl | |
| `IndicatorPanel` | Named indicator readings per symbol | From techtrade #72 |
| `MoverSignal` | Directional score + per-indicator vote attribution | From techtrade #74 |

Introducing parallel definitions would fork the type ecosystem and break the substrate (G3).

### 6.2 New models introduced by this PRD

#### 6.2.1 Config / plan

```python
class DailyConfig(Data):
    """Top-level config loaded from ~/.openbb_platform/fmp_trading/today.yaml.
    Passed to obb.fmp_trading.run(); serves as the input to PreOpenAgentTurn."""

    date: date | None = None                    # None = today
    exchange: Literal["NASDAQ","NYSE","AMEX"] = "NASDAQ"
    starting_equity: Decimal                    # for position sizing
    default_preset: str = "intraday_momentum"

    # BandwidthMeter parameters
    bandwidth_tier: Literal["premium","ultimate"] = "premium"
    bandwidth_monthly_bytes: int = 50 * 1024**3   # 50 GB Premium default

    # Risk defaults (RiskConfig can override per-session)
    default_risk: RiskConfig

    # Agent
    agent_backend: Literal["claude","openai","none"] = "claude"
    agent_max_watchlist_size: int = 20
    agent_universe_hint: list[str] | None = None


class DailyPlan(Data):
    """The pre-open agent's committed plan for the day.
    Written to journal + committed to IntradaySession at 09:29 ET."""

    as_of: datetime                             # commit timestamp
    date: date
    watchlist: list[str]                        # 10-30 symbols
    preset: str                                 # techtrade preset name
    alerts: list[AlertSpec]
    session_risk: RiskConfig                    # gates for today
    thesis: str                                 # LLM's narrative "why today"
    agent_backend: str                          # provenance
    is_deterministic_fallback: bool = False     # True if agent turn failed
```

#### 6.2.2 Market snapshot (article-inspired)

```python
class MoverRow(Data):
    symbol: str
    type: Literal["gainer","loser","active"]
    name: str
    price: Decimal
    change: Decimal
    change_pct: float
    volume: int
    sector: str | None = None                   # populated when sector_rollup=True

class MarketSnapshot(Data):
    as_of: datetime
    movers: list[MoverRow]                      # unified: gainers + losers + actives
    sentiment_ratio: float                      # gainer_count / max(loser_count, 1)
    top_gainer: MoverRow | None
    top_loser: MoverRow | None
    sector_breakdown: dict[str, int] | None = None
    volatile_movers: list[MoverRow] | None = None   # only if threshold set
```

#### 6.2.3 Intraday market data (per-fetcher models)

```python
class IntradayBar(Data):
    symbol: str
    interval: Literal["1min","5min","15min","30min","1hour","4hour"]
    ts: datetime                                # bar-start; tz-aware
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    is_extended: bool = False                   # extended-hours bar

class Quote(Data):
    symbol: str
    price: Decimal
    change: Decimal
    change_pct: float
    volume: int
    timestamp: datetime
    # short=False adds: bid, ask, bid_size, ask_size, day_high, day_low, prev_close,
    #                   year_high, year_low, market_cap, avg_volume, pe_ratio, eps,
    #                   shares_outstanding, price_avg_50, price_avg_200
    bid: Decimal | None = None
    ask: Decimal | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    # ... (~15 additional fields when short=False)

class AftermarketQuote(Data):
    symbol: str
    price: Decimal
    bid: Decimal
    ask: Decimal
    bid_size: int
    ask_size: int
    volume: int
    timestamp: datetime

class AftermarketTrade(Data):
    symbol: str
    price: Decimal
    size: int
    timestamp: datetime

class SessionStatus(Data):
    exchange: str
    is_market_open: bool
    is_pre_market: bool
    is_after_market: bool
    is_early_close_day: bool
    next_open: datetime
    next_close: datetime

class IndicatorValue(Data):
    symbol: str
    indicator: str
    ts: datetime
    value: float | None                         # None on lookback-warmup bars
    period_length: int
    timeframe: str
```

#### 6.2.4 Alerts

```python
# --- AlertSpec union types ---

class PriceThresholdSpec(Data):
    kind: Literal["price_threshold"] = "price_threshold"
    symbol: str
    crosses: Literal["up","down"]
    price: Decimal

class PercentChangeSpec(Data):
    kind: Literal["percent_change"] = "percent_change"
    symbol: str
    threshold_pct: float                        # e.g. 5.0 = trigger on ±5%
    window: Literal["session","1h","5m"]

class VolumeSpikeSpec(Data):
    kind: Literal["volume_spike"] = "volume_spike"
    symbol: str
    ratio_vs_avg: float                         # e.g. 3.0 = 3x average volume
    avg_window: int = 20                        # bars used for avg calc

AlertSpec = Annotated[
    PriceThresholdSpec | PercentChangeSpec | VolumeSpikeSpec,
    Field(discriminator="kind")
]

# --- Runtime alert + event ---

class Alert(Data):
    id: str                                     # UUID
    spec: AlertSpec
    created_at: datetime
    is_active: bool = True
    fired_count: int = 0
    session_id: str | None = None               # scoped to session

class AlertEvent(Data):
    alert_id: str
    ts: datetime
    symbol: str
    condition: str                              # human-readable ("price > 180")
    context: dict[str, Any]                     # tick data at fire time
```

#### 6.2.5 Session state / observability

```python
class TickData(Data):
    """One tick of live market state. Feeds AlertManager.evaluate() and RiskManager gates."""
    ts: datetime
    quotes: dict[str, Quote]                    # keyed by symbol
    bars_recent: dict[str, list[IntradayBar]]   # last N bars per symbol
    session_status: SessionStatus

class PnLSnapshot(Data):
    ts: datetime
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    day_pnl: Decimal                            # realized + unrealized since session open
    day_dd_pct: float                           # negative on drawdown
    positions_open: int
    positions_closed: int
    win_rate_today: float | None                # None if no closed positions yet

class BandwidthState(Data):
    month_used_bytes: int
    month_budget_bytes: int
    month_used_pct: float
    mode: Literal["normal","conservation","halted"]
    session_used_bytes: int

class RiskState(Data):
    ts: datetime
    gates_active: list[str]                     # ["max_position_size","day_dd_pct",...]
    gates_tripped_today: list[str]              # gates that fired at least once
    cooldowns: dict[str, datetime]              # symbol → cooldown expiry
    flat_by_close_window_open: bool             # True after 15:50 ET
    day_dd_pct: float
    open_position_count: int
    max_open_positions: int

class JournalEvent(Data):
    ts: datetime
    session_id: str
    event_type: Literal[
        "session_start", "session_end",
        "tick", "signal", "plan", "order", "fill",
        "veto", "alert", "risk_state_change",
        "mode_change", "agent_turn_start", "agent_turn_end",
    ]
    payload: dict[str, Any]                     # event-specific
```

#### 6.2.6 Results / reports

```python
class SessionResult(Data):
    session_id: str
    date: date
    exchange: str
    started_at: datetime
    ended_at: datetime
    exit_code: int
    daily_plan: DailyPlan
    final_pnl: PnLSnapshot
    final_bandwidth: BandwidthState
    total_ticks: int
    total_signals: int
    total_orders: int
    total_fills: int
    total_vetoes: int
    total_alerts_fired: int
    flat_at_close: bool
    journal_path: Path

class HealthReport(Data):
    ts: datetime
    fmp_credentials_ok: bool
    mysql_cache_ok: bool
    exchange_calendars_ok: bool
    techtrade_version: str
    techtrade_ok: bool
    agent_extra_installed: bool
    xlsxwriter_extra_installed: bool
    validation_extra_installed: bool
    bandwidth_remaining_pct: float
    warnings: list[str]
    errors: list[str]

class ReportManifest(Data):
    session_id: str
    md_path: Path | None
    xlsx_path: Path | None
    json_path: Path | None
    included_agent_narrative: bool
```

### 6.3 Field convention summary

- **Money & quantities:** `Decimal` (no float drift; P2)
- **Timestamps:** tz-aware `datetime` (UTC internally; converted to exchange TZ for display)
- **Enums:** `Literal[...]` (renders cleanly in OpenAPI + Pydantic v2 validates)
- **Optional data:** `T | None = None` (PEP 604 style, not `Optional[T]`)
- **Discriminated unions:** `Annotated[U1 | U2 | U3, Field(discriminator="kind")]` — the AlertSpec pattern
- **Provider round-trip:** every model has stable JSON serialization tested via `Data(...).model_dump_json()` → `Data.model_validate_json(...)` in unit tests

### 6.4 Where these models live

```
openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models/
├── __init__.py           # re-exports all public models
├── config.py             # DailyConfig, RiskConfig
├── plan.py               # DailyPlan
├── snapshot.py           # MoverRow, MarketSnapshot
├── market_data.py        # IntradayBar, Quote, AftermarketQuote, AftermarketTrade,
│                         #   SessionStatus, IndicatorValue
├── alert.py              # AlertSpec union, Alert, AlertEvent
├── session_state.py      # TickData, PnLSnapshot, BandwidthState, RiskState, JournalEvent
└── results.py            # SessionResult, HealthReport, ReportManifest
```

Provider fetcher classes (`EquityIntradayHistoricalFetcher`, etc.) live under `openbb_fmp/models/` and `openbb_fmp_cached/models/` — not in this extension. This extension consumes them via `obb.fmp_trading.bars_intraday(...)` which dispatches to `fmp_cached`.

---

## 7. Agent Turns Specification

Two one-shot agent turns per day. Both use forced tool-calling so the LLM must produce structured output matching the domain schema before it can exit. No looping mid-day.

### 7.1 PreOpenAgentTurn — spec

**Fires:** 07:30 ET (or `--pre-open-time` override), one-shot, ~5-min budget.
**Input:** yesterday's `SessionResult` (if exists), `DailyConfig`, current pre-market market state.
**Output:** `DailyPlan` (via forced tool call `submit_daily_plan`).
**Fallback on failure:** deterministic `DailyPlan` = (yesterday's watchlist filtered to still-active symbols) ∪ (techtrade.scan top-15) + preset=`intraday_momentum`.

#### System prompt (fixed template)

```
You are the pre-open discovery agent for an intraday day-trading automation
system. Your task is to produce a DailyPlan for today's US trading session
(exchange: {{exchange}}) that will be committed to a deterministic execution
loop at 09:29 ET.

You have {{time_budget_min}} minutes and {{tool_call_budget}} tool calls to
gather context and produce your plan.

# Hard constraints — enforced by RiskManager, will veto violations
- Watchlist size: {{min_watchlist}}–{{max_watchlist}} symbols
- Symbols must be listed on {{exchange}} and actively trading (no OTC, no PN)
- Preset must be one of: {{available_presets}}
- Total notional exposure cannot exceed {{max_notional}}
- Session risk budget: {{day_dd_pct}}% max drawdown

# Your process (do these in order)
1. Read yesterday's SessionResult if available (get_yesterday_result)
2. Gather pre-market context using the tools below
3. Build your watchlist reasoning symbol by symbol
4. Select preset + define session risk config + define alerts
5. Call submit_daily_plan(...) exactly once

# You MUST call submit_daily_plan before this turn ends. If you skip it, the
# system falls back to a deterministic default and your reasoning is discarded.

# You CANNOT submit orders, modify positions, or change RiskManager gates.
# Those all happen after 09:29 ET in the deterministic execution loop.
```

#### Tool set (read-only + one submit tool)

| Tool | Purpose | Underlying |
|---|---|---|
| `get_yesterday_result()` | Yesterday's SessionResult | Reads `~/.openbb_platform/fmp_trading/sessions/` |
| `market_snapshot(top_n, volatility_threshold_pct, sector_rollup)` | Gainers/losers/actives + sentiment | `obb.fmp_trading.market_snapshot` |
| `get_news(symbols, since_hours=16)` | Overnight news per symbol | `obb.news.company_news` |
| `get_8k_filings(since_hours=16)` | Overnight material-event filings | `obb.regulators.sec.filings(form_type="8-K")` |
| `get_earnings_today(when="BMO"|"AMC")` | Companies reporting today | `obb.equity.calendar.earnings` |
| `get_insider_trades(days=3)` | Recent insider transactions | `obb.equity.ownership.insider_trading` |
| `get_congressional_trades(days=7)` | Recent Senate/House disclosures | `obb.equity.ownership.government_trades` |
| `get_techtrade_movers(top_n=20)` | Techtrade's segment-aware mover ranker | `obb.techtrade.movers` |
| `get_sector_performance()` | Sector snapshot | `obb.equity.discovery.sector_performance` |
| `get_market_hours()` | Today's session hours (regular/early-close/holiday) | `obb.fmp_trading.session_status` |
| **`submit_daily_plan(plan: DailyPlan)`** | **Required terminal tool** — commits the plan | Validates DailyPlan against schema + RiskManager pre-flight |

#### Expected output (forced schema)

`submit_daily_plan()` takes a `DailyPlan` matching §6.2.1. On call:
1. Pydantic validation runs
2. RiskManager pre-flight validates against constraints (min/max watchlist size, valid preset, notional caps)
3. If valid: written to journal, committed to session, turn ends
4. If invalid: agent gets one retry with the validation error; second failure = deterministic fallback

#### Failure fallback

```python
def deterministic_daily_plan_fallback(config: DailyConfig) -> DailyPlan:
    yesterday_result = load_yesterday_result_or_none()
    if yesterday_result:
        base = [s for s in yesterday_result.daily_plan.watchlist if is_actively_trading(s)]
    else:
        base = []

    techtrade_movers = obb.techtrade.movers(top_n=15, metric="pct_change").results
    watchlist = list(dict.fromkeys(base + [m.symbol for m in techtrade_movers]))[:20]

    return DailyPlan(
        as_of=now_utc(),
        date=today(),
        watchlist=watchlist,
        preset=config.default_preset,
        alerts=[],
        session_risk=config.default_risk,
        thesis="Deterministic fallback — pre-open agent turn failed or unavailable.",
        agent_backend="none",
        is_deterministic_fallback=True,
    )
```

### 7.2 PostCloseAgentTurn — spec

**Fires:** 16:15 ET, one-shot, ~3-min budget.
**Input:** today's completed `SessionResult` + full journal (`list[JournalEvent]`).
**Output:** three artifacts written to disk (via forced tool calls):
1. `end_of_day.md` — narrative day summary
2. `preset_review` — structured critique of which votes worked
3. `next_day_hints` — symbols worth watching tomorrow with rationale
**Fallback:** deterministic template (techtrade's `Recommendation`-narrator pattern applied to today's fills).

#### System prompt

```
You are the post-close review agent for an intraday day-trading system.
Today's session has closed. Your task is to produce three artifacts:
(1) a narrative day summary, (2) a structured preset review, (3) hints
for tomorrow's session.

You have {{time_budget_min}} minutes and {{tool_call_budget}} tool calls.

# Your process
1. Read today's session journal (get_journal)
2. Analyze which trades worked, which didn't, and why
3. Attribute performance to preset votes (which indicators fired correctly?)
4. Identify symbols worth watching tomorrow based on today's setups that
   didn't trigger but developed shape (e.g., wedge formation, volume
   pattern change, unusual pre-close move)
5. Call submit_end_of_day_md(md=...) exactly once
6. Call submit_preset_review(review=...) exactly once
7. Call submit_next_day_hints(hints=...) exactly once

# You cannot modify positions, orders, or session state — the session is
# over. Your output feeds tomorrow's PreOpenAgentTurn as context.

# Constraints on next_day_hints
- Max 10 hints
- Each hint must reference a specific journal event ID as justification
- Hints are advisory only; tomorrow's PreOpenAgentTurn decides whether to use them
```

#### Tool set

| Tool | Purpose | Underlying |
|---|---|---|
| `get_journal(session_id, event_types=None)` | Today's journal events | Reads NDJSON journal |
| `get_final_pnl(session_id)` | End-of-day PnLSnapshot | From SessionResult |
| `get_trade_details(order_id)` | Deep-dive on a specific trade | Joins order + fill + signal + veto events |
| `get_missed_signals(session_id)` | Signals that fired but got RiskManager-vetoed | Journal query |
| **`submit_end_of_day_md(md: str)`** | Writes markdown narrative | Persists to `Analysis/exports/daytrade_<date>/end_of_day.md` |
| **`submit_preset_review(review: PresetReview)`** | Structured critique | Persists to preset_review.json |
| **`submit_next_day_hints(hints: list[NextDayHint])`** | Advisory hints | Persists to next_day_hints.json — auto-read by tomorrow's PreOpen agent |

Where `PresetReview` and `NextDayHint` are new models (add to §6.2):

```python
class PresetReview(Data):
    preset_used: str
    trades_taken: int
    trades_won: int
    vote_family_performance: dict[str, float]   # "trend" → 0.62, "momentum" → 0.45
    weight_suggestions: dict[str, float] | None  # advisory tilt for tomorrow
    notes: str

class NextDayHint(Data):
    symbol: str
    reason: str                                  # 1-sentence rationale
    journal_evidence: list[str]                  # event IDs supporting the hint
    suggested_alert: AlertSpec | None
```

#### Failure fallback

If the LLM turn fails, run techtrade's deterministic `RecommendationNarrator` (from #80) across today's fills, produce a plain-template `end_of_day.md`, empty `preset_review` (no weight suggestions), and empty `next_day_hints`. The session still ends cleanly; tomorrow's PreOpen agent gets no LLM-derived hints but has yesterday's raw SessionResult to reason over directly.

### 7.3 The MCP exposure (fulfills #85)

When `[agent]` extra is installed, everything above is exposed as MCP tools via a new `mcp_tools.py` module. External LLM clients (Claude Desktop, VS Code MCP, custom) can then:

- Query today's session state read-only via the §4.5 `session.*` commands
- Retroactively examine yesterday's SessionResult
- Generate their own DailyPlan variants using the pre-open tool set (though only the built-in `PreOpenAgentTurn` can actually *commit* one)
- Trigger a `report()` regeneration with a different narrative style

**Critical safety constraint:** the MCP tool surface **does not include** `submit_daily_plan()`, `submit_end_of_day_md()`, or any tool that mutates session state. Those are internal to the built-in agent turns. External MCP clients are read-only. This is what makes the #85 "core-unchanged-when-removed" test meaningful — removing the extra removes both the built-in agent turns AND the MCP server, but neither is on the critical path.

### 7.4 Agent-backend abstraction

The `agent_backend: Literal["claude","openai","none"]` field in `DailyConfig` maps to a small adapter layer:

```
openbb_fmp_trading/agent/
├── __init__.py
├── base.py              # AgentBackend Protocol
├── claude_backend.py    # anthropic SDK impl
├── openai_backend.py    # openai SDK impl
├── deterministic.py     # fallback impls of both turns
├── pre_open_turn.py     # PreOpenAgentTurn orchestration (backend-agnostic)
├── post_close_turn.py   # PostCloseAgentTurn orchestration
└── mcp_tools.py         # MCP server for external clients
```

The `AgentBackend` Protocol has three methods: `run_pre_open(config, tools) -> DailyPlan`, `run_post_close(session_result, tools) -> tuple[str, PresetReview, list[NextDayHint]]`, and `close()`. Swapping Claude for OpenAI (or a future local-model backend) is a single-file addition — same pattern as `BrokerInterface` for brokers.

### 7.5 Cost estimate

Rough per-day agent cost with Claude Sonnet at current pricing:
- Pre-open turn: ~50k input + ~2k output tokens ≈ $0.16
- Post-close turn: ~30k input + ~4k output tokens ≈ $0.12
- **~$0.28 / trading day, ~$70 / year** — negligible next to the FMP Premium subscription ($49/mo = $588/yr)

Bounded and predictable because both turns are one-shot with hard time/tool-call budgets. This is the specific reason Approach C was chosen — an intraday LLM-in-the-loop would burn ~10x this per day.

---

## 8. Risk Manager & Session State

The correctness gate that makes the deterministic execution guarantee real. Every proposed trade funnels through this layer; no path bypasses it.

### 8.1 RiskManager — the trade-admission contract

```python
class RiskManager:
    def propose_trade(self, plan: TradePlan, tick: TickData) -> TradeDecision:
        """
        Returns TradeDecision.APPROVED or TradeDecision.REJECTED(reason).
        Called exactly once per proposed order by IntradaySession — never
        bypassed by CLI, agent, or direct plan() call. Enforced by architecture
        (see §8.6).
        """

class TradeDecision(Data):
    verdict: Literal["APPROVED","REJECTED"]
    reason: str | None                          # populated when REJECTED
    reason_code: str | None                     # machine-readable enum
    gate: str | None                            # which gate tripped
    plan: TradePlan                             # echoed back for journal
```

### 8.2 The eight gates (v1)

Order matters — first REJECT wins, short-circuits the remainder. All configurable via `RiskConfig` in `DailyConfig`.

| # | Gate | Rejection reason | Config knob |
|---|---|---|---|
| **G1** | `flat_by_close` | `"in flat-by-close window; no new opens after 15:50 ET"` | `flat_by_close_time_et` (default `"15:50"`) |
| **G2** | `max_open_positions` | `"already at max_open_positions={N}"` | `max_open_positions` (default `5`) |
| **G3** | `day_dd_pct_breach` | `"day drawdown {X}% exceeds day_dd_pct={Y}%"` | `day_dd_pct` (default `-2.0`) |
| **G4** | `per_symbol_cooldown` | `"symbol {S} in {N}min cooldown after {reason}"` | `cooldown_after_stopout_min` (default `30`) |
| **G5** | `sector_cap` | `"sector {S} at cap {N}/{M} positions"` | `max_positions_per_sector` (default `2`) |
| **G6** | `max_position_size` | `"position size {N} exceeds max_position_size={M}"` | `max_position_size_pct_equity` (default `10.0`) |
| **G7** | `total_notional_cap` | `"total notional {N} exceeds max_notional={M}"` | `max_notional_pct_equity` (default `30.0`) |
| **G8** | `duplicate_position` | `"already long {S}; blocking additional long"` | *(not configurable; hard rule)* |

Deliberately simple. No exotic quant risk metrics (VaR, expected shortfall, correlation limits) in v1 — those are v2 territory. Every gate is testable with fixture data.

### 8.3 Cooldown state machine

When a position stops out, the symbol enters cooldown to prevent revenge-trading:

```
Position OPEN
    │
    ├─ stop hit ────────► Position CLOSED (loss)
    │                       │
    │                       ▼
    │                     Symbol enters COOLDOWN(30 min)
    │                       │
    │                       ├─ any new plan on this symbol → REJECTED(G4)
    │                       │
    │                       ▼ (after 30 min)
    │                     Symbol EXITS cooldown; new plans allowed
    │
    ├─ target hit ─────► Position CLOSED (win) — no cooldown
    │
    └─ time stop hit ──► Position CLOSED (breakeven-ish) — no cooldown
```

Cooldowns are per-symbol and reset at session start. Configurable via `cooldown_after_stopout_min` (default 30 min).

### 8.4 Day-drawdown model

```python
day_pnl = realized_pnl_today + unrealized_pnl_current
day_dd_pct = min(0, day_pnl / starting_equity * 100)   # negative or zero
```

When `day_dd_pct < RiskConfig.day_dd_pct` (e.g. -2.0%):
- **G3 rejects all new opens** — session enters "protective mode"
- **Existing positions are NOT force-closed** — they still respect their own stops
- **AlertManager fires a `day_dd_breach` alert** — visible to post-close agent turn
- **Session continues** — the risk cap is on new opens, not existing exposure

Rationale: force-closing on drawdown breach would guarantee realizing losses at a bad moment; letting stops work naturally is less catastrophic. The gate simply prevents *deepening* the hole.

### 8.5 Flat-by-close state machine

The single-most-important intraday risk rule (P4).

```
Session start (09:30 ET)
    │
    ▼
Normal state (09:30 – 15:49 ET)
    │  RiskManager gates active; new trades allowed
    │
    ▼ (at 15:50 ET)
Flat-by-close window opens
    │  G1 rejects ALL new opens
    │  Existing positions get MARKET SELL orders queued
    │  Journal: risk_state_change event
    │
    ▼ (at 15:55 ET)
Force-close window
    │  Any remaining positions get FILL-OR-KILL market orders
    │  These fill at 15:56 or 15:57 ET open (next-bar-open discipline)
    │
    ▼ (at 16:00 ET)
Session closes
    │  If flat_at_close=False → journal warning + exit code 5
    │  Post-close agent turn fires anyway (16:15 ET)
```

Overriding requires `--allow-overnight` flag + `overnight_reason` in DailyConfig. Overrides are per-symbol, not per-session — you cannot blanket-override.

### 8.6 Enforcement — why RiskManager can't be bypassed

The architectural invariant P7: every path to a `BrokerInterface.submit()` goes through `RiskManager.propose_trade()`.

Enforcement:
- **`IntradaySession._process_signal()` is the ONLY caller of `PaperBroker.submit()`** — a code-level chokepoint
- **`_process_signal()` calls `RiskManager.propose_trade()` on every plan** — no branches skip it
- **CI test `tests/architecture/test_broker_chokepoint.py`** greps for any `broker.submit(` outside `IntradaySession._process_signal()` and fails the build
- **The agent turns don't have access to `PaperBroker` at all** — the tool set (§7.1, §7.2) contains no `submit_order()` tool

### 8.7 Session state — what lives where

| State | Owner | Lifetime | Persistence |
|---|---|---|---|
| `RiskConfig` (gate thresholds) | `RiskManager.config` | Session (immutable after commit) | Written to journal at session_start |
| `RiskState` (gates tripped, cooldowns, day_dd) | `RiskManager.state` | Session (mutable during) | Snapshotted to journal on every change |
| `Positions` (open) | `PaperBroker.positions_open` | Session (mutable) | Journal per open/close event |
| `Orders` (submitted, pending, filled) | `PaperBroker.orders_history` | Session (append-only) | Journal per state change |
| `PnLSnapshot` (running) | derived from Positions + Fills | Session | Rehydrated from journal on replay |
| `BandwidthState` | `BandwidthMeter` | **Month** (persists across sessions) | `~/.openbb_platform/fmp_trading/bandwidth.json`, atomic writes |
| `AlertManager.alerts` | `AlertManager._active_alerts` | Session (mutable) | Journal per create/delete/fire |
| `DailyPlan` | `IntradaySession.plan` | Session (immutable after commit) | Journal at commit + `sessions/<date>.json` archive |

Everything except `BandwidthState` is session-scoped and reconstructible from the journal — that's what makes `obb.fmp_trading.replay()` work.

### 8.8 Acceptance criteria for §8

- **AC-risk-1** — `RiskManager.propose_trade()` rejects with correct `reason_code` for every gate violation. One test per gate (8 tests).
- **AC-risk-2** — CI test: `broker.submit(` string appears only inside `IntradaySession._process_signal()` (chokepoint enforcement).
- **AC-risk-3** — Flat-by-close: submitting an order at 15:51 → `REJECTED(G1)`. Test AC-6 from §2.3.
- **AC-risk-4** — Day-drawdown breach at 12:00 → G3 rejects new opens for the rest of the session, existing positions continue respecting their stops.
- **AC-risk-5** — Cooldown: symbol stopped out at 10:30 → any plan on that symbol at 10:45 rejected; at 11:01 approved.
- **AC-risk-6** — Sector cap: 3rd tech-sector position rejected when `max_positions_per_sector=2`, with correct sector attribution via `equity.profile.sector` (cached).
- **AC-risk-7** — Replay determinism: replaying the same journal twice produces byte-identical `RiskState` at every event boundary (extends AC-8 from §2.3).
- **AC-risk-8** — Agent turns cannot access `PaperBroker` — tool set inspection test asserts none of the pre-open or post-close tools returns or mutates a broker reference.

---

## 9. Non-Functional Requirements

| ID | Category | Requirement |
|---|---|---|
| **NFR-01** | Performance | REST API calls ≤ 200ms p95 on cache HIT; ≤ 800ms p95 on cache MISS+network |
| **NFR-02** | Performance | Full 6.5h session end-to-end runtime ≤ actual wall-clock (no drift beyond one tick period) |
| **NFR-03** | Reliability | Auto-retry on 429/5xx with exponential backoff + jitter, max 3 attempts, then skip tick and log |
| **NFR-04** | Reliability | Session survives MySQL cache down (falls back to direct fmp per fmp_cached tier-1 pattern) |
| **NFR-05** | Reliability | Session survives ≤3 consecutive tick failures (skip-and-continue); halts on 4th consecutive |
| **NFR-06** | Compatibility | Python 3.10-3.13 (matches parent techtrade + core platform) |
| **NFR-07** | Compatibility | `openbb-techtrade >= 0.1.0`, `openbb-backtest >= 0.1.0` (optional via `[validation]`) |
| **NFR-08** | Resource usage | Memory footprint ≤ 500 MB baseline, ≤ 1 GB with 100-symbol watchlist + agent extra |
| **NFR-09** | Observability | Structured logging via `logging`; NDJSON journal is source of truth |
| **NFR-10** | Observability | Every FMP call logged with endpoint + payload size (bandwidth accounting) |
| **NFR-11** | Security | No credentials in logs, journal, or session artifacts; FMP keys via `~/.openbb_platform/user_settings.json` + `keyring` |
| **NFR-12** | Security | Session journal `0640` permissions; contains positions and P&L, not credentials |
| **NFR-13** | Determinism | `SessionResult` reproducible from `(config, journal, market_data_fixtures)` byte-for-byte |
| **NFR-14** | Bandwidth | Conservation mode at 80% monthly budget; hard halt at 95% |
| **NFR-15** | Latency | Tick loop cadence ≤ 5s under normal conditions, ≤ 15s in conservation mode |
| **NFR-16** | Testability | ≥ 90% line coverage on `core/`, `engine/`, `agent/deterministic.py`; agent-backend impls tested via mock LLM |
| **NFR-17** | Maintainability | Every internal module ≤ 500 LoC; anything larger triggers a split-refactor issue |

---

## 10. Phased Delivery Roadmap

```
Phase 0 — Prerequisites (parallel, ~1 week)
├─ [P0.1] File 6 new fetchers in `openbb_fmp` (5.1 matrix, tier-2-safe versions first)
├─ [P0.2] Register 6 new fetchers in `openbb_fmp_cached` (all tier-2 initially)
├─ [P0.3] CI parity test `set(fmp) ⊂ set(fmp_cached)` — must be green
├─ [P0.4] CI provider-purity grep test — sets the guardrail before code lands
└─ [P0.5] Absorb #91 3-tier fallback code disposition (port to adapter or drop)

Phase 1 — Foundations (~2 weeks; Sprint 1)
├─ [P1.1] Extension scaffold: `openbb_platform/extensions/fmp_trading/`
├─ [P1.2] Core data models (§6) + Pydantic round-trip tests
├─ [P1.3] `RiskManager` with 8 gates (§8) + one test per gate
├─ [P1.4] `SessionJournal` NDJSON writer + reader/replay
├─ [P1.5] `BandwidthMeter` + monthly persistence + conservation-mode test
├─ [P1.6] `obb.fmp_trading.doctor()` command + `openbb-daytrade doctor` CLI

Phase 2 — Deterministic execution (~2 weeks; Sprint 2)
├─ [P2.1] Upgrade tier-2 fetchers #1 (intraday bars) + #2 (aftermarket quote) to TIER-1 with real caching (§5.2)
├─ [P2.2] Add `create_ttl_wrapper_class` to `base_cached.py`; migrate ExchangeMarketHours (§5.5)
├─ [P2.3] `IntradaySession` tick loop skeleton — no signals yet, just quote polling + journal writes
├─ [P2.4] Wire techtrade `signals → plan → orders → PaperBroker` chain into tick loop
├─ [P2.5] Flat-by-close state machine + AC-6 test
├─ [P2.6] No-look-ahead golden test (AC-5)
├─ [P2.7] End-to-end integration test with mock FMP → 6.5h simulated session (AC-1)

Phase 3 — Agent turns (~2 weeks; Sprint 3)
├─ [P3.1] `[agent]` Poetry extra + AgentBackend Protocol
├─ [P3.2] `claude_backend.py` (anthropic SDK) + `deterministic.py` fallback
├─ [P3.3] PreOpenAgentTurn — system prompt + tool set + forced submit_daily_plan
├─ [P3.4] PostCloseAgentTurn — system prompt + tool set + 3 submit tools
├─ [P3.5] MCP tool server (`openbb-daytrade mcp-serve`)
├─ [P3.6] "Core-unchanged-when-removed" test (fulfills #85 acceptance)
├─ [P3.7] Cost-cap tests — max tokens per turn

Phase 4 — AlertManager v1 + article-inspired features (~1 week; Sprint 4)
├─ [P4.1] `market_snapshot` command + MoverRow + MarketSnapshot models
├─ [P4.2] AlertManager v1 (3 spec types, session-log + agent-context delivery)
├─ [P4.3] `alert.*` sub-router + CLI subcommands
├─ [P4.4] Alert eval tests (each spec type × threshold-cross case)

Phase 5 — Reporting + polish (~1 week; Sprint 5)
├─ [P5.1] `obb.fmp_trading.report()` — MD + XLSX + JSON
├─ [P5.2] Excel export reuses techtrade `[xlsxwriter]` + adds intraday sheets
├─ [P5.3] `replay()` command — reruns from journal deterministically
├─ [P5.4] README + `openbb-daytrade` CLI docs + config examples

Phase 6 — Validation, docs, launch (~1 week; Sprint 6)
├─ [P6.1] Backtest bridge — validate techtrade preset over historical intraday
│         (optional via `[validation]` extra; blocked on #82's bridge already done)
├─ [P6.2] File all 4 target epics as CLOSABLE with reference to this PRD
├─ [P6.3] Post-v1 follow-up issues filed (AlertManager v2, FMP /stable/* migration, pattern alerts)
├─ [P6.4] Integration test suite green against live fmp_cached (AC-1 + AC-3 real-network)
├─ [P6.5] pyproject.toml final: entry-point + Poetry extras + version bumps

Total: ~9 weeks (6 sprints × ~1.5 weeks median), single developer.
Compressed to ~6 weeks with parallelism on P0, P1, and P3.
```

---

## 11. Testing Strategy

**Test tiers** (mirrors techtrade pattern):

| Tier | Path | What | When |
|---|---|---|---|
| **Unit** | `tests/unit/` | Every module offline; no FMP, no MySQL, no LLM | Every commit |
| **Golden** | `tests/golden/` | Content invariants: no-look-ahead, replay determinism, cache-hit reproducibility, Excel workbook structure | Every commit |
| **Architecture** | `tests/architecture/` | CI enforcement: parity, provider-purity, broker-chokepoint | Every commit |
| **Integration** | `tests/integration/` | Real fmp_cached, real MySQL, mock LLM | On PR + nightly |
| **Live** | `tests/live/` (marker `@pytest.mark.live`) | Real FMP, real LLM, real MySQL, real market hours (paper only) | Manual + weekly cron |
| **Replay** | `tests/replay/` | Deterministic replay of captured production sessions | Nightly |

**Key golden tests:**
1. **No-look-ahead**: signal off bar-t close → fill at bar-t+1 open (AC-5)
2. **Replay determinism**: same journal → same SessionResult byte-for-byte (AC-8, AC-risk-7)
3. **Cache determinism**: same fixture set → same cache state at end of session (AC-3)

**Fixtures** — captured NDJSON journals from real (paper) sessions serve as replay fixtures for regression testing. First few weeks post-launch, every real session's journal gets archived and a subset promoted to fixtures.

---

## 12. Risks & Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| **R1** | FMP intraday endpoint schema changes | Med | High | Fixture round-trip tests catch drift; version-pin FMP API base URL; docs URL check in `doctor()` |
| **R2** | FMP bandwidth cap surprises user mid-session | Med | Med | Conservation mode at 80%; `doctor()` reports remaining budget before session; email/log warnings |
| **R3** | MySQL cache corruption invalidates a day's data | Low | Med | `is_valid=FALSE` soft-delete allows re-fetch; cache rebuild command; MySQL replication optional |
| **R4** | LLM produces invalid DailyPlan repeatedly | Low | Low | 1-retry + deterministic fallback; failures logged; agent-backend swap possible |
| **R5** | LLM cost creep (long agent turns) | Low | Low | Hard token/tool-call budgets per turn; billing dashboard as add-on |
| **R6** | Contributor adds `provider="fmp"` bypassing cache | Med | High | CI grep test (§5.4) catches at PR time |
| **R7** | Contributor bypasses RiskManager | Low | Critical | Broker-chokepoint CI test (§8.6) catches |
| **R8** | Half-day / holiday not detected → runs past close | Low | High | `exchange_calendars` is canonical; test with fixture calendars |
| **R9** | Techtrade breaking change | Med | High | Techtrade version pinned in pyproject.toml; integration test in PR pipeline |
| **R10** | User runs with `--allow-overnight` and gets gapped | Med (user error) | Critical (user impact) | Explicit flag + reason; loud journal warning; disclaimer in end-of-day report |
| **R11** | Session state grows unbounded (memory leak) | Low | Med | Journal writes are streamed; in-memory position/order state bounded by max_open_positions × RiskConfig gates |
| **R12** | Two sessions run simultaneously on same account | Low | Med | Session lock file at `~/.openbb_platform/fmp_trading/session.lock`; doctor() checks |
| **R13** | Time-of-day-dependent bug (DST transitions, holiday early-close) | Med | Med | Frozen-clock tests for DST spring/fall + 3 known early-close dates + Christmas Eve |

---

## 13. Open Questions

Real decisions still needed. Recommend resolving before Phase 1 starts.

**Q1 — AftermarketQuote TTL configurable per-user?**
Current design: hard-coded 60s TTL. Alternative: `preferences.fmp_cached_aftermarket_ttl_seconds`. Small dev cost, non-trivial safety implication (too-long TTL delivers stale prices to a live position).
*Working lean:* Make it configurable but log a warning if set above 300s.

**Q2 — Should PostCloseAgentTurn suggestions auto-apply to tomorrow's DailyPlan?**
Current design: no. Suggestions are advisory; tomorrow's PreOpen agent must actively re-read them. Alternative: `next_day_hints.auto_apply=True` config flag.
*Working lean:* Manual read only in v1; add auto-apply as v2 option if user demand.

**Q3 — Multi-account support?**
Current design: single session, single FMP account, single MySQL cache. A power-user might run paper alongside a future live account.
*Working lean:* Defer to v2; if user has real need, file follow-up issue.

**Q4 — Half-day early-close: 13:00 or 12:55 flat-by-close?**
Half-days close 13:00 ET. Flat-by-close is normally close - 5 min. Should this scale (close - 5 min = 12:55) or stay at the fixed 15:50?
*Working lean:* Scale to `close - 5 min` via `exchange_calendars` — natural extension of the rule.

**Q5 — What preset is `intraday_momentum`? Does techtrade `trend_follow` at 5-min bars suffice?**
Techtrade ships 3 presets (`trend_follow`, `mean_revert`, `breakout`) all daily-oriented. At 5-min bars, some parameters may need re-tuning.
*Working lean:* File techtrade issue to add 5-min-tuned variants of the 3 presets. Deterministic default uses `trend_follow` at 5-min in the meantime.

**Q6 — Should the agent turns receive `next_day_hints` from `[N-1]` days ago as well, or just yesterday?**
More history = better pattern recognition but bigger prompt.
*Working lean:* Last 5 trading days' hints. Tokens are cheap.

**Q7 — CBOE integration for options context — required for v1 or deferred?**
FMP has no options. Analysis Phase-D2 (#279/#280/#281) proposes adding cboe.
*Working lean:* Defer. Day-trading momentum on equities doesn't require options context.

**Q8 — Should `--dry-run` also skip the agent turns?**
Current design: `dry_run=True` skips PaperBroker fills but agent turns still run (with tool responses stubbed).
*Working lean:* Add `--no-agent` as a separate flag. `--dry-run` skips fills only.

---

## Appendix A — FMP Endpoint Inventory

Snapshot of the FMP developer-docs surface relevant to day trading, gathered during research phase. Full details in the research agent's report (in-conversation only; not persisted).

### Priority-1 — Day-trading critical
- **Quotes**: `/stable/quote`, `/stable/quote-short`, `/stable/batch-quote`, `/stable/batch-quote-short`, `/stable/batch-exchange-quote`, `/stable/aftermarket-quote`, `/stable/aftermarket-trade`, `/stable/batch-aftermarket-trade`
- **Intraday bars**: `/stable/historical-chart/{1min,5min,15min,30min,1hour,4hour}` — unified across stocks, indices, crypto, forex
- **Movers**: `/stable/biggest-gainers`, `/stable/biggest-losers`, `/stable/most-actives`, `/stable/sector-performance-snapshot`
- **Session state**: `/stable/all-exchange-market-hours`, `/stable/exchange-market-hours`, `/stable/holidays-by-exchange`

### Priority-2 — Signals & context
- **News**: `/stable/news/{general-latest,stock,crypto,forex,press-releases}`
- **Calendars**: `/stable/earnings-calendar`, `/stable/dividends-calendar`, `/stable/splits-calendar`, `/stable/ipos-calendar`, `/stable/economic-calendar`
- **Insider / political**: `/stable/insider-trading/latest`, `/stable/senate-latest`, `/stable/senate-trades`, `/stable/house-latest`, `/stable/house-trades`
- **SEC**: `/stable/sec-filings-financials`, `/stable/sec-filings-8k`, `/stable/sec-filings-search/form-type`
- **Analyst ratings**: `/stable/grades-consensus`, `/stable/grades-historical`, `/stable/price-target-summary`, `/stable/upgrades-downgrades-consensus-bulk`
- **Technical indicators**: `/stable/technical-indicators/{ADX,RSI,EMA,SMA,WMA,DEMA,TEMA,WilliamsR,StandardDeviation}` at 1min-1day timeframes

### Priority-4 — Tier / rate / bandwidth
- **Premium ($49/mo)** is the entry-point tier — Starter lacks intraday bars and technicals. Ultimate ($99/mo) only needed for >750 req/min, bulk endpoints, or extra 100 GB bandwidth.
- **Bandwidth cap is the sneaky constraint**: Premium = 50 GB/month. Naive `batch-exchange-quote` on NASDAQ every 3s = ~30-60 GB/day, blows the cap in one session. Design uses `batch-quote-short` on a curated watchlist per P6.

### Hard gaps (require second provider or client-side computation)
1. **Options chains, greeks, IV** — nothing exists. Pair with cboe (Analysis Phase-D2) or Polygon/Tradier/ORATS.
2. **WebSocket streaming** — undocumented in current stable surface. Assume polling.
3. **Level 2 / order book / time-and-sales** — absent.
4. **MACD, Bollinger Bands, Stochastic, VWAP-as-indicator** — compute client-side from bars.
5. **Short interest / borrow rates** — not surfaced.
6. **News sentiment scoring** — only raw articles.

---

## Appendix B — Glossary

| Term | Definition |
|---|---|
| **OBBject** | OpenBB's standard return envelope wrapping data, metadata, and chart objects |
| **DailyPlan** | Pre-open agent turn's output: watchlist + preset + alerts + session risk config + thesis narrative |
| **IntradaySession** | The market-hours state machine that owns tick loop, positions, and journal |
| **RiskManager** | Single source of truth on trade admission — every proposed trade funnels through `propose_trade()` |
| **BrokerInterface** | Protocol (from techtrade #78) that PaperBroker implements today; live brokers implement in future |
| **PaperBroker** | Simulated fills at next-bar-open with slippage + commission; the only broker in v1 |
| **TradePlan** | Per-symbol bundle: signal + rule + size + orders + fills + recommendation (from techtrade #77) |
| **Recommendation** | Deterministic per-symbol verdict with action, conviction, levels, and reasoning (from techtrade #80) |
| **Conservation mode** | Bandwidth-triggered state where session uses short-quote endpoints and longer polling intervals |
| **fmp_cached** | MySQL-backed persistence wrapper around openbb_fmp; tier-1 dedicated caching + tier-2 passthrough |
| **Flat-by-close** | Risk rule that closes all positions by 15:55 ET; the single most important intraday risk control |
| **Techtrade** | `openbb-techtrade` — the daily/EOD sibling extension this one composes on |

---

*Document complete. Ready for user review before implementation planning.*
