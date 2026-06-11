# PRD & Functional Spec: Technical-Indicator Trading Engine (`openbb-techtrade`)

**Status:** Draft / Proposal — for review
**Author:** Quant working group
**Target component:** OpenBB Platform first-party extension (`openbb-techtrade`) + `pandas-ta-classic` submodule + `fmp_cached` data
**Companion documents:**
- [`docs/Specs/Backtesting-Engine-PRD.md`](./Backtesting-Engine-PRD.md) (the `openbb-backtest` engine this tool delegates validation to)
- [`docs/Specs/Quant-Analysis-Module-Proposal.md`](./Quant-Analysis-Module-Proposal.md) (broader `openbb-quant` strategy surface)
- [`docs/Tools/Quant-Strategies-Guide.md`](../Tools/Quant-Strategies-Guide.md) (453-repo survey — §5 Technical Indicators is the source for this PRD)

> **Cross-repo note.** The companion PRDs and the `quant_repos/` reference collection
> live in the sibling **`OpenBB`** checkout, while this engine is specified for the
> **`OpenBBTechnical`** checkout. Repo paths below that begin `quant_repos/…` refer to the
> `OpenBB` checkout and are **reference-only**; the `pandas-ta-classic` submodule is
> vendored into *this* tree. See **Q1 / §19** for the consolidation decision.

