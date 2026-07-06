# Pine Extraction to prajoria/pynecore — Design

**Author:** Prashant Rajoria (with Claude Code)
**Date:** 2026-07-06 (revision 2 — 2026-07-06 later same day)
**Status:** Draft for review — REVISED to address PR #328 reviewer findings
**Branch:** `design/pine-extraction-to-pynecore`
**Related:** openbb-pine Phase 2 epic `OpenBBTechnical-0e9.6` (paused for this extraction); tracking bead `OpenBBTechnical-rbf`

## Revision history

- **Rev 1** (2026-07-06 morning): Initial design after 7-question brainstorm. Committed at `0025d8149`, opened as PR #328.
- **Rev 2** (2026-07-06 afternoon): Addresses 5 BLOCK + 4 GAP + 2 QUESTION + 3 NIT findings from PR #328 review. Key structural changes:
  - Added new **Phase E0 (pre-extraction refactor)** to §6 — splits `errors.py` into compiler/provider halves, refactors `security_dispatcher`/`executor` to consume abstract interfaces, abstracts `telemetry` behind an injection point. All done INSIDE openbb-fork so post-extraction tree has zero dangling imports.
  - Updated §4 topology to reflect the E0 refactor outcome.
  - Updated §5 with `DataProvider` construction vs. call parameterization clarification.
  - Updated §9 to replace `@runtime_checkable` conformance check with behavioral suite.
  - Updated §6.E3 to add `openbb_pine.__version__` → `pyne_compiler.__version__` transition.
  - Updated §9 test baseline: 1353 (was: 1343 — stale after Wave 2 review fixes).
  - Resolved §13 open question about top-level vs. subpackage: **top-level `pyne_compiler`** (documented in §4).
  - Multiple cross-reference + line-count fixups.

---

## 1. Context

The `openbb-extension-pine` code (11,541 LOC across `openbb_platform/extensions/pine/openbb_pine/`) implements a clean-room Pine Script v6/v5 compiler + runtime for the OpenBB Platform. It currently vendors PyneCore via `third_party/pynecore/` (submodule → `prajoria/pynecore`, a fork of PyneSys upstream) and layers our compiler + provider-routing + REST/MCP surfaces on top.

Two forces motivate a restructure:

1. **Pine work is architecturally distinct from OpenBB.** The compiler, type checker, code generator, and Pine-runtime plumbing have no dependency on OpenBB's provider/router machinery — they'd be equally valuable to any project that wants to run Pine scripts. Bundling them inside `openbb_platform/extensions/pine/` conflates two concerns.
2. **The data-source model needs to open up.** PyneCore today reads only from `.ohlcv` binary files (`OHLCVReader`). Real-world consumers need MySQL, Postgres, SQLite, CSV, HTTP APIs, and streaming feeds. The `DataProvider` abstraction belongs one level closer to the runtime, not layered in OpenBB.

The user has approved the following architectural pivot: **extract the Pine compiler + core runtime + a `DataProvider` protocol to `prajoria/pynecore` as sibling packages, keep OpenBB-specific glue (FMP adapter, REST routers, MCP tools, CLI) in openbb-fork, and consume the extracted work via the existing git-submodule + editable-install pattern.**

Six architectural decisions have been made through brainstorming (2026-07-06 session):

