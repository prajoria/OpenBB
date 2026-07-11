# PRD & Functional Spec: `openbb-core-journal` — Shared Journaling + Replay Primitive

**Status:** Draft / Proposal — for review
**Author:** Trading Automation working group
**Target component:** `openbb_platform/core/journal/` (in-tree module, no separate PyPI release)
**Branch:** `journaling-primitive` (to be created off `fmp_trading` after Phase 1 lands)
**Date:** 2026-07-08
**Companion documents:**
- [`docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md`](./2026-07-06-fmp-day-trading-automation-design.md) — fmp-trading PRD (first consumer)
- [`docs/Specs/TechnicalTrading-Engine-PRD.md`](../../Specs/TechnicalTrading-Engine-PRD.md) — techtrade PRD (second consumer, retrofit target)
- [`docs/Specs/Backtesting-Engine-PRD.md`](../../Specs/Backtesting-Engine-PRD.md) — potential future consumer

**Decision posture:** Small, foundational, single-purpose. Extract *after* fmp-trading Phase 1 proves the pattern; do not design in the abstract. Every design decision below is grounded in a real fmp-trading use case.

---

## Table of Contents

1. [Problem & Motivation](#1-problem--motivation)
2. [Goals & Non-Goals](#2-goals--non-goals)
3. [Design Decisions (Locked)](#3-design-decisions-locked)
4. [Architecture](#4-architecture)
5. [Public API](#5-public-api)
6. [Consumer Retrofit — fmp-trading](#6-consumer-retrofit--fmp-trading)
7. [Consumer Retrofit — techtrade](#7-consumer-retrofit--techtrade)
8. [Task Roadmap (J1–J5)](#8-task-roadmap-j1j5)
9. [Testing Strategy](#9-testing-strategy)
10. [Risks & Mitigations](#10-risks--mitigations)
11. [Open Questions](#11-open-questions)

---

## 1. Problem & Motivation

The fmp-trading PRD (§8.7) introduced a `SessionJournal` — an NDJSON writer that captures every tick, signal, order, fill, alert, and veto during an intraday session, enabling deterministic replay (AC-8). At review time, the user observed that techtrade has neither journaling nor replay — its `scan` command produces a static Excel workbook that captures conclusions but not reasoning.

That's the wrong shape. **Journaling and replay are discipline-level primitives, not intraday-specific ones.** Techtrade would be strictly better with both:

- **Auditability** — "Why did AAPL rank #3 in the 2026-06-13 scan?" is currently unanswerable without re-running the entire pipeline with the same code + inputs. A journal records the votes, weights, tuning state, and preset in effect at that moment.
- **Regression detection** — Golden-file tests currently pin the Excel workbook layout; when the layout changes, goldens churn even when the underlying data is correct. Replay-based tests pin the *data*, not the presentation.
- **Cross-session composability** — A journal from techtrade's `scan` could feed fmp-trading's `build_daily_plan` as the "yesterday's context" input, replacing the ad-hoc `SessionResult` loader.

The right shape is a **shared primitive**: one small module that both extensions depend on, so the journaling/replay contract is identical across the fork.

## 2. Goals & Non-Goals

### Goals

- **G1** — One `JournalWriter` + `JournalReader` + `replay()` implementation, imported by every consumer. No duplicated NDJSON logic across extensions.
- **G2** — Extensible event schema: base `JournalEvent` model with `ts`/`session_id`/`event_type`/`payload`; consumers define typed subclasses that validate their own payloads.
- **G3** — Deterministic byte-identical replay: same journal + same reconstructor → same domain object across N runs. Verified by golden tests in both consumers.
- **G4** — Zero external dependencies beyond what `openbb_core` already ships (Pydantic v2, stdlib). No new PyPI packages.
- **G5** — Fmp-trading Phase 1 code lands **first** using this primitive from the start; techtrade retrofits **after**, without breaking any existing test.
- **G6** — File-system layout that survives grep + jq + git diff (NDJSON, file-per-session, human-readable).

### Non-Goals

- **NG1** — Not a general-purpose event bus (no pub/sub, no subscribers, no delivery guarantees to external systems).
- **NG2** — Not a database — no queries, no indexes, no cross-session aggregation. Journals are append-only files.
- **NG3** — Not compressed / not binary — NDJSON only. Parquet/Avro/binary formats are out of scope; performance-critical consumers can add their own compression layer atop `JournalWriter`.
- **NG4** — Not a cross-process coordination primitive — writers assume single-writer-per-file. Multi-writer requires a follow-up spec.
- **NG5** — Not a schema registry — event types are strings; consumers own their own validation via Pydantic subclasses.
- **NG6** — Not versioned as a separate package — lives in-tree under `openbb_platform/core/journal/` alongside `openbb_core`. No independent PyPI release.

## 3. Design Decisions (Locked)

The five decisions the brainstorming resolved. Each choice + rationale below.

### D1 — In-tree module, not separate package

**Choice:** `openbb_platform/core/journal/` (co-located with `openbb_core`).
**Not:** Separate PyPI package.
**Rationale:** No independent release cadence; both consumers ship in the same monorepo; matches how `openbb_core` itself is packaged. Avoids version-skew hell between `openbb-core-journal 0.1.2` and `openbb-fmp-trading 0.3.0` requiring `>=0.1.1,<0.2`. Consumers `from openbb_core_journal import ...`.

### D2 — Closed base event + open payload

**Choice:** Base `JournalEvent(Data)` with fixed shape `{ts, session_id, event_type, schema_version, payload: dict[str, Any]}`; consumers subclass with typed `payload` shapes.
**Not:** Fully open (arbitrary dicts) or fully closed (union of all known event types).
**Rationale:** Closed base gives the reader a stable filter surface (`event_type="fill"`); open payload lets consumers evolve without touching this module. Consumer subclasses (`FillEvent(JournalEvent)`) provide Pydantic validation of payload shape at deserialization time.

### D3 — NDJSON serialization

**Choice:** One JSON object per line, UTF-8, no compression.
**Not:** Parquet, msgpack, protobuf, JSON array.
**Rationale:** Human-readable, streamable, appendable without rewriting the whole file, `jq`-compatible for ad-hoc queries, git-diffable when small. NDJSON's cost is size; at ~50k events × ~200 bytes/event = ~10MB per full session, well inside any modern disk. Compression is a follow-up if profiling shows it matters.

### D4 — File-per-session storage

**Choice:** `~/.openbb_platform/journals/<extension>/<session_id>.ndjson`.
**Not:** One big database, per-day rollup, or in-repo tracking.
**Rationale:** Grep-friendly, deletable per session, doesn't require any storage-service dependency. Small enough to commit to git for goldens (`tests/fixtures/journals/*.ndjson`). Extension prefix (`fmp_trading/`, `techtrade/`) keeps consumers isolated.

### D5 — `schema_version` on every event

**Choice:** Every `JournalEvent` carries `schema_version: int = 1`; reader raises `SchemaVersionError` on unknown version.
**Not:** No versioning (fragile) or SemVer strings (over-engineered for a small module).
**Rationale:** One-line cost, buys us clean forward-migration when payload shapes need to change. Consumers can bump their subclass's version independently of the base schema.

## 4. Architecture

```
openbb_platform/core/journal/
├── __init__.py              # re-exports JournalWriter, JournalReader, JournalEvent, replay
├── event.py                 # JournalEvent base model (Pydantic v2, Data-inheriting)
├── writer.py                # JournalWriter — append-only NDJSON with atomic-flush guarantees
├── reader.py                # JournalReader — streaming iteration, event-type filtering
├── replay.py                # replay(journal_path, reconstruct_fn) skeleton
├── errors.py                # JournalError base + SchemaVersionError, MalformedEventError
└── py.typed                 # PEP 561 marker

openbb_platform/core/journal/tests/
├── unit/
│   ├── test_writer.py       # round-trip, atomic-append, tail-safe
│   ├── test_reader.py       # stream, filter, malformed-line handling
│   └── test_replay.py       # replay determinism (byte-identical across 3 runs on a fixture)
└── fixtures/
    └── sample_session.ndjson    # 20-event fixture used by both writer and reader tests
```

### 4.1 Data model

```python
# openbb_platform/core/journal/event.py
from datetime import datetime
from typing import Any, Literal
from openbb_core.provider.abstract.data import Data


class JournalEvent(Data):
    """Base event. Every journaled event inherits from this."""
    schema_version: int = 1
    ts: datetime                                # tz-aware, UTC internally
    session_id: str                             # UUID or date-based scope
    event_type: str                             # dispatch key ("tick","signal","fill",...)
    payload: dict[str, Any]                     # consumer-typed via subclass


class JournalError(Exception): ...
class SchemaVersionError(JournalError): ...
class MalformedEventError(JournalError): ...
```

### 4.2 Writer contract

```python
# openbb_platform/core/journal/writer.py
class JournalWriter:
    def __init__(self, journal_path: Path, session_id: str): ...
    def write(self, event: JournalEvent) -> None: ...   # atomic append + fsync on rotation
    def close(self) -> None: ...                        # explicit flush
    def __enter__(self) -> "JournalWriter": ...
    def __exit__(self, *exc) -> None: ...               # calls close()
```

Guarantees:
- **Append-only**: no rewriting or truncation
- **Atomic per-line**: writer holds an exclusive lock during `write()`; a crash mid-line leaves the file consistent (last partial line is discarded by reader per §4.3)
- **Auto-flush on close**: never silently lose events

### 4.3 Reader contract

```python
# openbb_platform/core/journal/reader.py
class JournalReader:
    def __init__(self, journal_path: Path): ...
    def stream(
        self,
        event_types: list[str] | None = None,
    ) -> Iterator[JournalEvent]: ...
    def read_all(self) -> list[JournalEvent]: ...  # convenience for small journals
```

Behaviors:
- **Malformed-line tolerance**: skips + logs any line that fails JSON parse or Pydantic validation (never raises mid-stream)
- **Unknown-version rejection**: raises `SchemaVersionError` immediately on any `schema_version > CURRENT_VERSION`
- **Filter push-down**: when `event_types` is set, non-matching lines are skipped without full Pydantic validation (perf win for large journals)

### 4.4 Replay skeleton

```python
# openbb_platform/core/journal/replay.py
from typing import Callable, TypeVar
T = TypeVar("T")

def replay(
    journal_path: Path,
    reconstruct: Callable[[list[JournalEvent]], T],
    event_types: list[str] | None = None,
) -> T:
    """Read a journal fully and hand to the consumer's reconstructor.

    The consumer supplies its own reconstruction logic; this function just
    guarantees deterministic event delivery. Byte-identical replay depends on
    the reconstructor being pure — see docs/testing/replay-determinism.md.
    """
    reader = JournalReader(journal_path)
    events = list(reader.stream(event_types=event_types))
    return reconstruct(events)
```

That's the whole module. ~150 lines of production code.

## 5. Public API

Consumers `from openbb_core_journal import ...`. Full exported surface:

```python
from openbb_core_journal import (
    JournalEvent,              # base model — subclass with typed payloads
    JournalWriter,             # write per-session
    JournalReader,             # read + iterate
    replay,                    # reader → reconstructor pipeline
    JournalError,              # base exception
    SchemaVersionError,        # forward-compat guard
    MalformedEventError,       # payload validation failure
    CURRENT_SCHEMA_VERSION,    # int constant, currently 1
)
```

No other public symbols. If a consumer needs something else, it's a request to extend this module, not to reach inside it.

## 6. Consumer Retrofit — fmp-trading

Fmp-trading Phase 1 was going to build a local `SessionJournal` in `openbb_fmp_trading/core/session_journal.py`. That module is now deleted; replaced with typed subclasses that import from `openbb_core_journal`:

```python
# openbb_fmp_trading/models/journal_events.py
from openbb_core_journal import JournalEvent
from openbb_fmp_trading.models.plan import DailyPlan
# etc.

class TickEvent(JournalEvent):
    event_type: Literal["tick"] = "tick"
    # payload is validated via pydantic model_post_init using a typed shape:
    # {watchlist_size: int, quotes_fetched: int, mode: str}

class SignalEvent(JournalEvent):
    event_type: Literal["signal"] = "signal"
    # payload: {symbol: str, score: float, direction: str, votes: dict[str, int]}

class OrderEvent(JournalEvent): ...
class FillEvent(JournalEvent): ...
class AlertEvent(JournalEvent): ...
class VetoEvent(JournalEvent): ...
class RiskStateChangeEvent(JournalEvent): ...
```

Fmp-trading Phase 1 plan `P1.4 SessionJournal NDJSON writer + reader/replay foundation` gets replaced with `P1.4 Define fmp_trading typed JournalEvent subclasses + wire JournalWriter into IntradaySession.__init__`. Same acceptance criteria, half the code.

**Impact on fmp-trading roadmap:** J1-J3 must land before fmp-trading P1.4. That's a **blocker** to file explicitly.

## 7. Consumer Retrofit — techtrade

The higher-value retrofit — this is where the journaling gap you flagged actually gets closed.

### Where journaling gets added

Techtrade's decision pipeline (from `openbb_techtrade` source layout):
```
segments → movers → panels → confluence → signals → rules → orders → fills → recommendation
```

Journal events one per stage per symbol:

| Stage | Event type | Payload sketch |
|---|---|---|
| `movers` | `mover_ranked` | `{segment, symbol, rank, metric, value}` |
| `panels` | `indicator_computed` | `{symbol, indicator, timeframe, value, engine}` (engine = `pandas-ta-classic\|technical`) |
| `confluence` | `vote_cast` | `{symbol, family, weight, direction, score_contribution}` |
| `signals` | `signal_ranked` | `{symbol, score, direction, preset, rank_in_segment}` |
| `rules` | `plan_sized` | `{symbol, entry, stop, target, position_size, risk_per_share}` |
| `orders` | `order_generated` | `{symbol, intent, side, qty, limit_price, stop_price}` |
| `fills` | `fill_simulated` | `{symbol, price, qty, slippage, commission}` |
| `recommendation` | `recommendation_built` | `{symbol, action, conviction, reasoning}` |
| tuning | `tune_applied` | `{segment, preset, weights, source: "default\|tuned"}` |

### New commands

```python
# unchanged — still writes Excel:
obb.techtrade.scan(metric="pct_change", top_n=5) → OBBject[list[TradePlan]]

# NEW — same as scan but also writes journal:
obb.techtrade.scan(metric="pct_change", top_n=5, journal_path=Path) → OBBject[list[TradePlan]]

# NEW — reconstruct a scan from a prior journal:
obb.techtrade.replay(journal_path) → OBBject[list[TradePlan]]
```

### Backward compatibility

- `journal_path=None` (default) → no journal written; techtrade behavior unchanged
- Existing golden tests unchanged
- New golden test: `test_replay_determinism.py` runs `scan` with `journal_path=X`, then `replay(X)`, asserts equal `list[TradePlan]`

### What this buys techtrade

- Audit trail per historical scan (`journals/techtrade/2026-06-13.ndjson`)
- Data-level (not layout-level) regression tests
- Composability with fmp-trading (fmp-trading's pre-open agent can read yesterday's techtrade journal instead of round-tripping through Excel)

## 8. Task Roadmap (J1–J5)

Sized ~1 week total single-dev. Plan-doc granularity same as fmp-trading Phase 0 (bite-sized 2-5 min steps with full code).

| # | Task | Files touched | Depends on | ~Size |
|---|---|---|---|---|
| **J1** | Scaffold `openbb-core-journal` | `openbb_platform/core/journal/__init__.py`, `errors.py`, empty stubs; `pyproject.toml`; `dev_install.py` addition | — | 1-2 hr |
| **J2** | Writer + reader + base event | `event.py`, `writer.py`, `reader.py`; unit tests for round-trip + malformed-line handling | J1 | 1 day |
| **J3** | Replay skeleton + determinism golden | `replay.py`; `tests/unit/test_replay.py` with 3x byte-identical assertion on `sample_session.ndjson` fixture | J2 | 0.5 day |
| **J4** | Retrofit fmp-trading Phase 1 P1.4 | Delete `openbb_fmp_trading/core/session_journal.py`; add `openbb_fmp_trading/models/journal_events.py`; update `pyproject.toml` deps; all fmp-trading tests still green | J1-J3 + fmp-trading P1.1-P1.3 | 1 day |
| **J5** | Retrofit techtrade with journaling + replay | Add `openbb_techtrade/journal_events.py`; add `journal_path=` kwarg to `scan`/`plan`/`simulate`; add `replay()` command; new golden `test_replay_determinism.py`; existing tests unchanged | J1-J3 | 2 days |

**Sequencing recommendation:** J1-J3 first (independent), then J4 + J5 in parallel (different consumers).

## 9. Testing Strategy

### 9.1 Unit tests (in `openbb_platform/core/journal/tests/unit/`)

Per module:
- `test_writer.py`: round-trip N events; assert order preserved; assert atomic-append semantics under simulated mid-line crash (write half a line, reader skips it cleanly)
- `test_reader.py`: stream vs. `read_all`; `event_types` filter push-down; malformed-line tolerance; `SchemaVersionError` on future-version event
- `test_replay.py`: determinism golden — same fixture read 3x, `render_json` of `list[JournalEvent]` byte-identical

### 9.2 Consumer integration tests

- **fmp-trading**: Phase 5's AC-8 test (already spec'd in the fmp-trading PRD) — replays a fixture session 3x, asserts byte-identical `SessionResult`. Just now runs against the shared primitive instead of a local module.
- **techtrade**: new `tests/golden/test_replay_scan_determinism.py` — runs `scan` with `journal_path=X`, then `replay(X)`, asserts equal `list[TradePlan]`.

### 9.3 Contract tests (in `openbb_platform/core/journal/tests/unit/test_contract.py`)

Assert that any `JournalEvent` subclass satisfies the contract: has `event_type` as `Literal[...]`, `schema_version` inheritable, round-trips through JSON. Runs against both fmp-trading and techtrade subclasses via fixtures.

## 10. Risks & Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| **R1** | fmp-trading Phase 1 finishes and lands local `SessionJournal` before J1-J3 ship | Med | Med | Explicit blocker on fmp-trading epic; if Phase 1 races ahead, J4 becomes a delete-and-replace instead of write-and-import (bigger PR, same outcome) |
| **R2** | Techtrade goldens break during J5 despite backward-compat design | Low | High | J5 acceptance requires every existing techtrade test green; `journal_path=None` default preserves current behavior byte-for-byte |
| **R3** | NDJSON writer's atomic-append semantics fail on Windows with locked-file quirks | Low | Med | Existing patterns in `openbb_core/utils/atomic_file.py` (from user-settings persistence) — reuse instead of reimplement |
| **R4** | Schema-version mismatch between consumers ("techtrade wrote v2 events, fmp-trading only reads v1") | Low | Low | `schema_version` is per-event, not per-file; reader raises specific error; no silent data loss |
| **R5** | Journals grow unbounded on disk | Med | Low | Not in v1 scope; document rotation as user's responsibility; add `journal_ttl_days` follow-up in v2 |
| **R6** | Replay determinism relies on consumer's reconstructor being pure | Med | Med | Document as a contract in `replay()` docstring; provide `test_replay_determinism.py` template; not a v1 problem to *enforce* purity |

## 11. Open Questions

**Q1 — Should the writer fsync per event or per close?**
Recommendation: **per close** (fast writes, crash loses at most last N buffered events). Fsync per event adds ~1ms per write; on a 5s tick loop with 10 events/tick that's ~2% overhead, but negligible on techtrade's one-scan-per-day cadence. Configurable via `JournalWriter(fsync_mode="per_event"|"per_close")`.

**Q2 — Cross-session composability — is there a `merge` helper?**
Recommendation: **no in v1**. Consumers can iterate multiple readers themselves. If real demand appears (e.g. fmp-trading's post-close agent wants to reason over the last 5 days of techtrade scans), add a follow-up.

**Q3 — Should the base `JournalEvent` include `agent_generated: bool`?**
Recommendation: **no**. Consumers can add it to their payload if relevant. Base stays lean.

**Q4 — Should there be a `TruncatedError` when reading a partial last line?**
Recommendation: **no**, silently skip + log. Truncation from a crash is not an error condition the caller can meaningfully handle.

---

*Document complete. Ready for user review before implementation planning.*