**Date:** 2026-06-09
**Decision posture:** Optimize for a **deterministic, reproducible signal core first**;
the LLM/agent layer is an optional shell that *narrates and orchestrates* but never
becomes the source of truth. "Best-in-class" here means transparent, tunable,
overfitting-aware signal generation — not opacity.
**Licensing posture:** The fork is **AGPL-3.0** (inherited from OpenBB) and
**non-commercial**. Every dependency in this design is permissive (MIT / BSD / Apache-2.0)
and therefore AGPL-compatible with no Commons-Clause exposure. The primary indicator
engine, **`pandas-ta-classic`** ([`prajoria/pandas-ta-classic`](https://github.com/prajoria/pandas-ta-classic),
MIT), is a **first-party fork** consumed as a **git submodule**, so feature work can land
on its source branch and flow straight into this engine.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement & Motivation](#2-problem-statement--motivation)
3. [Goals & Non-Goals](#3-goals--non-goals)
4. [Guiding Principles](#4-guiding-principles)
5. [Comparative Analysis of Technical-Indicator & Signal Sources](#5-comparative-analysis-of-technical-indicator--signal-sources)
6. [Licensing Analysis](#6-licensing-analysis)
7. [Selected Architecture — Deterministic Pipeline + Optional Agent](#7-selected-architecture--deterministic-pipeline--optional-agent)
8. [Best-of-Breed Component Selection](#8-best-of-breed-component-selection)
9. [Functional Specification](#9-functional-specification)
10. [Segment & Top-Mover Screening](#10-segment--top-mover-screening)
11. [Indicator Engine (`pandas-ta-classic` submodule)](#11-indicator-engine-pandas-ta-classic-submodule)
12. [Weighted Confluence Signal Engine](#12-weighted-confluence-signal-engine)
13. [Entry / Exit Criteria & Order Generation](#13-entry--exit-criteria--order-generation)
14. [Execution & Fill Model](#14-execution--fill-model)
15. [Robustness Validation (delegated to `openbb-backtest`)](#15-robustness-validation-delegated-to-openbb-backtest)
16. [Optional Agent / MCP Layer](#16-optional-agent--mcp-layer)
17. [Non-Functional Requirements](#17-non-functional-requirements)
18. [Phased Delivery Roadmap](#18-phased-delivery-roadmap)
19. [Risks & Mitigations](#19-risks--mitigations)
20. [Open Questions / Decisions Needed](#20-open-questions--decisions-needed)
21. [Appendix A — Indicator & Signal Repo Inventory](#appendix-a--indicator--signal-repo-inventory)
22. [Appendix B — Glossary](#appendix-b--glossary)

---

## 1. Executive Summary

This PRD proposes **`openbb-techtrade`**, a first-party OpenBB Platform extension that
turns **technical indicators into actionable trade plans** for the **top movers in each
market segment**. Where `openbb-backtest` answers *"would this rule have worked over
history?"*, this engine answers the forward-looking, operational question:

> *"Across each GICS sector right now, which top movers are giving the strongest
> technical setups, and what are the concrete entry, exit, and order/fill instructions?"*

It composes existing, permissively-licensed building blocks into one coherent,
deterministic pipeline exposed as `obb.techtrade.*`:

- A **segment-aware top-mover screener** that reuses OpenBB's `equity.discovery`
  endpoints (gainers / losers / active) and `fmp_cached`, grouped by **GICS sector**.
- A **batch indicator engine** built on the first-party **`pandas-ta-classic`** submodule
  (192 indicators + 62 candlestick patterns, MIT) plus OpenBB's existing `technical`
  extension where it already covers an indicator — no re-implementation.
- A **weighted multi-indicator confluence engine** (trend / momentum / volatility /
  volume families vote into a composite score) producing transparent, tunable signals.
- **Entry/exit criteria** (threshold cross, ATR stop, R-multiple target, time-stop) that
  emit an **order list** and a **paper-simulated fill list** via a **live-ready broker
  interface** (no real routing in v1), and a **full Excel recommendation** (entry/stop/
  target levels, stop gaps, risk/reward, position size, and reasoning).
- **Robustness validation delegated to `openbb-backtest`** — every proposed rule set can
  be walk-forward / PBO / Deflated-Sharpe checked before it is trusted.
- An **optional agent / MCP layer** that narrates rankings and exposes the deterministic
  tools to LLM clients, without ever being the decision-maker.

**Central architectural decision:** the **signal core is deterministic and reproducible**
(seeded, point-in-time, `Data`/`OBBject` round-tripping), and the **agent is an optional
shell**. This keeps results testable and auditable while still offering the "agentic"
surface the request calls for. The primary indicator dependency is a **first-party MIT
fork** consumed as a **submodule**, so there is no licensing friction and a direct path to
extend indicators when the engine needs one.

---

## 2. Problem Statement & Motivation

The fork already has the raw materials for technical trade generation but no component
that *assembles* them into a per-segment, top-mover, order-ready workflow:

- OpenBB ships a **`technical`** extension (rsi, macd, bbands, atr, adx, stoch, ema,
  ichimoku, donchian, kc, vwap, aroon, fisher, demark, clenow, …) and a **`quantitative`**
  extension — but these are **per-series calculators**, not a strategy that decides
  *when* and *what* to trade.
- OpenBB ships **`equity.discovery`** (`gainers`, `losers`, `active`,
  `undervalued_large_caps`, `undervalued_growth`, `aggressive_small_caps`, `growth_tech`)
  — top-mover lists, but **not grouped by segment** and **not wired to a signal engine**.
- The `Quant-Strategies-Guide.md` §5 catalogs the best TA libraries (batch + streaming),
  the indicator-tuning tool `tuneta`, and a cluster of **signal-fusion / confluence**
  projects (`QTradeX`, `intelligent-trading-bot`, `orallexa`) — but they are fragmented,
  variously structured, and not OpenBB-native.

Today, answering *"give me the strongest technical setups among today's top movers in
each sector, with entries, exits, and orders"* requires manual stitching across all three.
Naively adopting any single signal-fusion repo would inherit its data model, its (often
crypto-centric) assumptions, and **none of the research-integrity tooling** that separates
a credible rule from a curve-fit. The right move — mirroring the backtest PRD — is to
build **one engine, designed for this platform**, that orchestrates the best
permissively-licensed pieces and delegates validation to `openbb-backtest`.

---

## 3. Goals & Non-Goals

### Goals

- **G1 — Segment-aware top-mover discovery.** Screen and rank top movers **within each
  GICS sector** from `equity.discovery` + `fmp_cached`, on a configurable rank metric.
- **G2 — Deterministic signal core.** Indicators → weighted confluence score →
  entry/exit decision, fully reproducible (seeded, point-in-time, no look-ahead).
- **G3 — First-party indicator engine via submodule.** Use `pandas-ta-classic`
  (MIT submodule) as the breadth engine; reuse OpenBB `technical` where it already covers
  an indicator; never re-implement an indicator that already exists.
- **G4 — Transparent, tunable confluence.** Trend / momentum / volatility / volume
  families each vote; weights and thresholds are explicit config, not magic numbers.
- **G5 — Concrete trade artifacts.** Emit a `TradePlan` per symbol: entry criteria, exit
  criteria (stop / target / time), position size, an **order list**, a paper-simulated
  **fill list**, and a **full Excel recommendation** (entry/stop/target levels, stop gaps,
  risk/reward, and plain-English reasoning) under `Analysis/exports/`.
- **G6 — Live-ready, paper-only execution.** A pluggable `BrokerInterface` simulates fills
  (slippage / commission) in v1; the same interface can back a real broker later.
- **G7 — Overfitting-aware.** Any tuned rule set can be handed to `openbb-backtest` for
  walk-forward / CPCV / PBO / Deflated-Sharpe validation before being trusted.
- **G8 — Optional agent / MCP surface.** An LLM layer can narrate rankings and call the
  deterministic tools (incl. as MCP tools) — strictly optional, never authoritative.
- **G9 — OpenBB-native surface.** Exposed as `obb.techtrade.*` using standard Router /
  `OBBject[Model]` / `Data` conventions, identical to existing extensions.
- **G10 — Permissive license hygiene.** Every dependency is MIT / BSD / Apache-2.0
  (AGPL-compatible); the submodule is first-party MIT.

### Non-Goals

- **NG1 — Not a live broker / execution gateway in v1.** Paper/sim fills only; the
  `BrokerInterface` is live-ready but no real routing ships in v1.
- **NG2 — Not a backtesting engine.** Historical robustness testing is **delegated** to
  `openbb-backtest`; this engine generates signals/orders, it does not re-implement
  walk-forward/PBO/DSR.
- **NG3 — Not a new market-data provider.** Reuse `fmp_cached` / existing providers and
  `equity.discovery`.
- **NG4 — Not an LLM-first decision-maker.** The agent never overrides the deterministic
  signal core; it explains and orchestrates only (per the chosen posture).
- **NG5 — Not HFT / tick / L2.** Daily bars first; intraday (hourly/minute) and streaming
  (talipp / `streaming_indicators`) are documented later phases, not v1.
- **NG6 — Not a fundamental screener.** Segment membership and movers are the axis;
  fundamental scoring belongs to the `Analysis/` module and `openbb-quant`.

---

## 4. Guiding Principles

1. **Deterministic core, optional intelligence.** The signal/order path is reproducible
   from inputs alone; the agent is a removable shell. Same inputs → identical orders.
2. **Compose, don't re-implement.** Reuse `pandas-ta-classic`, OpenBB `technical`, and
   `equity.discovery`. New code is glue, scoring, rules, and execution — not indicators.
3. **Transparency over cleverness.** Every signal traces to named indicator votes and
   explicit weights; a user can always answer *"why did it say buy?"*.
4. **No look-ahead.** Signals on bar *t* use only data through bar *t*; orders fill at
   *t+1* in the paper model (shared discipline with `openbb-backtest`).
5. **Overfitting is the enemy.** Tuned parameters are suspect until `openbb-backtest`
   attaches an overfitting probability. Fixed defaults ship un-tuned and honest.
6. **License hygiene is architectural.** Permissive-only deps; the indicator engine is a
   first-party MIT submodule, kept current via its source branch.
7. **Privacy-first.** Personal holdings stay in local MySQL; the engine emits
   normalized/synthetic series outward — never account numbers, lot detail, or dollar
   amounts (per fork rules).
8. **Composability.** Engine outputs are `Data`/`OBBject` and round-trip through Python,
   REST, and CLI unchanged.

---

## 5. Comparative Analysis of Technical-Indicator & Signal Sources

Sourced from `Quant-Strategies-Guide.md` §5 and the signal-fusion cluster. Reference repos
live in the sibling `OpenBB` checkout's `quant_repos/`. Scores are this team's assessment
for **our** use case (daily equity, segment top-movers, deterministic signal generation),
not a universal ranking.

### 5.1 Batch indicator libraries (Python)

| Library | License | Strengths | Weaknesses for us | Fit |
|---|---|---|---|---|
| **pandas-ta-classic** (`prajoria/` fork) | **MIT** | 192 indicators + 62 candlestick patterns; `df.ta` accessor; fluent chaining; multiprocessing Strategy; optional TA-Lib/numba backends | Batch-only (no streaming yet) | **Core (first-party submodule)** |
| **OpenBB `technical`** ext | AGPL (ours) | Already installed; OBBject-native (rsi/macd/bbands/atr/adx/stoch/ema/ichimoku/…) | Smaller set; per-series only | **Core (reuse where covered)** |
| **TA-Lib** (`mrjbq7/ta-lib`, `TA-Lib/ta-lib-python`) | BSD | 150+ indicators + candlesticks; C-fast | C build dependency | **Optional accel backend** (via pandas-ta-classic `talib=True`) |
| `bukosabino/ta` | MIT | 43 clean pure-pandas indicators; sklearn-friendly | Subset of pandas-ta-classic | Reference / fallback |
| `peerchemist/finta` | LGPL-ish/MIT* | 80+ incl. adaptive MAs (KAMA/HMA/ZLEMA/FRAMA) | Verify license; overlaps fork | Reference |
| `cirla/tulipy` | LGPL | Cython Tulip bindings; fast | Oracle-only in fork | Parity oracle only |

\* Verify each repo's `LICENSE` before any reuse beyond reference (see §6).

### 5.2 Streaming / incremental indicators (future intraday/live)

| Library | License | Note | Fit |
|---|---|---|---|
| `nardew/talipp` | MIT | O(1) incremental TA, chaining, large set (Williams %R, Ichimoku) | **Future (live/intraday phase)** |
| `mr-easy/streaming_indicators` | MIT | Stateful SMA/EMA/RSI; O(1) | Future reference |

### 5.3 Indicator tuning

| Tool | License | Role |
|---|---|---|
| **`jmrichardson/tuneta`** | **MIT** | Distance-correlation-to-forward-return tuning + Optuna; prunes correlated indicators | **Optional extra (`[tuneta]`)** — tuned output **must** pass §15 validation |

### 5.4 Signal-fusion / confluence references

| Project | License | Idea we borrow | Fit |
|---|---|---|---|
| `squidKid-deluxe/QTradeX-AI-Agents` | (study) | ~40 indicator-confluence recipes; weighted consensus | Pattern reference |
| `asavinov/intelligent-trading-bot` | (study) | Offline/online **feature-parity** pipeline; declarative derived features/labels | **Design pattern (parity guarantee)** |
| `nazmiefearmutcu/TRADING-BOT` | (study) | 15-indicator weighted consensus × multi-timeframe | Pattern reference |
| `alex-jb/orallexa-ai-trading-agent` | (study) | Multi-source fusion + adaptive per-source weighting | Agent-layer reference (§16) |

These are **study/pattern references** — we re-implement the confluence-scoring idea
natively (§12), we do **not** vendor their code (verify licenses; several are unspecified).

### 5.5 Verdict

No single repo is a drop-in. **`pandas-ta-classic`** (first-party MIT submodule) is the
clear breadth engine; **OpenBB `technical`** is reused where it already covers an
indicator; **`tuneta`** is the right optional tuner; the **confluence pattern** is best
re-implemented natively for transparency and OBBject-nativeness. The optimal design is a
**composition with a native scoring/rules/execution core** — see §7.

---

## 6. Licensing Analysis

License posture is simpler here than in the backtest PRD because **every selected
dependency is permissive**.

### 6.0 Governing facts

1. **This fork is AGPL-3.0** (inherited from OpenBB). AGPL is the strongest copyleft here
   and already obligates the whole work to stay free and open.
2. **The project is non-commercial** — never sold, freely usable and redistributable.

The relevant test is therefore simply *"is the dependency AGPL-3.0-compatible?"* — and
MIT, BSD, and Apache-2.0 all are.

### 6.1 Eligibility

| Component | License | AGPL-compatible? | Role |
|---|---|---|---|
| **pandas-ta-classic** (`prajoria/` fork) | **MIT** | ✅ | **Core — first-party git submodule** |
| OpenBB `technical` / `discovery` | AGPL (ours) | ✅ | Core (reuse) |
| `fmp_cached` provider | AGPL (ours) | ✅ | Data |
| **tuneta** | **MIT** | ✅ | Optional extra (`[tuneta]`) |
| TA-Lib (C + python) | BSD | ✅ | Optional accel backend |
| `openbb-backtest` (companion) | AGPL (ours) | ✅ | Validation delegate |
| `exchange_calendars` | Apache-2.0 | ✅ | Sessions/holidays (shared w/ backtest) |

### 6.2 Submodule posture (the one thing to get right)

- `pandas-ta-classic` is **first-party and MIT**, vendored as a **git submodule** under
  `external/pandas-ta-classic`. MIT permits inclusion in an AGPL tree; the combined work
  is distributed under AGPL while the submodule retains its MIT `LICENSE`.
- Because it is **our fork**, indicator gaps are fixed on its **source branch** and pulled
  in by bumping the submodule pin — no waiting on upstream, no vendoring of foreign source.
- **Pin discipline:** the submodule is pinned to a specific commit; CI records the pin so
  results stay deterministic. A submodule bump is a reviewable change like any other.

### 6.3 Study-only references

The signal-fusion repos in §5.4 are **pattern references**; several have unspecified
licenses. We **re-implement** the confluence idea from their described behavior and do not
copy their source. Verify any `LICENSE` before going beyond reading.

**Conclusion:** a best-in-class technical-trading core is achievable with an
**entirely permissive** dependency set; the only operational rule is **keep the submodule
pinned and reviewed**.

---

## 7. Selected Architecture — Deterministic Pipeline + Optional Agent

A **layered, linear pipeline**. Each stage is independently testable, has a
`Data`/`OBBject` contract, and is swappable. The agent/MCP layer wraps the pipeline but is
never in the decision path.

```mermaid
flowchart TD
    subgraph SEG["[1] Segment & Mover Screener"]
        GICS["GICS sector universe\n(sector -> constituents / ETF)"]
        DISC["equity.discovery\n(gainers / losers / active)"]
        FC["fmp_cached (OHLCV)"]
        GICS --> RANK["Top-N movers per sector\n(rank: %chg / volume / gap)"]
        DISC --> RANK
        FC --> RANK
    end

    subgraph IND["[2] Indicator Engine"]
        PTAC["pandas-ta-classic (submodule)\ndf.ta — 192 ind + 62 candles"]
        OBBT["OpenBB technical ext\n(where already covered)"]
        RANK --> PANEL["Indicator panel per symbol\n(trend / momentum / vol / volume)"]
        PTAC --> PANEL
        OBBT --> PANEL
    end

    subgraph SIG["[3-4] Confluence + Rules"]
        SCORE["Weighted confluence score\n(votes -> composite in [-1,+1])"]
        RULES["Entry/exit rules\n(threshold / ATR stop / R-target / time)"]
        PANEL --> SCORE --> RULES
    end

    subgraph EXEC["[5] Orders, Fills & Recommendation"]
        ORD["Order list"]
        BRK["BrokerInterface\n(paper fill sim: slippage/commission)"]
        FILL["Fill list"]
        REC["Recommendation\n(entry/stop/target + reasoning)"]
        RULES --> ORD --> BRK --> FILL --> REC
    end

    subgraph OUT["[6] Outputs"]
        TP["TradePlan per symbol\n+ per-sector ranked MoverSignals"]
        XLS["Excel workbook\n(Analysis/exports/*.xlsx)"]
        FILL --> TP
        ORD --> TP
        REC --> TP
        TP --> XLS
    end

    subgraph OPT["Optional, off the decision path"]
        TUNE["tuneta (extra)\nper-sector param tuning"]
        VAL["openbb-backtest.validate()\nWFO / CPCV / PBO / DSR"]
        AGENT["Agent / MCP layer\n(narrate + expose tools)"]
    end

    TUNE -. tunes .-> SCORE
    RULES -. validate .-> VAL
    TP --> API["obb.techtrade.* (Router / OBBject / Data)"]
    AGENT -. calls .-> API
    API --> CONSUMERS["Python · REST · CLI · MCP · portfolio_app"]

    %% --- high-contrast styling (dark text on light-medium fills, bold borders) ---
    classDef data fill:#bfdbfe,stroke:#1e3a8a,stroke-width:2px,color:#0b1f4d;
    classDef ind  fill:#bbf7d0,stroke:#166534,stroke-width:2px,color:#052e16;
    classDef sig  fill:#fde68a,stroke:#b45309,stroke-width:2px,color:#3f2d00;
    classDef exec fill:#fed7aa,stroke:#c2410c,stroke-width:2px,color:#431407;
    classDef out  fill:#ddd6fe,stroke:#6d28d9,stroke-width:2px,color:#2e1065;
    classDef opt  fill:#e5e7eb,stroke:#374151,stroke-width:2px,color:#111827;
    classDef api  fill:#fbcfe8,stroke:#a21caf,stroke-width:2px,color:#500724;

    class GICS,DISC,FC,RANK data;
    class PTAC,OBBT,PANEL ind;
    class SCORE,RULES sig;
    class ORD,BRK,FILL,REC exec;
    class TP,XLS out;
    class TUNE,VAL,AGENT opt;
    class API,CONSUMERS api;

    %% subgraph borders tinted per stage; neutral background keeps node text readable
    style SEG  fill:#f8fafc,stroke:#1e3a8a,stroke-width:1px,color:#0b1f4d;
    style IND  fill:#f8fafc,stroke:#166534,stroke-width:1px,color:#052e16;
    style SIG  fill:#f8fafc,stroke:#b45309,stroke-width:1px,color:#3f2d00;
    style EXEC fill:#f8fafc,stroke:#c2410c,stroke-width:1px,color:#431407;
    style OUT  fill:#f8fafc,stroke:#6d28d9,stroke-width:1px,color:#2e1065;
    style OPT  fill:#f8fafc,stroke:#374151,stroke-width:1px,color:#111827,stroke-dasharray:6 4;

    %% darken edges and edge labels for contrast
    linkStyle default stroke:#334155,stroke-width:1.5px,color:#111827;
```

**Why a deterministic pipeline, not an agent-first design:**

- The signal core must be **reproducible and testable** — golden-file trade plans, unit
  tests with no LLM, byte-identical orders from identical inputs.
- The **agent adds value where reasoning helps** (explaining a ranking, fusing context,
  serving MCP clients) but is **removable** — pull it out and the engine still produces the
  same orders.
- **Tuning and validation are off the hot path**: `tuneta` proposes parameters, but they
  only become defaults after `openbb-backtest` attaches an overfitting verdict.

---

## 8. Best-of-Breed Component Selection

| Capability | Chosen component | License | Why it wins |
|---|---|---|---|
| Breadth indicator engine | **pandas-ta-classic** (`prajoria/` fork, submodule) | MIT | 192 ind + 62 candles; first-party → extensible on source branch |
| Already-covered indicators | **OpenBB `technical`** ext | AGPL (ours) | OBBject-native; no duplication |
| Top-mover lists | **OpenBB `equity.discovery`** | AGPL (ours) | gainers/losers/active already implemented |
| Historical OHLCV | **`fmp_cached`** | AGPL (ours) | Existing cache; deterministic; no re-download |
| Sessions/holidays | **`exchange_calendars`** | Apache-2.0 | Authoritative; shared with `openbb-backtest` |
| Confluence scoring | **In-house** (pattern from QTradeX/ITB) | AGPL (ours) | Transparency + OBBject-native |
| Indicator/param tuning | **tuneta** (optional extra) | MIT | Distance-corr + Optuna; prunes correlated indicators |
| Robustness validation | **openbb-backtest** (delegate) | AGPL (ours) | Reuses WFO/CPCV/PBO/DSR; no duplication |
| Excel recommendation export | **pandas + openpyxl** | BSD/MIT | Matches existing `equity_screener_tool.py` export convention |
| Optional reasoning/MCP | **In-house agent shell** | AGPL (ours) | Optional; never authoritative |

---

## 9. Functional Specification

### 9.1 Extension layout

Mirrors the on-disk shape of existing extensions and the backtest PRD: sub-router per
domain, lazy imports, `models.py`, `helpers.py`.

```
openbb_platform/extensions/techtrade/
├── openbb_techtrade/
│   ├── __init__.py
│   ├── techtrade_router.py        # top-level Router; includes sub-routers
│   ├── models.py                  # Pydantic Data models (see §9.3)
│   ├── helpers.py                 # df<->Data plumbing, alignment, returns
│   ├── py.typed
│   ├── engine/
│   │   ├── screener.py            # GICS segment + top-mover ranking (uses equity.discovery)
│   │   ├── indicators.py          # pandas-ta-classic + OpenBB technical adapter -> panel
│   │   ├── confluence.py          # weighted multi-indicator voting -> composite score
│   │   ├── rules.py               # entry/exit criteria -> orders
│   │   └── execution.py           # BrokerInterface + paper fill simulation + Recommendation builder
│   ├── reporting/
│   │   └── excel_export.py        # multi-sheet .xlsx recommendation workbook (openpyxl)
│   ├── tuning/
│   │   └── tuneta_adapter.py      # OPTIONAL ([tuneta] extra) per-segment param tuning
│   ├── validation/
│   │   └── backtest_bridge.py     # hands rules to openbb-backtest.validate()
│   ├── agent/                     # OPTIONAL reasoning + MCP tool exposure
│   │   ├── narrator.py
│   │   └── mcp_tools.py
│   └── strategies/                # curated confluence presets (trend/mean-rev/breakout)
├── external/
│   └── pandas-ta-classic/         # GIT SUBMODULE (prajoria/pandas-ta-classic, MIT)
├── tests/
├── README.md
└── pyproject.toml                 # entry point: openbb_core_extension
```

**Entry point** (`pyproject.toml`):

```toml
[tool.poetry.plugins."openbb_core_extension"]
techtrade = "openbb_techtrade.techtrade_router:router"

[tool.poetry.extras]
tuneta = ["tuneta"]          # MIT — optional per-segment indicator tuning
talib  = ["TA-Lib"]          # BSD — optional C acceleration backend for pandas-ta-classic
agent  = ["mcp"]             # optional agent / MCP tool surface
```

The `pandas-ta-classic` submodule is installed editable from `external/` so its source
branch is directly developable. After `python -c "import openbb; openbb.build()"`, all
commands appear under `obb.techtrade.*`.

### 9.2 Command surface (`obb.techtrade.*`)

| Command | Purpose |
|---|---|
| `obb.techtrade.segments(...)` | List supported GICS segments + their resolved universes |
| `obb.techtrade.movers(segment=..., metric=..., top_n=...)` | Top-N movers for one/all segments; returns `MoverList` |
| `obb.techtrade.signals(symbols\|segment, preset=..., weights=...)` | Compute confluence signals; returns `list[MoverSignal]` |
| `obb.techtrade.plan(symbols\|segment, preset=..., risk=...)` | Full `TradePlan` per symbol (entry/exit/size/orders) |
| `obb.techtrade.scan(metric=..., top_n=..., preset=...)` | One-call: screen **all** sectors → ranked `TradePlan`s |
| `obb.techtrade.orders(plan)` | Materialize the order list from a `TradePlan` |
| `obb.techtrade.simulate(orders, fill_model=...)` | Paper-fill the orders; returns `FillList` |
| `obb.techtrade.export(plans, path=..., engine=...)` | Write the full Excel recommendation workbook (§14.3); returns the file path |
| `obb.techtrade.validate(plan, method="wfo"\|"cpcv")` | Delegate to `openbb-backtest`; returns `ValidationReport` |
| `obb.techtrade.tune(segment, ...)` | (extra) Tune indicator params via `tuneta`; returns `TuningReport` |

All inputs/outputs are `Data`/`OBBject` so they round-trip through Python, REST, CLI, and
MCP.

### 9.3 Core data models (`models.py`)

```python
class SegmentConfig(Data):
    segment: str                       # GICS sector, e.g. "Information Technology"
    universe_source: Literal["etf_holdings", "constituent_list", "screener"] = "etf_holdings"
    benchmark_etf: str | None = None   # e.g. "XLK" for IT
    rank_metric: Literal["pct_change", "volume", "gap", "rel_volume"] = "pct_change"
    top_n: int = 10

class MoverList(Data):
    segment: str
    as_of: date
    movers: list[Mover]                # symbol, pct_change, volume, rank

class IndicatorPanel(Data):
    symbol: str
    as_of: date
    trend: dict[str, float]            # macd_hist, adx, ema_fast, ema_slow, ...
    momentum: dict[str, float]         # rsi, stoch_k, stoch_d, ...
    volatility: dict[str, float]       # bb_pctb, atr, kc_upper, ...
    volume: dict[str, float]           # obv_slope, cmf, ...
    candles: dict[str, int]            # detected candlestick pattern flags

class IndicatorVote(Data):
    family: Literal["trend", "momentum", "volatility", "volume"]
    name: str                          # e.g. "macd_hist"
    vote: float                        # in [-1, +1]
    weight: float

class MoverSignal(Data):
    symbol: str
    segment: str
    as_of: date
    score: float                       # composite confluence score in [-1, +1]
    direction: Literal["long", "short", "flat"]
    votes: list[IndicatorVote]         # full attribution (why)
    rank_in_segment: int

class EntryExitRule(Data):
    entry_threshold: float = 0.4       # |score| cross to enter
    exit_on_opposite: bool = True
    atr_stop_mult: float = 2.0         # stop = entry -/+ atr_stop_mult * ATR
    target_r_multiple: float = 2.0     # take-profit at R multiple
    max_holding_bars: int | None = 20  # time stop

class Order(Data):
    symbol: str
    side: Literal["buy", "sell", "sell_short", "buy_to_cover"]
    quantity: Decimal
    order_type: Literal["market", "limit", "stop"] = "market"
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    tif: Literal["day", "gtc"] = "day"
    intent: Literal["entry", "exit_stop", "exit_target", "exit_time", "exit_signal"]

class Fill(Data):
    order_ref: str
    timestamp: datetime
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal                     # fill price after slippage
    commission: Decimal
    slippage: Decimal

class TradePlan(Data):
    symbol: str
    segment: str
    as_of: date
    signal: MoverSignal
    rule: EntryExitRule
    position_size: Decimal             # shares (risk-based, see §13)
    orders: list[Order]
    simulated_fills: list[Fill]        # paper model (v1)
    recommendation: Recommendation     # human-facing full call (see §14.2)
    validation: ValidationReport | None = None

class Recommendation(Data):
    """The full, human-facing trade call derived from a paper-filled TradePlan.
    This is the row-level record that becomes one line of the Excel export (§14.3)."""
    symbol: str
    segment: str
    as_of: date
    action: Literal["BUY", "SELL_SHORT", "HOLD/FLAT"]
    conviction: Literal["High", "Medium", "Low"]   # bucketed from |score|
    score: float                       # composite confluence score in [-1, +1]
    # --- price levels (from paper fill + rules) ---
    entry_price: Decimal               # simulated next-bar-open fill
    stop_price: Decimal                # ATR stop (§13)
    target_price: Decimal              # R-multiple target (§13)
    stop_distance_pct: float           # |entry - stop| / entry
    target_distance_pct: float         # |target - entry| / entry
    risk_reward: float                 # reward / risk (R multiple)
    atr: float                         # ATR(14) used for the stop
    # --- sizing & risk ---
    position_size: Decimal             # shares
    risk_per_share: Decimal            # entry - stop (abs)
    risk_pct_of_notional: float        # sizing risk fraction used
    time_stop_bars: int | None         # max holding period
    # --- narrative ---
    reasoning: str                     # 2-4 sentence plain-English rationale
    top_factors: list[str]             # e.g. ["MACD+ (trend)", "RSI 62 (momentum)", "OBV rising"]
    caveats: str                       # divergences / weak votes / validation note

class ExportConfig(Data):
    path: str | None = None            # default: Analysis/exports/techtrade_<date>.xlsx
    engine: Literal["openpyxl", "xlsxwriter"] = "openpyxl"
    include_sheets: list[str] = ["Recommendations", "Levels", "Reasoning",
                                  "Orders", "Fills", "Summary"]
    conditional_formatting: bool = True  # color BUY/SELL, R:R, conviction
```

---

## 10. Segment & Top-Mover Screening

The first stage maps **GICS sectors → universes**, then ranks **top movers within each**.

- **Segment universe resolution** (`SegmentConfig.universe_source`):
  - `etf_holdings` (default) — sector SPDR holdings (e.g. `XLK`, `XLF`, `XLE`, `XLV`,
    `XLY`, `XLP`, `XLI`, `XLB`, `XLRE`, `XLU`, `XLC`) as the constituent proxy.
  - `constituent_list` — an explicit symbol list per sector.
  - `screener` — derive membership from `fmp_cached` sector/industry fields.
- **Mover ranking** reuses **`equity.discovery`** (`gainers` / `losers` / `active`) for the
  cross-market candidate pool, then **filters to each segment** and re-ranks by
  `rank_metric` (`pct_change`, `volume`, `gap`, `rel_volume`).
- **Calendars** via `exchange_calendars` (`XNYS` default) so "today's movers" respects
  sessions/half-days — consistent with `openbb-backtest`.
- **Output:** a `MoverList` per segment, and a combined per-sector ranking for `scan`.

> **Why reuse `equity.discovery`:** it already implements the mover endpoints; this engine
> adds the **segment grouping + signal wiring** on top, rather than a second screener.

---

## 11. Indicator Engine (`pandas-ta-classic` submodule)

The indicator stage turns each mover's OHLCV history into an `IndicatorPanel`.

- **Primary engine:** the **`pandas-ta-classic`** submodule via its `df.ta` accessor and
  **multiprocessing Strategy** for bulk computation across a segment's symbols at once.
- **Reuse-first rule:** where OpenBB's `technical` extension already exposes an indicator
  (rsi, macd, bbands, atr, adx, stoch, ema, ichimoku, …), the adapter prefers it for
  OBBject-nativeness; `pandas-ta-classic` fills the breadth gaps and **all 62 candlestick
  patterns**.
- **Optional acceleration:** if the `[talib]` extra is installed, `pandas-ta-classic`
  routes its 34 TA-Lib-backed indicators through the C implementation; otherwise native
  Python is used (`talib=False`). Results are equivalent within tolerance (the fork ships
  a parity oracle).
- **Feature-parity discipline** (pattern from `intelligent-trading-bot`): the *same*
  indicator definitions produce the panel in both batch (v1) and any future streaming
  path, so signals don't silently change between offline and online.
- **Determinism:** indicator periods are fixed defaults unless a `tune` result overrides
  them; the submodule commit pin makes the computation reproducible.

Default indicator set per family (overridable):

| Family | Default indicators |
|---|---|
| **Trend** | MACD(12,26,9) histogram, ADX(14), EMA(20) vs EMA(50) cross |
| **Momentum** | RSI(14), Stochastic(14,3,3) |
| **Volatility** | Bollinger %B(20,2), ATR(14), Keltner(20,2) |
| **Volume** | OBV slope(10), Chaikin Money Flow(20) |
| **Candles** | `cdl_pattern("all")` → confirmation flags |

---

## 12. Weighted Confluence Signal Engine

The proposed **best-in-class default strategy**: a transparent, tunable weighted
consensus. Re-implemented natively from the confluence pattern (QTradeX / ITB / multi-
indicator consensus bots), expressed as explicit `IndicatorVote`s.

### 12.1 Voting

Each indicator maps its reading to a **vote ∈ [-1, +1]**:

- **Trend** — `sign(macd_hist)` gated by ADX strength (`adx > 20` ⇒ full weight, else
  damped); EMA-cross adds +1 (golden) / −1 (death).
- **Momentum** — RSI > 55 ⇒ +; RSI < 45 ⇒ −; magnitude scales toward ±1 at 70/30; stoch
  K/D cross confirms sign.
- **Volatility** — regime-aware: in a trend regime, Bollinger %B > 1 breakout ⇒ + (continue);
  in a range regime, price at the band ⇒ mean-revert vote. ATR does **not** vote — it sets
  stop distance (§13).
- **Volume** — acts as a **confirmation multiplier**: rising OBV / positive CMF amplifies a
  same-sign score; divergence damps it.

### 12.2 Composite score

```
raw   = Σ_family ( w_family · Σ_indicator (vote_i / n_indicators) )
score = clip(raw · volume_confirmation, -1, +1)
```

- **Default weights:** trend `0.40`, momentum `0.25`, volatility `0.20`, volume `0.15`
  (volume applied as the confirmation multiplier). All weights are explicit config.
- **Direction:** `long` if `score ≥ +entry_threshold`, `short` if `score ≤ −entry_threshold`,
  else `flat`.
- **Attribution:** every `MoverSignal` carries its full `votes` list, so the engine can
  always answer *"why long?"* — the transparency principle (§4.3).

### 12.3 Presets

`strategies/` ships three named presets that reweight the same families:

| Preset | Tilt | Typical use |
|---|---|---|
| `trend_follow` (default) | trend-heavy; breakout volatility | momentum movers |
| `mean_revert` | momentum + band-touch; trend damped | overextended movers |
| `breakout` | volatility + volume; ADX gate strict | gap / high-rel-volume movers |

### 12.4 Optional tuning (`[tuneta]`)

`tune` uses **`tuneta`** to fit indicator periods/weights **per segment** by distance
correlation to forward returns, pruning correlated indicators (Optuna + KMeans cluster
selection). **Tuned parameters are not trusted until** `openbb-backtest.validate()` (§15)
returns a non-overfit verdict — guarding the well-known overfitting risk of TA tuning.

---

## 13. Entry / Exit Criteria & Order Generation

Given a `MoverSignal` and an `EntryExitRule`, the rules engine produces concrete orders.

- **Entry:** when `|score|` crosses `entry_threshold` in a new direction → an **entry
  order** (`market` next-bar-open by default, or `limit` at a configurable offset).
- **Exit (whichever first):**
  - **Stop:** `entry ∓ atr_stop_mult · ATR(14)` (a `stop` order).
  - **Target:** R-multiple — `entry ± target_r_multiple · (entry − stop)` (a `limit` order).
  - **Signal:** opposite-direction threshold cross (`exit_on_opposite`).
  - **Time:** `max_holding_bars` reached (`exit_time`).
- **Position sizing (risk-based, default):** shares chosen so that the stop distance equals
  a fixed **risk fraction** of notional (e.g. risk 1% of a configured account size per
  trade): `qty = floor(risk_budget / (atr_stop_mult · ATR))`. Sizing parameters are config;
  no personal dollar amounts are emitted (privacy rule §4.7) — outward artifacts use
  normalized notional unless run locally against `portfolio_app`.
- **Order list:** a `TradePlan` emits an ordered list — entry first, then the contingent
  stop / target / time exits with `intent` tags so downstream consumers (or a real broker
  later) understand each order's role.

**Look-ahead discipline:** signals computed on bar *t* generate orders that fill at *t+1*
in the paper model — identical to `openbb-backtest`'s next-bar-open convention.

---

## 14. Execution & Fill Model

v1 is **paper/sim only** behind a **live-ready `BrokerInterface`** so a real broker can be
slotted in later without touching the signal core. The paper fill is not an end in
itself — it produces the concrete **entry/stop/target prices** that drive a **full,
human-facing Excel recommendation** (§14.2–§14.3).

### 14.1 Broker interface & fill simulation

```python
class BrokerInterface(Protocol):
    def submit(self, order: Order, bar: Bar) -> Fill | None: ...
    def cancel(self, order_ref: str) -> None: ...
    def positions(self) -> list[PositionSnapshot]: ...
```

- **Default impl — `PaperBroker`:** fills entry at next-bar-open ± slippage; evaluates
  stop/target intrabar against bar high/low; applies commission.

| Model | Options (default) |
|---|---|
| **Commission** | per-share / per-trade flat / percentage (default = zero-commission equities) |
| **Slippage** | fixed bps (default 5 bps) / volume-share price-impact / spread-based |
| **Fill** | next-bar-open (default; prevents same-bar look-ahead) / limit-with-timeout |
| **Stops/targets** | intrabar touch against bar high/low; conservative tie-breaking |

- **Output:** a `FillList` (the requested **order fill list**) plus updated positions.
- **Live-ready:** the same `BrokerInterface` can later back Alpaca/IBKR; v1 ships
  `PaperBroker` only (NG1). Live routing is a separate, explicitly out-of-scope phase.

### 14.2 Recommendation builder

The paper fill yields the realized **entry price**; combined with the rules engine (§13)
it fixes **stop** and **target** levels. From these, `engine/execution.py` assembles a
`Recommendation` (§9.3) — the **full, human-facing trade call** that pairs the numbers
with **reasoning**:

- **Action & conviction:** `BUY` / `SELL_SHORT` / `HOLD/FLAT` from signal direction;
  conviction bucketed from `|score|` (`≥0.7` High, `0.4–0.7` Medium, `<0.4` Low).
- **Price levels & gaps:** `entry_price`, `stop_price`, `target_price`, plus the derived
  **`stop_distance_pct`**, **`target_distance_pct`**, and **`risk_reward`** (the "stop gap"
  context a reader needs at a glance), with the `atr` that set the stop.
- **Sizing & risk:** `position_size`, `risk_per_share`, and `risk_pct_of_notional`
  (normalized notional outward — no personal dollar amounts, §4.7).
- **Reasoning (deterministic, not LLM):** a templated 2–4 sentence rationale generated
  from the `MoverSignal.votes` attribution — e.g. *"Long NVDA: trend strongly positive
  (MACD histogram +, ADX 28, EMA20>EMA50), momentum confirming (RSI 62), and rising OBV
  confirms participation. Stop 2×ATR below entry (−3.1%); target at 2R (+6.2%)."* Plus
  `top_factors` (the highest-weight votes) and `caveats` (divergences, weak votes, or a
  pending/failed validation verdict). The optional agent layer (§16) may *rewrite* this
  prose more fluently, but the **deterministic template is the source of truth** and is
  what ships when the agent is absent.

### 14.3 Excel recommendation export (template)

`obb.techtrade.export(plans, ...)` writes a **multi-sheet `.xlsx` workbook** — the
shareable deliverable. It uses **`pandas.ExcelWriter(engine="openpyxl")`**, matching the
existing `fmp_cached/equity_screener_tool.py` export convention; `xlsxwriter` is an
optional engine for richer conditional formatting. Default path:
`Analysis/exports/techtrade_<YYYY-MM-DD>.xlsx`.

**Workbook structure** (one row per recommendation, sorted by segment then conviction):

| Sheet | Purpose | Key columns |
|---|---|---|
| **Recommendations** | The headline call — one line per symbol | `Segment`, `Symbol`, `Action`, `Conviction`, `Score`, `Entry`, `Stop`, `Target`, `Stop %`, `R:R`, `Shares`, `Reasoning` (short) |
| **Levels** | Price/stop/target detail & gaps | `Symbol`, `Entry`, `Stop`, `Target`, `Stop Distance %`, `Target Distance %`, `ATR(14)`, `Risk/Share`, `Risk %`, `Time Stop (bars)` |
| **Reasoning** | Full narrative & attribution | `Symbol`, `Reasoning` (full), `Top Factors`, `Caveats`, per-family vote breakdown (Trend / Momentum / Volatility / Volume) |
| **Orders** | The order list per plan | `Symbol`, `Side`, `Qty`, `Type`, `Limit`, `Stop`, `TIF`, `Intent` |
| **Fills** | Paper-simulated fills | `Symbol`, `Side`, `Qty`, `Fill Price`, `Commission`, `Slippage`, `Timestamp` |
| **Summary** | Run metadata & roll-ups | As-of date, calendar, preset, weights, segment counts, # BUY/SELL/FLAT, avg R:R, submodule pin, validation coverage |

**Formatting (when `conditional_formatting=True`, default):**
- `Action` color-coded (green BUY / red SELL_SHORT / grey FLAT); `Conviction` shaded.
- `R:R` data-bar / color scale (green ≥ 2.0, amber 1.0–2.0, red < 1.0).
- `Stop Distance %` and `Score` color scales; frozen header row; auto-filter on
  **Recommendations**; currency/percent number formats; column auto-width.
- A title block on **Recommendations**: *"OpenBB TechTrade — Top-Mover Recommendations,
  <date>"* plus a one-line **disclaimer** ("Research/paper output — not investment advice").

**Layout sketch — `Recommendations` sheet:**

```
OpenBB TechTrade — Top-Mover Recommendations — 2026-06-09   [Research/paper output — not advice]
┌────────────────┬────────┬────────┬──────────┬───────┬───────┬───────┬────────┬────────┬─────┬────────┬───────────────────────────┐
│ Segment        │ Symbol │ Action │Conviction│ Score │ Entry │ Stop  │ Target │ Stop % │ R:R │ Shares │ Reasoning                 │
├────────────────┼────────┼────────┼──────────┼───────┼───────┼───────┼────────┼────────┼─────┼────────┼───────────────────────────┤
│ Info Technology│ NVDA   │ BUY    │ High     │ +0.72 │ 121.40│ 117.6 │ 129.0  │ -3.1%  │ 2.0 │ 41     │ Trend+ (MACD,ADX28), RSI62…│
│ Info Technology│ AMD    │ BUY    │ Medium   │ +0.51 │  98.20│  95.1 │ 104.4  │ -3.2%  │ 1.9 │ 50     │ Trend+ but volume diverg…  │
│ Financials     │ JPM    │ HOLD   │ Low      │ +0.18 │   —   │   —   │   —    │   —    │  —  │ 0      │ Mixed: trend flat, RSI52…  │
└────────────────┴────────┴────────┴──────────┴───────┴───────┴───────┴────────┴────────┴─────┴────────┴───────────────────────────┘
```

**Determinism:** identical inputs produce a byte-stable workbook (sorted rows, fixed
column order, no timestamps in cells beyond the as-of/run date). The Excel file is an
artifact under `Analysis/exports/` (consistent with existing export conventions); the
`Recommendation`/`ExportConfig` `Data` models round-trip through Python/REST/CLI/MCP, so
the same content is available without opening Excel.


---

## 15. Robustness Validation (delegated to `openbb-backtest`)

This engine **generates** signals/orders; it does **not** re-implement backtesting.
`validation/backtest_bridge.py` translates a `TradePlan` (or a tuned rule set) into an
`openbb-backtest` strategy and calls `obb.backtest.validate(...)`.

- **Methods (from the companion PRD §14):** Walk-Forward Optimization, Combinatorial Purged
  Cross-Validation, Probability of Backtest Overfitting, Deflated Sharpe Ratio.
- **Gate on tuning:** a `tune` result becomes a default **only** if validation returns
  `robust` (not `fragile` / `overfit`).
- **Output:** the `ValidationReport` is attached to the `TradePlan.validation` field, so a
  plan can always be inspected for its overfitting probability before action.

> This is the deliberate division of labor: `openbb-techtrade` = forward signal/order
> generation; `openbb-backtest` = historical robustness. Neither duplicates the other.

---

## 16. Optional Agent / MCP Layer

An **optional, removable** shell (`agent/`, `[agent]` extra). It never makes trading
decisions — it narrates and orchestrates the deterministic tools.

- **Narrator (`narrator.py`):** given a `list[MoverSignal]` / `TradePlan`s, produces a
  human-readable per-sector briefing ("XLK: NVDA strongest long, score +0.72, driven by
  MACD+ADX trend and OBV confirmation; stop 2×ATR"). It reads the `votes` attribution —
  it does not invent signals.
- **MCP tools (`mcp_tools.py`):** exposes `segments`, `movers`, `signals`, `plan`, `scan`,
  `export`, `validate` as **MCP tools** so external LLM clients can call the deterministic
  engine. Pattern reference: `orallexa` multi-source fusion, but **without** giving the LLM
  decision authority (NG4).
- **Determinism guarantee:** with the agent layer removed, identical inputs still yield
  identical `TradePlan`s. The agent is tested separately and is never on the golden-file
  path.

---

## 17. Non-Functional Requirements

| Area | Requirement |
|---|---|
| **Python** | 3.10–3.13 (match platform); primary dev on Windows 3.12 |
| **Determinism** | Seeded; fixed indicator periods unless tuned; submodule commit-pinned → reproducible signals/orders |
| **Performance** | Scan all 11 GICS sectors × top-10 movers (≈110 symbols) daily-bar end-to-end in < 30 s on a mid-range CPU (multiprocessing Strategy) |
| **Concurrency** | Sync MySQL path (PyMySQL) for `fmp_cached` — avoid the known Windows 3.12 aiohttp `CancelledError` |
| **Submodule** | `external/pandas-ta-classic` pinned to a reviewed commit; bump is a normal PR; CI records the pin |
| **Excel export** | `pandas` + `openpyxl` (engine matches `equity_screener_tool.py`); deterministic byte-stable workbook; artifacts under `Analysis/exports/`; every workbook carries a "research/paper — not advice" disclaimer |
| **Testing** | Unit (no DB, no LLM) with synthetic OHLCV; golden-file `TradePlan`s **and golden `.xlsx`** with known answers; integration via `FMP_CACHE_TEST_MODE=true`; agent layer tested separately |
| **Privacy** | No PII/dollar/lot leakage; sizing uses normalized notional outward; secrets via `user_settings.json`/env only |
| **Code quality** | Ruff (line-length 122), `Decimal` for money, `pathlib`, `logging` not `print`, no emoji |
| **Licensing** | All deps MIT/BSD/Apache-2.0 (AGPL-compatible); submodule first-party MIT; no Commons-Clause anywhere |

---

## 18. Phased Delivery Roadmap

| Phase | Milestone | Scope | Exit criteria |
|---|---|---|---|
| **P0** | Foundations | Extension skeleton; `pandas-ta-classic` submodule wired + editable install; models; GICS segment map | `obb.techtrade.segments` resolves all 11 sectors; submodule imports |
| **P1** | Segment screener | `movers` / segment grouping over `equity.discovery` + `fmp_cached`; `exchange_calendars` | `obb.techtrade.movers(segment=...)` returns ranked `MoverList` |
| **P2** | Indicator engine | `pandas-ta-classic` + OpenBB `technical` adapter → `IndicatorPanel`; bulk Strategy | Panel reproduces golden indicator values; TA-Lib parity holds |
| **P3** | Confluence engine | Weighted voting → `MoverSignal` with full attribution; 3 presets | `signals` reproduces a golden score; `votes` explain it |
| **P4** | Rules + orders + fills | `EntryExitRule`, sizing, `Order` list, `PaperBroker` fill sim → `FillList` | `plan` / `scan` emit full `TradePlan` + fill list; no look-ahead |
| **P5** | Recommendation + Excel export | `Recommendation` builder (levels/stop-gaps/reasoning); multi-sheet `.xlsx` via openpyxl | `export` writes golden `.xlsx`; reasoning traces to votes |
| **P6** | Validation bridge | `backtest_bridge` → `openbb-backtest.validate`; attach verdict | `validate` returns a verdict on a sample plan |
| **P7** | Tuning (extra) | `tuneta` per-segment tuning gated by P6 validation | `tune` proposes params; only robust ones persist |
| **P8** | Agent / MCP (extra) | Narrator + MCP tool exposure (incl. `export`) | Briefing generated; tools callable; core unchanged when removed |
| **P9 (future)** | Streaming / intraday | `talipp`/`streaming_indicators` O(1) path; hourly/minute; live `BrokerInterface` impl | Feature-parity with batch; opt-in; license-reviewed |

---

## 19. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **TA over-tuning** | Tuned params look great in-sample, fail live | `tune` gated by `openbb-backtest` PBO/DSR; defaults ship un-tuned |
| **Look-ahead in signals** | False setups | Bar-*t* signals → *t+1* fills; no same-bar peeking; golden-file tests |
| **Submodule drift / unpinned** | Non-reproducible signals | Commit-pin the submodule; CI records pin; bump via reviewed PR |
| **Indicator duplication (fork vs OpenBB `technical`)** | Divergent values for "same" indicator | Reuse-first rule + parity oracle; single adapter decides source |
| **Segment universe accuracy** | Wrong movers per sector | ETF-holdings default + configurable source; validate membership counts |
| **Confluence weights are arbitrary** | Distrust / poor signals | Weights explicit + per-preset; `tune` + validation justify deviations |
| **Agent overreach** | LLM makes/alters trades | NG4 hard rule; agent off the decision path; core deterministic without it |
| **Cross-repo references** | Companion PRDs / `quant_repos` live in sibling `OpenBB` checkout | Treat as reference; resolve via Q1; don't hard-depend on those paths at runtime |
| **Windows 3.12 async issues** | Runtime failures | Sync PyMySQL path; no aiohttp in engine |
| **Live-trading scope creep** | Never ships | NG1 firm; `PaperBroker` only in v1; live is a separate phase |

---

## 20. Open Questions / Decisions Needed

> **How to use this section.** Each question has an **Answer:** placeholder — write your
> decision inline after the marker. A `Recommendation:` line records the working group's
> default *suggestion*; it is **not** decided until you fill in **Answer:**.

**Q1 — Repo consolidation / cross-repo references.**
This engine is specified in `OpenBBTechnical`, but the companion PRDs, `quant_repos/`, and
`openbb-backtest` live in the sibling `OpenBB` checkout. Do we (a) develop `openbb-techtrade`
in `OpenBBTechnical` and depend on `openbb-backtest` as an installed package, (b) merge the
two checkouts, or (c) build both engines in the same checkout?
- *Recommendation:* (a) — keep checkouts separate; depend on `openbb-backtest` as a package.
- **Answer:** _(decision pending)_

**Q2 — Segment taxonomy.**
GICS **sectors** (11) only, or also allow GICS **industry groups** / sub-industries and
cap-tier overlays as alternative segment axes?
- *Recommendation:* Ship 11 sectors in v1; make the segment axis pluggable for later.
- **Answer:** 11 GICS sectors only in v1; keep the segment axis pluggable for later.
  Maps 1:1 to the SPDR sector ETFs used by Q3; industry-group / sub-industry / cap-tier
  overlays are an additive axis to be added later without rework. Gates #68.

**Q3 — Segment universe source of truth.**
Sector-ETF holdings (default), explicit constituent lists, or `fmp_cached` sector fields?
- *Recommendation:* ETF-holdings default with the other two as configurable sources.
- **Answer:** ETF-holdings as the default; `constituent_list` and `screener` as
  configurable alternatives via `SegmentConfig.universe_source` (default `etf_holdings`).
  Stable, externally-defined membership with no extra data dependency. Gates #69.

**Q4 — Default confluence weights.**
Adopt trend `0.40` / momentum `0.25` / volatility `0.20` / volume `0.15` (volume as
confirmation multiplier), or derive defaults from a one-time `openbb-backtest` study?
- *Recommendation:* Ship the stated weights; revisit after a validation study.
- **Answer:** trend `0.40` / momentum `0.25` / volatility `0.20` / volume `0.15`, with
  volume as a confirmation multiplier (not an additive vote). Ship un-tuned and honest;
  weights live in explicit per-preset config and may be revisited after a one-time
  `openbb-backtest` study. Gates #74.

**Q5 — Intraday in v1.**
Daily bars only in v1 (streaming deferred to P8), or include hourly from the start?
- *Recommendation:* Daily only in v1.
- **Answer:** Daily bars only in v1. Streaming / hourly / minute deferred to P9 (#87).
  Matches `fmp_cached`'s daily-bar strength and the bar-*t* → *t+1* no-look-ahead discipline.

**Q6 — Account-size / sizing inputs.**
Use a configurable abstract notional for sizing (privacy-safe), or integrate with
`portfolio_app` holdings when run locally?
- *Recommendation:* Abstract notional by default; optional local `portfolio_app` integration.
- **Answer:** _(decision pending)_

**Q7 — Relationship to `openbb-quant`.**
Is `openbb-techtrade` standalone, or a sub-surface of the broader `openbb-quant` proposal
(alongside `openbb-backtest`)?
- *Recommendation:* Standalone extension; `openbb-quant` may orchestrate it.
- **Answer:** _(decision pending)_

**Q8 — Candlestick patterns in scoring.**
Treat the 62 candlestick patterns as a scoring family (extra votes) or as confirmation-only
flags in v1?
- *Recommendation:* Confirmation flags in v1; promote to a weighted family after validation.
- **Answer:** Confirmation-only flags in v1 (populate `IndicatorPanel.candles`); not a
  weighted scoring family. Keeps the composite driven by the four explicit families (Q4);
  promote to a weighted family only after a validation study. Affects #72, #74.

**Q9 — Excel export engine & formatting.**
Ship `openpyxl` only (matches the existing screener tool), or also support `xlsxwriter`
for richer conditional formatting / charts? And is the per-workbook
"research/paper — not investment advice" disclaimer sufficient?
- *Recommendation:* `openpyxl` default in core, `xlsxwriter` as an optional engine;
  disclaimer required on the `Recommendations` sheet of every export.
- **Answer:** _(decision pending)_

---

## Appendix A — Indicator & Signal Repo Inventory

Technical-indicator and signal-fusion repositories relevant to this design. Reference repos
live in the sibling `OpenBB` checkout's `quant_repos/`; the submodule is vendored in *this*
tree.

**Indicator engine (core):**
- `prajoria/pandas-ta-classic` (**MIT — first-party submodule**) — 192 indicators + 62
  candlestick patterns; `df.ta`; multiprocessing Strategy; optional TA-Lib/numba.
- OpenBB `technical` extension (**core, reuse**) — OBBject-native rsi/macd/bbands/atr/adx/
  stoch/ema/ichimoku/donchian/kc/vwap/aroon/fisher/demark/clenow.

**Indicator references / fallbacks:**
- `bukosabino__ta` (MIT), `peerchemist__finta` (verify), `mrjbq7__ta-lib` /
  `TA-Lib__ta-lib-python` (BSD — optional accel), `cirla__tulipy` (LGPL — parity oracle),
  `mementum__bta-lib`.

**Streaming (future P8):**
- `nardew__talipp` (MIT), `mr-easy__streaming_indicators` (MIT).

**Tuning:**
- `jmrichardson__tuneta` (**MIT — optional extra**).

**Signal-fusion / confluence (pattern references — re-implemented natively):**
- `squidKid-deluxe__QTradeX-AI-Agents`, `asavinov__intelligent-trading-bot`,
  `nazmiefearmutcu__TRADING-BOT`, `alex-jb__orallexa-ai-trading-agent`.

**Reused OpenBB surfaces:**
- `equity.discovery` (gainers/losers/active/…), `fmp_cached` provider,
  `gerrymanoim__exchange_calendars` (Apache-2.0).

**Validation delegate:**
- `openbb-backtest` (companion PRD) — WFO / CPCV / PBO / DSR.

---

## Appendix B — Glossary

- **Confluence** — combining multiple independent indicators into one consensus signal;
  here, weighted family votes summed into a composite score in [-1, +1].
- **GICS sector** — one of 11 Global Industry Classification Standard sectors used as the
  segment axis (e.g. Information Technology, Financials, Energy).
- **Top mover** — a symbol ranked highly within its segment by a movement metric
  (%change, volume, gap, relative volume) for the session.
- **Vote** — an indicator's mapped opinion in [-1, +1] (e.g. RSI>55 ⇒ positive momentum).
- **Confirmation multiplier** — volume signals scale (not add to) the trend/momentum score.
- **R-multiple** — profit target expressed as a multiple of initial risk (entry−stop).
- **Recommendation** — the full human-facing trade call (action, conviction, entry/stop/
  target levels, stop gap, risk/reward, size, and reasoning) built from a paper-filled
  `TradePlan`; one `Recommendation` = one row of the Excel export.
- **Stop gap / stop distance** — the percentage distance from entry to the stop level
  (`|entry − stop| / entry`); the immediate downside a reader sees per recommendation.
- **ATR stop** — a stop placed a multiple of Average True Range away from entry.
- **Look-ahead bias** — using information not available at decision time; prevented by
  bar-*t* → fill-*t+1* discipline.
- **PBO / DSR / CPCV / WFO** — overfitting-control methods (Probability of Backtest
  Overfitting / Deflated Sharpe Ratio / Combinatorial Purged Cross-Validation / Walk-Forward
  Optimization); provided by `openbb-backtest`, not re-implemented here.
- **Feature parity** — guarantee that offline (batch) and online (streaming) paths compute
  the *same* indicators, so signals don't change between research and live.
- **Submodule pin** — the exact commit of `pandas-ta-classic` recorded for reproducibility.

---

*End of document.*