| # | Decision | Rationale |
|---|---|---|
| 1 | **Thin core with reference adapters** (Option B) | pynecore ships the `DataProvider` protocol + reference `CSVAdapter`/`SQLiteAdapter`; project-specific adapters (FMP for OpenBB) stay in the consuming project. |
| 2 | **Sync query-based protocol** (Option B) | `stream(sym, tf, start, end) -> Iterator[OHLCV]` + `fetch(sym, tf, start, end) -> list[OHLCV]`. Aligns with `request.security()` semantics; doesn't force async refactor. |
| 3 | **Sibling packages** in one repo (Option B) | `pynecore/` (runtime, upstream) + `pyne_compiler/` (our clean-room compiler) — directory-level provenance boundary, single Apache-2.0 license. |
| 4 | **Extract first, resume Phase 2 in new home** (Option A) | Freeze 17 open Phase 2 P1 sub-beads; resume against `pyne_compiler.*` module paths after extraction. Avoids double-write of the same code. |
| 5 | **Full history preservation via `git filter-repo`** (Option B) | Preserves per-bead attribution + Clean-room trailers + `git blame`. One-time complexity for permanent audit value. |
| 6 | **Git submodule + editable install** (Option A) | Same pattern in use today. PyPI publishing deferred as separate future decision. |
| 7 | **Extract compiler + core runtime only** (Option B, this doc's operating assumption) | FMP + REST + MCP + CLI stay in openbb-fork; refactor FMP in place to consume the new `DataProvider` protocol. Least physical file movement. |

## 2. Goals

**In scope:**
- Move `compiler/` (6,840 LOC), core `runtime/` plumbing (subset of 3,484 LOC), the `errors.py` compiler/runtime errors, and the Pine-runtime-facing tests (subset of 17,211 LOC of tests) from `openbb_platform/extensions/pine/openbb_pine/` to `prajoria/pynecore` as a new `pyne_compiler/` sibling package.
- Design + implement a `DataProvider` protocol in pynecore (`pynecore/adapters/base.py`) with two reference implementations (`pynecore/adapters/csv.py`, `pynecore/adapters/sqlite.py`).
- Refactor `openbb_platform/extensions/pine/openbb_pine/runtime/fmp_provider.py` to implement `DataProvider` (kept in openbb-fork).
- Preserve full git history via `git filter-repo` — every commit's Clean-room trailer + per-bead attribution + `git blame` continue to work in the new location.
- Bump the `third_party/pynecore/` submodule in openbb-fork to point at the post-extraction pynecore HEAD; verify `pip install -e third_party/pynecore` still gives a working dev environment.
- Full pine test suite (currently 1,353 passing per `pytest --collect-only`) stays green across both repos after extraction.

**Out of scope for this design (future decisions):**
- PyPI publishing of pynecore — deferred until there's a concrete external consumer.
- Async data providers — sync-only for now; async wrappers can be added later as a non-breaking extension.
- Streaming/websocket adapters — the sync `stream()` method supports polling patterns; websocket-native support is a future enhancement.
- Migration of the M2 conformance harness / conformance corpus — those move with the compiler as part of the mechanical extraction, no design change.
- Whether `pyne_compiler/` also owns bundled Pine indicators/strategies (widgets.json) — those are OpenBB-Workspace-specific glue and stay in openbb-fork.

## 3. Non-goals / explicit exclusions

- **No behavior change** for existing `obb.pine.*` REST/MCP consumers. `obb.pine.run(source, symbol="AAPL", provider="fmp")` must produce byte-identical output before and after extraction (verified by full test suite).
- **No new legal review required for extraction itself** — the counsel signoff on PRD §2 (bead `0e9.4.1`, closed 2026-07-04) covers the Clean-room posture, which continues in the new location. If the extraction changes the FMP adapter's shape materially, that's a separate reviewable diff, not a legal concern.
- **No `develop` branch changes.** Everything lands via feature branches to `openbb_pine_support` (openbb-fork) and to `main` (pynecore, per its own conventions). Bulk merges to `develop` remain manual and human-driven per branch protection policy.
- **No PyneCore upstream contribution** — this is an extraction into a fork. Upstream `PyneSys/pynecore` remains a separate maintenance path.

## 4. Post-extraction repo topology

```
prajoria/pynecore  (fork, Apache-2.0)
├── pynecore/                        # From PyneSys upstream — runtime, Pine builtins, ScriptRunner
│   ├── core/
│   ├── lib/
│   ├── types/
│   └── adapters/                    # NEW — sibling to core/lib/types
│       ├── __init__.py
│       ├── base.py                  # DataProvider Protocol
│       ├── csv.py                   # Reference CSV adapter
│       ├── sqlite.py                # Reference SQLite adapter
│       └── file.py                  # Wraps existing OHLCVReader as a DataProvider
├── pyne_compiler/                   # NEW — our clean-room Pine v5/v6 compiler
│   ├── __init__.py
│   ├── lexer.py                     # Was: openbb_pine/compiler/lexer.py
│   ├── parser.py                    # Was: openbb_pine/compiler/parser.py
│   ├── type_checker.py              # Was: openbb_pine/compiler/type_checker.py
│   ├── codegen.py                   # Was: openbb_pine/compiler/codegen.py
│   ├── compile_cache.py             # Was: openbb_pine/compiler/compile_cache.py
│   ├── v5_migration.py              # Was: openbb_pine/compiler/v5_migration.py
│   ├── ir.py, types.py, ...         # Was: openbb_pine/compiler/*.py
│   ├── grammar/*.lark               # Was: openbb_pine/compiler/grammar/
│   ├── builtin_signatures.py        # Was: openbb_pine/compiler/builtin_signatures.py
│   ├── errors/                      # Compiler + runtime error package
│   │   ├── __init__.py              # Re-exports the PineError hierarchy
│   │   ├── base.py                  # PineError base + compiler/runtime subclasses (from openbb_pine/compiler_errors.py — E0.1 split)
│   │   ├── codes.py                 # Error code catalog (from openbb_pine/error_codes.py)
│   │   └── diagnostics.py           # Diagnostic + telemetry glue (from openbb_pine/diagnostics.py)
│   ├── runtime/                     # Pine runtime plumbing that's not OpenBB-specific
│   │   ├── executor_core.py         # ScriptRunner adapter (from post-E0.3 openbb_pine/runtime/executor_core.py)
│   │   ├── _pynecore_glue.py        # Kept as-is
│   │   ├── restricted.py            # Restricted-exec namespace
│   │   ├── limits.py                # Exec limits (timeout, RLIMIT_AS, bar cap)
│   │   ├── security_dispatcher.py   # prefetch_security_contexts (bead c1x)
│   │   ├── secondary_cache.py       # SecondarySeriesCache
│   │   ├── security_hook.py         # install_secondaries_hook (bead n6j)
│   │   └── strategy_types.py        # TradeSummary + OpenPositionSummary (bead wxz)
│   └── tests/
│       ├── unit/                    # All compiler + core-runtime unit tests migrate here
│       └── conformance/             # Conformance harness + Pine-fixture pairs
├── LICENSE                          # Apache-2.0 (from PyneSys)
├── NOTICE                           # Attribution: PyneCore upstream + our compiler additions
└── pyproject.toml                   # Both pynecore/ and pyne_compiler/ as installable packages

prajoria/OpenBB  (openbb-fork, on openbb_pine_support)
├── openbb_platform/extensions/pine/
│   └── openbb_pine/
│       ├── __init__.py              # obb.pine facade
│       ├── pine_router.py           # about() endpoint
│       ├── routers/                 # /pine/run, /pine/run_byo, /pine/indicators/list, /pine/strategies/*, /pine/health, /pine/builtins/coverage
│       │   ├── run_router.py
│       │   ├── strategies_router.py
│       │   ├── catalog_router.py
│       │   ├── health_router.py
│       │   ├── compile_router.py
│       │   └── _models.py           # Shared Pydantic request/response models
│       ├── mcp_tools.py             # MCP tool registrations
│       ├── cli/                     # openbb pine doctor CLI
│       ├── about.py                 # PineAbout model
│       ├── attribution.py           # §4(d) attribution strings
│       ├── runtime/                 # OpenBB-specific runtime glue
│       │   ├── fmp_provider.py      # FMP adapter (refactored to implement DataProvider)
│       │   ├── fmp_retry.py         # Shared retry budget for FMP
│       │   ├── byo_provider.py      # BYODataProvider (refactored to implement DataProvider)
│       │   └── provider_selection.py # Provider precedence + non-FMP fast-fail
│       ├── assets/widgets.json      # Bundled OpenBB Workspace widgets (Bollinger etc.)
│       ├── _coverage_manifest.py    # OpenBB-side coverage attribution
│       ├── errors.py                # Provider-side errors ONLY, post-E0.1 split (PineProviderError, FMP subclasses, PineDataValidationError). Compiler+runtime errors moved to pyne_compiler.errors.
│       └── tests/                   # Only OpenBB-integration + FMP + provider-selection tests remain
└── third_party/pynecore/            # Submodule → prajoria/pynecore (post-extraction HEAD)
```

**Line-count expectations after extraction (verified via `wc -l` on 2026-07-06):**
- `pyne_compiler/` in pynecore: **~11,400 LOC** (compiler 6,840 + core runtime subset ~2,660 + errors/codes/diagnostics 1,911)
- `openbb_pine/` remaining in openbb-fork: **~3,000 LOC** (routers 1,217 + FMP/BYO/retry/selection 821 + mcp/router/about/attribution/telemetry/coverage/__init__ 838 + CLI 119)
- Test migration: majority of the current 17,211 test LOC moves with the compiler+runtime. Exact split determined during E0.6 refactor. Baseline: **1,353 tests must stay green in whichever repo they land in.**

(Rev 1 of this doc estimated ~9,500 + ~4,000 LOC — corrected in rev 2 after direct measurement.)

## 5. The `DataProvider` protocol (pynecore/adapters/base.py)

```python
from __future__ import annotations

from datetime import datetime
from typing import Iterator, Protocol, runtime_checkable

from pynecore.types.ohlcv import OHLCV


@runtime_checkable
class DataProvider(Protocol):
    """Sync query-based OHLCV data source.

    Two orthogonal methods:

    * ``stream()`` yields bars one at a time — used by the primary iteration
      loop of a Pine script (open, high, low, close, volume at each bar).
    * ``fetch()`` returns a bar range as a list — used by ``request.security()``
      to load a secondary symbol/timeframe upfront before the main loop starts.

    Implementations MAY back both methods with the same underlying query
    (e.g. a SQL SELECT returned by `fetch()` and iterated for `stream()`),
    or with distinct optimized paths (e.g. a streaming HTTP endpoint for
    `stream()` and a batch REST call for `fetch()`).

    A ``DataProvider`` is stateless with respect to which bar the caller
    is on — the pynecore ``ScriptRunner`` maintains its own bar index.
    Providers therefore MUST NOT hold cursor state between calls.
    """

    def stream(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Iterator[OHLCV]:
        """Yield OHLCV bars in chronological order.

        Both ``start`` and ``end`` are inclusive when provided. ``None``
        means "from the beginning" or "to the end" respectively.

        Timestamps in yielded ``OHLCV`` records must be in UTC and
        monotonically non-decreasing.
        """
        ...

    def fetch(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[OHLCV]:
        """Return a bar range as a materialized list.

        Semantically equivalent to ``list(stream(...))``, but implementations
        can (and should) optimize batch fetches — e.g. a single SQL query
        instead of iterating cursor rows.

        Returned bars follow the same ordering + UTC guarantees as
        ``stream()``.
        """
        ...
```

**Optional metadata protocol** (not required — providers may implement for richer error messages):

```python
@runtime_checkable
class SymbolInfo(Protocol):
    """Optional provider metadata used by `syminfo.*` builtins."""

    def symbol_info(self, symbol: str) -> dict[str, str | float]:
        """Return {'ticker': ..., 'currency': ..., 'mintick': ..., ...}."""
        ...
```

**Reference adapters shipped in `pynecore/adapters/`:**

| Adapter | Backing store | Use case |
|---|---|---|
| `FileAdapter` | Existing `.ohlcv` binary files | Migration path for existing PyneCore users |
| `CSVAdapter` | CSV files (RFC 4180) with timestamp,open,high,low,close,volume columns | Local backtests, tutorials, quick experimentation |
| `SQLiteAdapter` | SQLite database with configurable table schema | Local persistence, embedded distributions |

**Consuming-project adapters (stay in their host projects):**

| Adapter | Location | Backing store |
|---|---|---|
| `FMPProvider` | openbb-fork `openbb_pine/runtime/fmp_provider.py` | Financial Modeling Prep REST API (with fmp_cached tier support) |
| `BYODataProvider` | openbb-fork `openbb_pine/runtime/byo_provider.py` | User-supplied `list[dict]` records (REST BYO endpoint) |
| Future: `MySQLAdapter`, `PostgresAdapter`, etc. | Wherever their consumers live | Their respective backing stores |

### 5.1 Construction vs. call parameterization (addresses PR #328 review finding #6)

Existing `FMPOHLCVProvider` is **construction-parameterized**: its `__init__(symbol, timeframe, start, end, api_key, ...)` locks a specific request; call sites do `list(provider)`. Existing `BYODataProvider` is similar (`__init__(records, symbol, timeframe)`).

`DataProvider` is **call-parameterized**: one instance can serve arbitrary `(symbol, timeframe, start, end)` queries via `stream()` and `fetch()`. This is REQUIRED to support `request.security()` cleanly — a single `DataProvider` instance handles both the primary symbol/timeframe and any secondaries the script requests. The alternative (one provider per (symbol, timeframe) pair) forces the dispatcher to know how to construct providers, which pushes provider-specific constructor logic into pynecore.

**E3 refactor implications for FMP + BYO adapters:**

- Their `__init__` accepts CONFIGURATION (api key, cache dir, base URL, etc.) — no symbol/timeframe/date.
- Their `__init__` no longer takes `symbol`/`timeframe`/`start`/`end` — those move to method parameters.
- Call sites that today do `provider = FMPOHLCVProvider(symbol="AAPL", timeframe="1D", start=...); bars = list(provider)` become `provider = FMPOHLCVProvider(api_key=...); bars = provider.fetch("AAPL", "1D", start=..., end=...)`.
- This is a real interface rewrite, not "add two methods." Estimated FMP adapter refactor: ~4-6 hours; BYO adapter refactor: ~2 hours. Included in E3 scope.

### 5.2 Conformance testing (addresses PR #328 review finding #7)

`@runtime_checkable` on a `Protocol` only checks **method names**, not signatures — `isinstance(adapter, DataProvider)` returns `True` for a class that defines `stream()` and `fetch()` with completely wrong parameter shapes. Empirically verified via Python 3.12.

The design DOES NOT rely on `isinstance()` for conformance. Instead, `pynecore/adapters/tests/test_conformance.py` ships a **behavioral test suite** that every adapter must pass:

```python
# pynecore/adapters/tests/test_conformance.py
import pytest
from datetime import datetime, timezone

def _conformance_suite(adapter: DataProvider):
    """Behavioral checks every DataProvider must satisfy.

    Called by adapter-specific test modules with a fixture-configured
    adapter instance.
    """
    # 1. stream() and fetch() return equivalent data for the same query
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 1, 10, tzinfo=timezone.utc)
    streamed = list(adapter.stream("TESTSYM", "1D", start=start, end=end))
    fetched = adapter.fetch("TESTSYM", "1D", start=start, end=end)
    assert streamed == fetched, "stream() and fetch() must return identical bars"

    # 2. Timestamps monotonically non-decreasing
    timestamps = [bar.timestamp for bar in fetched]
    assert timestamps == sorted(timestamps), "bars must be chronological"

    # 3. Empty range returns empty list, not error
    empty = adapter.fetch("TESTSYM", "1D",
                         start=datetime(2020, 1, 1, tzinfo=timezone.utc),
                         end=datetime(2020, 1, 2, tzinfo=timezone.utc))
    assert empty == [], "unknown range must return [] cleanly"

    # 4. start > end raises (contract: caller passed invalid range)
    with pytest.raises((ValueError, RuntimeError)):
        adapter.fetch("TESTSYM", "1D", start=end, end=start)

    # 5. Missing symbol raises typed error
    with pytest.raises((KeyError, LookupError, ValueError)):
        adapter.fetch("NEVER_EXISTS_XYZ", "1D", start=start, end=end)
```

Each concrete adapter (`test_csv.py`, `test_sqlite.py`, `test_file.py`, and downstream `test_fmp_provider.py` in openbb-fork) instantiates itself with a fixture dataset and calls `_conformance_suite(self.adapter)`. This is real conformance — signature-mismatched implementations fail at TEST time, not at production call time.

## 6. The migration process (five phases — was four; E0 added in rev 2)

### Phase E0 — Pre-extraction refactor (INSIDE openbb-fork, before any file moves)

**Where:** openbb-fork on a feature branch (`refactor/pine-pre-extraction-decoupling`).

**Why:** PR #328 review (rev 1) surfaced that compiler + core-runtime files as-shipped have ~15 cross-cutting imports of code that stays in openbb-fork (FMP provider, BYO provider, telemetry, attribution, provider-side errors). Extracting them as-is produces dangling imports in pynecore. The clean fix is to refactor the boundary IN PLACE first, so the pre-extraction openbb-fork tree already has the "compiler+runtime-only" and "provider+glue" halves cleanly separable. Once E0 lands, E2's `git filter-repo` can safely move the compiler+runtime half with zero dangling imports.

**What (six sub-refactors, each is its own commit / possibly its own PR):**

**E0.1 — Split `errors.py` into two files.** Current `errors.py` is 1050 LOC with 20+ classes mixing compiler errors (`PineSyntaxError`, `PineTypeError`, `PineCodegenError`, etc.) and provider-side errors (`PineFMPRequiredError`, `PineFMPUnreachableError`, `PineProviderError`). After E0.1:
- `openbb_pine/errors.py` — provider-side errors ONLY (PineProviderError + FMP subclasses + PineDataValidationError). ~350 LOC.
- `openbb_pine/compiler_errors.py` — compiler + runtime errors that will move to pynecore (PineError base + all compile/runtime subclasses + Diagnostic). ~700 LOC. When E2 runs, this file is what gets renamed to `pyne_compiler/errors/*.py`.
- Every existing import site of `errors.py` gets updated to the correct new import path.

**E0.2 — Refactor `security_dispatcher.py` to take a `DataProvider` interface, not FMPProvider directly.** The dispatcher currently does `from openbb_pine.runtime.fmp_provider import FMPOHLCVProvider, FMPRequest, infer_asset_class`. That coupling is the exact thing the extraction is meant to break. After E0.2:
- Dispatcher's `prefetch_security_contexts()` accepts a `provider` argument typed as the future `DataProvider` protocol (which we'll define in E1 in pynecore, but we can stub it inline in openbb-fork as a `typing.Protocol` for E0 — one file that gets deleted at E2).
- FMP-specific concepts (`FMPRequest`, `infer_asset_class`) get pushed UP to the caller (either `executor.py` or the router that instantiates the dispatcher).
- After the refactor, dispatcher only depends on `DataProvider`, `SecurityContext`, and `SecondarySeriesCache` — all of which move with it.

**E0.3 — Refactor `executor.py` similarly.** Current `executor.py` directly imports `FMPOHLCVProvider`, `BYODataProvider`, `POWERED_BY_FULL`, and provider errors. After E0.3:
- `executor.py` splits into two pieces:
  - `pyne_compiler/runtime/executor_core.py` (moves) — the compile-cache lookup, `_pynecore_glue` wiring, `_bar_iter` loop, per-bar snapshot capture, `OBBject.results` build. Takes a `DataProvider` as input. No knowledge of FMP, BYO, or attribution.
  - `openbb_pine/runtime/executor_shell.py` (stays) — the thin wrapper that instantiates the concrete provider (FMP-cached / FMP / BYO), attaches attribution (`POWERED_BY_FULL`), populates OpenBB-specific `.extra` fields, and delegates to `executor_core.run_compiled()`.
- Routers (`run_router.py`, `strategies_router.py`) call `executor_shell` instead of `executor`. Behavior is byte-identical.

**E0.4 — Abstract telemetry behind an injection point.** Compiler imports `openbb_pine.telemetry` in 9 sites (`codegen.py`, `type_checker.py`, `v5_migration.py`, `compiler/__init__.py`). After E0.4:
- `pyne_compiler` (soon-to-exist) defines a `TelemetrySink` protocol with 2 methods: `record_unsupported_feature(name)` and `record_unsupported_builtin(name)`.
- Compiler's `compile_pine()` takes an optional `telemetry: TelemetrySink | None = None` kwarg. Compiler code paths do `if telemetry: telemetry.record_unsupported_feature(...)` instead of `from openbb_pine.telemetry import ...`.
- `openbb_pine.telemetry` becomes an implementation of `TelemetrySink` that stays in openbb-fork. Openbb-fork's routers instantiate it and pass it to `compile_pine()`.
- Zero cross-repo import; compiler doesn't know openbb-fork exists.

**E0.5 — Refactor `_pynecore_glue.py` sys.path bridge.** Current bridge lives in `openbb_pine/__init__.py`'s `_install_pynecore_path()`. After E0.5:
- Move the sys.path insertion logic into `pyne_compiler/__init__.py` (soon-to-exist location) — but for E0, we stub it in a new `openbb_pine/runtime/pynecore_bridge.py` file that `_pynecore_glue.py` imports at module-load time. After E2, `pynecore_bridge.py` moves with `_pynecore_glue.py`.

**E0.6 — Refactor test files to split imports along the extraction line.** Currently ~50 test files import both `openbb_pine.stdlib`/`attribution`/`telemetry`/`routers`/`fmp_provider` (openbb-fork-side) AND compiler internals (pynecore-side). Some tests genuinely span both; those stay in openbb-fork as integration tests. Others are pure unit tests of compiler/runtime bits that only use openbb-fork imports for fixtures — those refactor to use pynecore-only imports and then move with E2.

**Verification for E0:** Full pine test suite must be green (1353 passing). No behavior change. This is a pure structural refactor.

**Estimated effort:** ~3-4 days. Each sub-refactor is bounded; can be done as 6 sequential feature-branch PRs to `openbb_pine_support` or one big PR (recommended: 6 small PRs for reviewability).

**Deliverables:** openbb-fork tree where compiler+runtime code has ZERO imports of provider/glue/telemetry/attribution code. All cross-cutting concerns are behind explicit injection points. Pre-extraction verification: `grep -r "from openbb_pine\|import openbb_pine" openbb_platform/extensions/pine/openbb_pine/compiler/ openbb_platform/extensions/pine/openbb_pine/runtime/{executor_core,security_dispatcher,secondary_cache,security_hook,strategy_types,restricted,limits,_pynecore_glue}.py` returns ZERO hits.

### Phase E1 — Design the `DataProvider` protocol + build reference adapters

**Where:** `prajoria/pynecore` on a feature branch (`feat/data-provider-protocol`).
**What:**
- Add `pynecore/adapters/base.py` (the Protocol above)
- Add `pynecore/adapters/file.py` (wraps existing `OHLCVReader`)
- Add `pynecore/adapters/csv.py` (new — reads RFC 4180 CSV)
- Add `pynecore/adapters/sqlite.py` (new — reads SQLite via stdlib `sqlite3`)
- Unit tests for each adapter (per-fixture round-trip: known input → expected output)
- Interface conformance tests (each adapter passes a shared `test_conforms_to_protocol` suite)
- Merge to pynecore `main` before starting Phase E2.

**Estimated effort:** ~4 days.

**Deliverables:** Working `DataProvider` protocol + 3 reference adapters + tests, all merged to pynecore main.

### Phase E2 — Extract compiler + core runtime via `git filter-repo`

**Where:** openbb-fork source tree → new pynecore branch (`feat/extract-openbb-pine-compiler`).
**What:**
1. In a scratch clone of `prajoria/OpenBB`, run `git filter-repo` to isolate `openbb_platform/extensions/pine/openbb_pine/` history:
   - Rewrite paths: `openbb_platform/extensions/pine/openbb_pine/compiler/` → `pyne_compiler/`
   - Rewrite paths: `openbb_platform/extensions/pine/openbb_pine/runtime/{executor,security_dispatcher,secondary_cache,security_hook,strategy_types,restricted,limits,_pynecore_glue}.py` → `pyne_compiler/runtime/*`
   - Rewrite paths: `openbb_platform/extensions/pine/openbb_pine/errors.py` + `error_codes.py` + `diagnostics.py` → `pyne_compiler/errors/*`
   - Rewrite paths: tests to `pyne_compiler/tests/`
   - Exclude paths that stay in openbb-fork: `runtime/fmp_provider.py`, `runtime/fmp_retry.py`, `runtime/byo_provider.py`, `runtime/provider_selection.py`, `routers/*`, `mcp_tools.py`, `cli/`, `assets/`, `about.py`, `attribution.py`, `pine_router.py`, `_coverage_manifest.py`
2. Verify the rewritten history: every commit's Clean-room trailer preserved, per-bead attribution intact, `git log --follow` on moved files works.
3. In `prajoria/pynecore` on a new branch, merge the rewritten history with `--allow-unrelated-histories`.
4. Resolve any path collisions manually (none expected since `pyne_compiler/` is a fresh directory).
5. Update `pynecore/pyproject.toml` to list `pyne_compiler` as a second package under the same install.
6. Open PR to pynecore main.

**Estimated effort:** ~2 days (bulk is verification, not filter-repo itself).

**Deliverables:** `prajoria/pynecore` HEAD includes `pyne_compiler/` with preserved history, tests still green under the new module paths.

### Phase E3 — Refactor openbb-fork to consume the extracted pynecore

**Where:** openbb-fork on a feature branch (`refactor/pine-consumes-pyne_compiler`).
**What:**
1. Bump `third_party/pynecore/` submodule to the post-extraction pynecore HEAD.
2. Refactor `openbb_pine/runtime/fmp_provider.py` to implement the `DataProvider` protocol (add `stream()` + `fetch()` methods that wrap existing FMP-fetch logic).
3. Refactor `openbb_pine/runtime/byo_provider.py` similarly.
4. Update all `openbb_pine/*` imports:
   - `from openbb_pine.compiler.xxx import ...` → `from pyne_compiler.xxx import ...`
   - `from openbb_pine.runtime.executor import ...` → `from pyne_compiler.runtime.executor import ...`
   - `from openbb_pine.runtime.security_dispatcher import ...` → `from pyne_compiler.runtime.security_dispatcher import ...`
   - Same for `security_hook`, `secondary_cache`, `strategy_types`, `restricted`, `limits`
   - `from openbb_pine.errors import ...` where the error is a compiler/runtime error → `from pyne_compiler.errors import ...`
5. Delete the now-empty `openbb_pine/compiler/` directory + all migrated files.
6. Update `openbb_pine/tests/` to import from new locations. Delete tests that migrated to pynecore.
7. **Update `openbb_pine/__version__` references in migrated compiler code to `pyne_compiler.__version__`.** Specifically: `codegen.py` embeds the compiler version string in every emitted script header + populates `CompiledModule.compiler_version` field. Post-extraction these must point at `pyne_compiler.__version__` (defined in `pyne_compiler/__init__.py`). Grep before-and-after: `grep -rn "openbb_pine.__version__\|openbb_pine import.*__version__" pyne_compiler/` should return zero hits after the refactor.
8. Update `openbb_pine/README.md` to reference the extracted architecture.
9. Run full test suite (openbb-fork side) — must be 100% green.
10. Open PR to `openbb_pine_support`.

**Estimated effort:** ~3 days (bulk is import-fixups; ~1 day of test-suite baby-sitting).

**Deliverables:** `openbb_pine_support` branch that consumes the extracted pynecore, tests green, no behavior change for downstream users.

### Phase E4 — Resume Phase 2 in the new location

**Where:** Both repos, per-bead.
**What:**
- Update every open Phase 2 P1 bead's DESIGN field to reference the new module paths (`pyne_compiler/` instead of `openbb_pine/compiler/`).
- Re-dispatch Wave 3 (beads `aeh`, `god`, `5k0`) against `prajoria/pynecore` instead of `prajoria/OpenBB`.
- Downstream Wave 4 (`liz`, `4d0`, `250`, conformance harness) similarly split: runtime work goes to pynecore, platform endpoints stay in openbb-fork.

**Estimated effort:** Phase 2 timeline unchanged from pre-extraction estimate — this phase is bead re-scoping, not net-new work.

## 7. Git-history preservation details (Phase E2 mechanics)

**Tool:** `git filter-repo` v2.34+ (Python-based, actively maintained; official recommended replacement for `git filter-branch`).

**Command (illustrative):**
```bash
cd /tmp/openbb-extract-scratch
git clone --no-local /path/to/openbb-fork .
git filter-repo \
  --path openbb_platform/extensions/pine/openbb_pine/compiler/ \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/executor_core.py \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/_pynecore_glue.py \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/restricted.py \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/limits.py \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/security_dispatcher.py \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/secondary_cache.py \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/security_hook.py \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/strategy_types.py \
  --path openbb_platform/extensions/pine/openbb_pine/compiler_errors.py \
  --path openbb_platform/extensions/pine/openbb_pine/error_codes.py \
  --path openbb_platform/extensions/pine/openbb_pine/diagnostics.py \
  --path openbb_platform/extensions/pine/openbb_pine/tests/ \
  --path-rename openbb_platform/extensions/pine/openbb_pine/compiler/:pyne_compiler/ \
  --path-rename openbb_platform/extensions/pine/openbb_pine/runtime/:pyne_compiler/runtime/ \
  --path-rename openbb_platform/extensions/pine/openbb_pine/compiler_errors.py:pyne_compiler/errors/base.py \
  --path-rename openbb_platform/extensions/pine/openbb_pine/error_codes.py:pyne_compiler/errors/codes.py \
  --path-rename openbb_platform/extensions/pine/openbb_pine/diagnostics.py:pyne_compiler/errors/diagnostics.py \
  --path-rename openbb_platform/extensions/pine/openbb_pine/tests/:pyne_compiler/tests/
```

**Trailer preservation:** `git filter-repo` preserves commit messages VERBATIM. The `Clean-room: I have not viewed TradingView or PyneComp source code.` trailer on every compiler-touching commit remains intact.

**Author/date preservation:** All committer and author identities and timestamps preserved.

**SHA rewriting:** Commit SHAs change (unavoidable — tree hashes change when paths change). Cross-repo references (e.g. bead descriptions that cite `68f655584`) become historical breadcrumbs — the referenced commit is findable via message search but not clickable.

**Merge into pynecore:**
```bash
cd /path/to/pynecore-clone
git checkout main
git remote add extract /tmp/openbb-extract-scratch
git fetch extract
git merge extract/master --allow-unrelated-histories --no-ff -m "Merge extracted openbb-pine compiler + core runtime into pynecore

Extraction of compiler + core runtime code originally developed in
prajoria/OpenBB (openbb_pine_support branch, commits 2f000abe3..07e8d4d9f).
Full history preserved via git filter-repo per Pine Extraction Design §7.

All migrated commits retain their original per-bead attribution and
Clean-room trailers.
"
```

## 8. Error handling + failure modes

**Where can extraction go wrong?**

| Failure mode | Detection | Recovery |
|---|---|---|
| `git filter-repo` misses a file | Test suite fails in pynecore with `ModuleNotFoundError` | Re-run filter-repo with corrected `--path` list; the rewrite is idempotent on a fresh scratch clone |
| Import fixup in openbb-fork misses a call site | Test suite fails in openbb-fork with `ModuleNotFoundError` | grep for the old import string, fix; run tests again |
| `DataProvider` protocol shape doesn't accommodate FMP's rate-limit behavior | FMP tests fail after refactor | Extend the protocol (backward-compatible: add optional methods with default no-op impls) OR wrap the rate-limit logic in the FMP adapter itself outside the protocol |
| Reference adapter (CSV/SQLite) has a bug caught only by real users later | Bug report, fix via patch release | Standard bugfix loop — the interface is stable, the impl can iterate |
| PyneCore upstream lands a breaking change that our fork needs to track | `git fetch upstream && git merge` produces conflicts | Standard fork-maintenance: resolve conflicts, verify with test suite, ship |

**Rollback plan:** If Phase E3 refactor destabilizes openbb-fork, the escape hatch is stronger than a naive read suggests — **git submodules pin by exact commit SHA**, not by branch name. Consequences:

- The extraction PR to pynecore is already merged (irreversible without a revert commit). ✅ Fine.
- Openbb-fork's `openbb_pine_support` is protected by the branch-protection hook — no direct-to-base commits. ✅ Fine.
- The refactor PR to `openbb_pine_support` can be reverted via `git revert` on that PR's merge commit. When reverted, the submodule pointer in `third_party/pynecore/` moves BACK to the pre-extraction SHA (e.g. `2919eac`), which still exists on origin/pynecore's history even after pynecore's own main has moved forward. **The old pynecore commit is not garbage-collected as long as any ref (main, tag, other branch) reaches it.**
- To make the rollback bulletproof, tag the pre-extraction pynecore HEAD as `pre-openbb-extraction-2026-07-06` BEFORE starting E2 — that guarantees the SHA remains reachable in perpetuity, immune to future force-pushes on pynecore's main.
- Openbb-fork continues consuming the OLD (pre-extraction) submodule pointer via the reverted state until the refactor is fixed and re-shipped.
- No data loss, no user-visible downtime — worst case is a few days on the pre-extraction code path.

This is a stronger guarantee than typical "revert the merge" rollbacks: because submodule pointers are content-addressed (SHAs), rolling back openbb-fork also rolls back its pynecore version atomically. The two repos stay in sync as long as the SHA is preserved.

## 9. Testing strategy

**Per phase:**

- **Phase E1 (protocol + reference adapters):** Each adapter has unit tests for round-trip fidelity, malformed input handling, and edge cases (empty range, single bar, start > end). Shared `test_conforms_to_protocol` suite verifies each adapter satisfies the `DataProvider` Protocol at both static-type-check level (via `isinstance(adapter, DataProvider)` since Protocol is `runtime_checkable`) and behavioral level (round-trip a known dataset through `stream()` vs. `fetch()` and assert byte-identical output).

- **Phase E2 (extraction):** Post-migration, run the full pine test suite from pynecore. Baseline: **1,353 passing** (matches openbb-fork's current count for the migrated subset per `pytest --collect-only -q`). Any test count change is a regression signal. Note: baseline was 1,343 in Rev 1 of this doc but 10 tests landed in Wave 2 review fixes between the doc draft and now.

- **Phase E3 (openbb-fork refactor):** Full pine test suite in openbb-fork must remain green — this is the definitive "no behavior change" gate. Additionally: run the M1 smoke test (`from openbb import obb; obb.pine.run(source, symbol="AAPL")`) end-to-end against the FMP adapter to verify the refactored `fmp_provider.py` still delivers correct bars.

- **Phase E4 (Phase 2 resumption):** Each resumed bead gets its own PR + review + fix loop per the pattern established in Wave 2 tonight. No cross-cutting test change — each bead's tests land with the bead.

**Regression guard:** Add a `pyne_compiler.tests.test_import_stability` module that asserts every public compiler entry point (`compile_pine`, `CompiledModule`, `PineError` hierarchy, etc.) can be imported at the documented module path. This catches accidental import-path breakage from future refactors.

## 10. Legal + audit considerations

- **Clean-room trailer preservation:** All ~40 compiler-touching commits in openbb-fork carry `Clean-room: I have not viewed TradingView or PyneComp source code.` Extraction preserves these verbatim via `git filter-repo`. New commits in pyne_compiler/ must continue the trailer per PRD §2.5.
- **Apache-2.0 attribution:** `pynecore/NOTICE` gets a new line naming our compiler additions. Wording (draft): *"pyne_compiler/ — clean-room Pine v5/v6 compiler contributed by Prashant Rajoria under Apache-2.0. See pyne_compiler/CLEANROOM.md for provenance."*
- **`CLEANROOM.md` in `pyne_compiler/`:** Document the clean-room process (points at PRD §2 in openbb-fork). Not legally required but useful for future auditors.
- **Counsel signoff (bead 0e9.4.1):** The 2026-07-04 approval was scoped to "openbb-fork ships an extension using vendored PyneCore." This extraction changes that architecture. Recommended action: file a follow-up bead requesting counsel confirmation that the extraction preserves the Clean-room posture. Not blocking for extraction, but worth doing before pynecore's first published release.
- **License compatibility:** Everything stays Apache-2.0. No mixing, no dual-licensing, no CLAs required.

## 11. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `git filter-repo` command has a wrong path spec, produces partial history | Medium | High (would need re-run + re-review) | Do it in a scratch clone first; verify with `git log --follow` on 5+ representative files before pushing to pynecore. |
| Refactor breaks a subtle FMP-provider behavior not covered by unit tests | Medium | Medium | Run the M1 smoke test end-to-end against real FMP before landing the openbb-fork refactor PR. |
| Wave 3 subagents work in the OLD location while extraction is in flight | Medium | Low-Medium | Freeze Phase 2 via `bd update <id> --status blocked` on all open P1 sub-beads until extraction lands. |
| PyneCore upstream lands a change that conflicts with our fork during extraction window | Low | Low | Freeze upstream fetches until extraction is complete. Estimated extraction window: ~2 weeks. |
| A subtle circular import emerges (compiler needs runtime types, runtime needs compiler errors) | Medium | Low | Fix inline as import failures surface during Phase E3 — the extraction is a chance to enforce cleaner boundaries. |
| Bead references (in `bd`) become stale (referencing openbb-fork paths after extraction) | High | Low | Bulk-update all Phase 2 bead DESIGN fields as part of Phase E4 kickoff. |
| Documentation (`docs/designs/openbb-pine/D1-D5.md`) still references old paths | High | Low | Cross-reference cleanup as part of Phase E4. |

## 12. Success criteria

Extraction is complete when:

1. `prajoria/pynecore` main HEAD contains `pyne_compiler/` with full preserved history (spot-check 5 commits' trailers + author + date).
2. `prajoria/pynecore` main HEAD contains `pynecore/adapters/{base,csv,sqlite,file}.py` with tests green.
3. `openbb_pine_support` HEAD in openbb-fork consumes the extracted pynecore via updated submodule; full pine test suite green (baseline 1,353 passing preserved).
4. `obb.pine.run(source, symbol="AAPL", provider="fmp")` produces byte-identical output vs. pre-extraction baseline (verified by re-running M1 smoke test).
5. All open Phase 2 P1 sub-beads have updated DESIGN fields pointing at `pyne_compiler/*` module paths, ready for Wave 3 resumption.
6. `bd remember pine-extraction-completed "extracted YYYY-MM-DD; pynecore HEAD <sha>; openbb-fork HEAD <sha>"` captures the transition point.

## 13. Open questions (deferred to implementation planning)

**Resolved in rev 2:**
- ~~Should `pyne_compiler/` be a distinct Python package with its own version, or a subpackage of `pynecore` (i.e. `pynecore.compiler`)?~~ **RESOLVED — distinct top-level `pyne_compiler`**. Rationale: (a) clean provenance boundary (visible at directory level), (b) `pyne_compiler.__version__` can advance independently of `pynecore.__version__` (compiler bugfixes shouldn't force a runtime version bump), (c) `import pyne_compiler` reads as intent-revealing vs. `import pynecore.compiler` which sounds like an internal upstream module.

**Still deferred to implementation planning:**
- **Do we need a `pynecore-adapters` extras group** (`pip install pynecore[csv]` / `pip install pynecore[sqlite]`) or ship all adapters unconditionally? Design assumes all shipped (stdlib deps only — no optional external packages).
- **Should the extraction PR to pynecore be one giant merge commit, or should we cherry-pick commits in per-bead groups?** Design assumes one merge via `--allow-unrelated-histories` for simplicity; per-bead grouping is an option if the extracted history is too dense to review.
- **The `Signature.kwargs` slot vs. h14's trailing-tuple-kwargs inconsistency (flagged in Wave 2 h14 review):** This normalization is a good candidate for the first Phase 4 cleanup PR in pynecore after extraction lands.

---

**Approval sought:** User review of this document before proceeding to a written implementation plan.
