# Pine Extraction to prajoria/pynecore — Design

**Author:** Prashant Rajoria (with Claude Code)
**Date:** 2026-07-06 (revision 3 — 2026-07-06 evening)
**Status:** Draft for review — REVISED (Rev 3) to address PR #328 external editorial + subagent re-review findings
**Branch:** `design/pine-extraction-to-pynecore`
**Related:** openbb-pine Phase 2 epic `OpenBBTechnical-0e9.6` (paused for this extraction); tracking bead `OpenBBTechnical-rbf`; h14-normalization follow-up bead `OpenBBTechnical-qj7`

> **Post-extraction note (2026-07-10, E4.1 / bd-8j9):** The E3 epic has landed
> (`openbb_pine_support` at `0dff38fa3`). All forward-looking compiler/runtime
> module paths in this spec are `pyne_compiler.*` (e.g. `pyne_compiler.compiler.*`,
> `pyne_compiler.errors.*`, `pyne_compiler.telemetry`,
> `pyne_compiler.runtime.executor_core`, `pyne_compiler.runtime.pynecore_bridge`).
> Remaining `openbb_pine.compiler.*` / `openbb_pine.runtime.executor` / `openbb_pine.telemetry`
> references below are **narrative or historical** — they describe the
> pre-extraction state, the E0→E3 migration steps (before→after imports), or the
> §13.5 PEP 562 deprecation shims (which by definition cite the old paths).
> Those legacy import paths remain accessible via the deprecation shims until
> v0.next+1 per §13.5.

## Revision history

- **Rev 1** (2026-07-06 morning): Initial design after 7-question brainstorm. Committed at `0025d8149`, opened as PR #328.
- **Rev 2** (2026-07-06 afternoon): Addresses 5 BLOCK + 4 GAP + 2 QUESTION + 3 NIT findings from PR #328 subagent initial review. Key structural changes:
  - Added new **Phase E0 (pre-extraction refactor)** to §6 — splits `errors.py` into compiler/provider halves, refactors `security_dispatcher`/`executor` to consume abstract interfaces, abstracts `telemetry` behind an injection point. All done INSIDE openbb-fork so post-extraction tree has zero dangling imports.
  - Updated §4 topology to reflect the E0 refactor outcome.
  - Updated §5 with `DataProvider` construction vs. call parameterization clarification.
  - Updated §9 to replace `@runtime_checkable` conformance check with behavioral suite.
  - Updated §6.E3 to add `openbb_pine.__version__` → `pyne_compiler.__version__` transition.
  - Updated §9 test baseline: 1353 (was: 1343 — stale after Wave 2 review fixes).
  - Resolved §13 open question about top-level vs. subpackage: **top-level `pyne_compiler`** (documented in §4 — CORRECTED in Rev 3, see below).
  - Multiple cross-reference + line-count fixups.
- **Rev 3** (2026-07-06 evening): Addresses the external editorial review (§14 R1–R10, §15 open-question feedback) and the subagent Rev-2 re-review (23 comments on commit `ad2a971b3`). Substantive changes:
  - **R1 (BLOCK) — `src/` layout**: pynecore uses `src/pynecore/` layout per its `pyproject.toml` (`package-dir = { "pynecore" = "src/pynecore" }`, `packages.find = { where = ["src"] }`). §4 topology and every `--path-rename` in §7 now target `src/pynecore/…` and `src/pyne_compiler/…`. Files at the old top-level targets would sit outside setuptools' discovery root and never install.
  - **R2 (BLOCK) — Unify with existing `Provider` base class, do not introduce a parallel `DataProvider` protocol**: pynecore already ships `src/pynecore/providers/{provider.py,ccxt.py,capitalcom.py}`. `Provider` (abstract base, construction-parameterized, `__enter__`/`__exit__` around an `OHLCVWriter`) is the authoritative interface. §5 rewritten: we EXTEND `Provider` with two new concrete methods — `stream(sym, tf, *, start, end)` and `fetch(sym, tf, *, start, end)` — whose default implementations use `download_ohlcv()` + `load_ohlcv_data()` (write-then-read through `.ohlcv` file). Subclasses can override for direct-query optimizations (e.g., FMP fetches from REST directly, no file intermediate). No new `adapters/` directory; reference CSV/SQLite implementations live in `src/pynecore/providers/{csv,sqlite}.py` alongside existing `ccxt.py` and `capitalcom.py`. Kills the `Provider` vs. `DataProvider` naming collision and the parallel `SymbolInfo` protocol (existing `SymInfo` / `get_symbol_info` are authoritative).
  - **R3 (GAP) — Partial history for E0-split files**: `executor_core.py`, `compiler_errors.py`, `pynecore_bridge.py` don't exist yet; E0 creates them. Their history in pynecore therefore starts at the E0 commit; earlier lineage stays in openbb-fork under `executor.py` / `errors.py` / `__init__.py`. Explicitly documented in §7 and §12; §12's "spot-check 5 commits" now requires at least one E0-split file so the truncated-lineage behavior is signed off knowingly.
  - **R4 (BLOCK-ish contradiction) — §9 vs. §5.2**: §5.2 correctly rejects `@runtime_checkable isinstance` as real conformance. §9 was contradicting itself by saying conformance was verified via that isinstance check. Deleted the isinstance sentence. After R2, conformance is inheritance from the `Provider` base class (`isinstance(x, Provider)` IS meaningful for ABCMeta subclasses — but real conformance is the behavioral test suite in §5.2, not that check).
  - **R5 (GAP) — Conformance over-constrains live providers**: Scoped `stream()` vs. `fetch()` byte-equivalence to **closed historical ranges** — live/paginated providers (FMP realtime) may include forming bars in stream but not fetch. Also changed `start > end` from "must raise" to "returns `[]`" for consistency with check #3 (empty range → empty list) and natural SQL semantics.
  - **R6 (GAP) — Python floor mismatch**: pynecore requires `>=3.11`; openbb-fork advertises 3.10–3.13. Post-extraction, `pyne_compiler` inherits pynecore's `>=3.11` floor. Documented in a new subsection under §4 with implications for downstream users on Python 3.10.
  - **R7 (GAP) — Independent versioning compatibility contract**: Clarified that "independent versioning" means independent `__version__` STRINGS, not independently installable wheels — both packages ship from ONE distribution (`pynesys-pynecore`) so they can't actually version-skew at install time. Documented in §13.1 and §4.
  - **R8 (NIT) — Line-count precision**: Direct `wc -l` on 2026-07-06 evening: `errors.py`=1082 LOC, `error_codes.py`=444, `diagnostics.py`=385, sum=1911. The Rev 2 numbers (1911 sum) were correct; the Rev 2 E0.1 sub-line "1050 LOC with 20+ classes" was wrong (actual is 1082). Numbers throughout §4 and §6.E0.1 updated to match direct measurement; approximate figures now labelled with "~".
  - **R9 (NIT) — Freeze/unfreeze coordination**: Formalized as (a) a tracking bead (already exists: `bd remember pine-phase2-frozen-for-extraction`), (b) an explicit unfreeze checklist added to §12 success criteria so E4 resumption can't silently miss a bead.
  - **R10 (NIT) — NOTICE/CLEANROOM.md placement under `src/`**: Called out in §10: `CLEANROOM.md` under `src/pyne_compiler/` needs `package-data`/`MANIFEST.in` config to ship in the wheel; alternative is to place it at repo root (like `NOTICE`).
  - **Subagent BLOCK #4 (test split criterion)**: Made concrete in §6.E0.6 — a test moves to pynecore iff its imports are ALL either (a) pynecore-side (compiler/runtime/errors) OR (b) fixtures/stdlib. Tests importing openbb-fork-side modules (routers/attribution/mcp/fmp_provider/byo_provider/telemetry) stay in openbb-fork as integration tests.
  - **Subagent BLOCK #5 (errors.py ambiguous classes)**: Assigned explicitly in §6.E0.1 — `PineDataResolverError` MOVES (runtime concern, raised by user callback wrapper); `PineDataValidationError` STAYS (provider-boundary schema validation); `PineSecurityContextNotFoundError` MOVES (raised by security_hook).
  - **Subagent GAP #8 (pynecore_bridge.py underspecified)**: Spelled out in §6.E0.5. Post-E2 the bridge is absorbed into `src/pyne_compiler/__init__.py` (or deleted entirely if `pip install -e src/pynecore` and `pip install -e src/pyne_compiler` both live-install the packages). §4 topology updated to show the file.
  - **New GAP (E0 verification grep-gate)**: §6.E0 verification now includes an explicit grep-gate command: `grep -rE "from openbb_pine\.(attribution|telemetry|routers|mcp_tools|_coverage_manifest|cli)\.|from openbb_pine\.runtime\.(fmp_provider|byo_provider|fmp_retry|provider_selection)" <migrated-files>` must return zero hits. This is the definition of E0 done — green tests are necessary but not sufficient.
  - **New GAP (E0 inter-dependencies)**: §6.E0 now documents the ordering: E0.1 (errors split) FIRST; E0.2 (dispatcher) and E0.3 (executor) depend on E0.1; E0.4 (telemetry) and E0.5 (pynecore_bridge) are independent (can parallelize); E0.6 (test refactor) depends on E0.1 + E0.2 + E0.3 + E0.4.
  - **New NIT (E0.2 stub-Protocol trick concrete filename)**: §6.E0.2 now names the temporary in-repo file (`openbb_pine/runtime/_data_provider_stub.py`) and specifies the E2 deletion step. After R2 this stub is even simpler — a temporary ABC that gets replaced by the real `Provider` base at E2 import-fixup time.
  - **New QUESTION (E0 effort estimate)**: Bumped from ~3–4 days to **5–7 days**, matching the reviewer's per-sub-refactor sum.
  - **§13.1 resolution text**: Amended per R7 wording — "distinct import package `pyne_compiler` living at `src/pyne_compiler/`, shipped from the same `pynesys-pynecore` distribution, carrying its own `__version__` string and a documented `pynecore` runtime-version floor."
  - **§13.2 (adapters extras group) LOCKED**: Ship CSV/SQLite unconditionally (stdlib deps). Reserve `optional-dependencies` for future providers with non-stdlib deps (mysql needs a driver, postgres needs psycopg). Rule: "stdlib-only providers ship in core; any provider needing a non-stdlib dep goes behind an extra named after the backing store." Moved from "open" to "resolved".
  - **§13.3 (merge strategy) LOCKED**: Single `--allow-unrelated-histories` merge — cherry-picking across unrelated histories loses the merge base, error-prone at ~11k LOC, gains nothing. Reviewability comes from (a) this design doc, (b) preserved `git log --follow`/blame, (c) the green 1,353-test gate — NOT small PR diff. Added a "how to review an extraction PR" note. Moved from "open" to "resolved".
  - **§13.4 (h14 normalization) — bead filed**: Filed as `OpenBBTechnical-qj7`, linked as `tracks` `OpenBBTechnical-rbf`. Survives freeze/unfreeze churn.
  - **NEW §13.5 (deprecation shim)**: Documented decision: given "no behavior change for downstream users" (§3), ship a one-release re-export shim in `openbb_pine/compiler/` and `openbb_pine/runtime/` that re-exports the moved names from `pyne_compiler.*` (with a `DeprecationWarning`). Removes the shim in the next minor release. This gives external notebooks/`Analysis/`/doc examples one release to migrate.

---

## 1. Context

The `openbb-extension-pine` code (11,541 LOC across `openbb_platform/extensions/pine/openbb_pine/`) implements a clean-room Pine Script v6/v5 compiler + runtime for the OpenBB Platform. It currently vendors PyneCore via `third_party/pynecore/` (submodule → `prajoria/pynecore`, a fork of PyneSys upstream) and layers our compiler + provider-routing + REST/MCP surfaces on top.

Two forces motivate a restructure:

1. **Pine work is architecturally distinct from OpenBB.** The compiler, type checker, code generator, and Pine-runtime plumbing have no dependency on OpenBB's provider/router machinery — they'd be equally valuable to any project that wants to run Pine scripts. Bundling them inside `openbb_platform/extensions/pine/` conflates two concerns.
2. **The data-source model needs to open up.** PyneCore today reads only from `.ohlcv` binary files, but the existing `Provider` base class (in `src/pynecore/providers/provider.py`) already frames the download-and-persist pattern for external data sources (CCXT, Capital.com). Real-world Pine consumers need MySQL, Postgres, SQLite, CSV, HTTP APIs, and streaming feeds. Extending the existing `Provider` base with `stream()`/`fetch()` methods (rather than introducing a parallel `DataProvider` protocol) preserves the download-time contract while adding runtime-read semantics. See §5 for the full API design.

The user has approved the following architectural pivot: **extract the Pine compiler + core runtime to `prajoria/pynecore` as a sibling package `src/pyne_compiler/`, extend the existing `Provider` base class with runtime-read methods, keep OpenBB-specific glue (FMP provider, REST routers, MCP tools, CLI) in openbb-fork, and consume the extracted work via the existing git-submodule + editable-install pattern.**

Six architectural decisions have been made through brainstorming (2026-07-06 session):

| # | Decision | Rationale |
|---|---|---|
| 1 | **Thin core with reference providers** (Option B) — Rev 3: unified with existing `Provider` base | pynecore ships an EXTENDED `Provider` base class (adds `stream()` + `fetch()` methods with default `download_ohlcv()` + `load_ohlcv_data()` implementations) plus reference `CSVProvider`/`SQLiteProvider`; project-specific providers (FMP for OpenBB) stay in the consuming project. No parallel `DataProvider` Protocol — see §5. |
| 2 | **Sync query-based API** (Option B) | `stream(sym, tf, start, end) -> Iterator[OHLCV]` + `fetch(sym, tf, start, end) -> list[OHLCV]`. Aligns with `request.security()` semantics; doesn't force async refactor. Added as concrete methods on `Provider` (not a separate Protocol). |
| 3 | **Sibling packages** in one repo (Option B) | `src/pynecore/` (runtime, upstream) + `src/pyne_compiler/` (our clean-room compiler) — directory-level provenance boundary, single Apache-2.0 license, single distribution (`pynesys-pynecore`). |
| 4 | **Extract first, resume Phase 2 in new home** (Option A) | Freeze 17 open Phase 2 P1 sub-beads; resume against `pyne_compiler.*` module paths after extraction. Avoids double-write of the same code. |
| 5 | **Full history preservation via `git filter-repo`** (Option B) | Preserves per-bead attribution + Clean-room trailers + `git blame`. One-time complexity for permanent audit value. E0-split files carry lineage only from the E0 commit forward (see §7 for details). |
| 6 | **Git submodule + editable install** (Option A) | Same pattern in use today. PyPI publishing deferred as separate future decision. |
| 7 | **Extract compiler + core runtime only** (Option B, this doc's operating assumption) | FMP + REST + MCP + CLI stay in openbb-fork; refactor FMP in place to extend the unified `Provider` base. Least physical file movement. |

## 2. Goals

**In scope:**
- Move `compiler/` (6,840 LOC), core `runtime/` plumbing (subset of 3,484 LOC), the `errors.py` compiler/runtime errors, and the Pine-runtime-facing tests (subset of 17,211 LOC of tests) from `openbb_platform/extensions/pine/openbb_pine/` to `prajoria/pynecore` as a new `src/pyne_compiler/` sibling package (sibling to `src/pynecore/`).
- **Extend** the existing `pynecore.providers.Provider` base class (in `src/pynecore/providers/provider.py`) with two new concrete methods — `stream(sym, tf, *, start, end)` and `fetch(sym, tf, *, start, end)` — whose default implementations use `download_ohlcv()` + `load_ohlcv_data()` (write-then-read through `.ohlcv` file). Add two new reference concrete providers (`src/pynecore/providers/csv.py`, `src/pynecore/providers/sqlite.py`). NO new parallel `DataProvider` Protocol; NO new `adapters/` directory. (See §5 for the full rationale.)
- Refactor `openbb_platform/extensions/pine/openbb_pine/runtime/fmp_provider.py` to inherit from `Provider` and override `stream`/`fetch` for direct REST-query optimization (kept in openbb-fork).
- Preserve full git history via `git filter-repo` — every commit's Clean-room trailer + per-bead attribution + `git blame` continue to work in the new location. (Caveat: files created by E0 — `executor_core.py`, `compiler_errors.py`, `pynecore_bridge.py` — carry lineage from the E0 commit forward, not from before; documented in §7.)
- Bump the `third_party/pynecore/` submodule in openbb-fork to point at the post-extraction pynecore HEAD; verify `pip install -e third_party/pynecore` still gives a working dev environment.
- Full pine test suite (currently 1,353 passing per `pytest --collect-only`) stays green across both repos after extraction.

**Out of scope for this design (future decisions):**
- PyPI publishing of pynecore — deferred until there's a concrete external consumer.
- Async data providers — sync-only for now; async wrappers can be added later as a non-breaking extension.
- Streaming/websocket providers — the sync `stream()` method supports polling patterns; websocket-native support is a future enhancement.
- Migration of the M2 conformance harness / conformance corpus — those move with the compiler as part of the mechanical extraction, no design change.
- Whether `pyne_compiler/` also owns bundled Pine indicators/strategies (widgets.json) — those are OpenBB-Workspace-specific glue and stay in openbb-fork.

## 3. Non-goals / explicit exclusions

- **No behavior change** for existing `obb.pine.*` REST/MCP consumers. `obb.pine.run(source, symbol="AAPL", provider="fmp")` must produce byte-identical output before and after extraction (verified by full test suite).
- **No new legal review required for extraction itself** — the counsel signoff on PRD §2 (bead `0e9.4.1`, closed 2026-07-04) covers the Clean-room posture, which continues in the new location. If the extraction changes the FMP adapter's shape materially, that's a separate reviewable diff, not a legal concern.
- **No `develop` branch changes.** Everything lands via feature branches to `openbb_pine_support` (openbb-fork) and to `main` (pynecore, per its own conventions). Bulk merges to `develop` remain manual and human-driven per branch protection policy.
- **No PyneCore upstream contribution** — this is an extraction into a fork. Upstream `PyneSys/pynecore` remains a separate maintenance path.

## 4. Post-extraction repo topology

**Layout note:** pynecore's `pyproject.toml` declares `[tool.setuptools] package-dir = { "pynecore" = "src/pynecore" }` and `packages.find = { where = ["src"] }`. All Python packages MUST live under `src/` or setuptools will silently skip them at install time. This is a hard constraint on the extraction targets.

```
prajoria/pynecore  (fork, Apache-2.0)
├── src/                              # setuptools discovery root (packages.find where=["src"])
│   ├── pynecore/                     # From PyneSys upstream — runtime, Pine builtins, ScriptRunner
│   │   ├── core/
│   │   ├── lib/
│   │   ├── types/
│   │   └── providers/                # EXISTING today (upstream) — ccxt.py, capitalcom.py, provider.py
│   │       ├── __init__.py
│   │       ├── provider.py           # Provider base class — EXTENDED (Rev 3) with new stream()/fetch() concrete methods
│   │       ├── ccxt.py               # Existing CCXT provider (upstream, unchanged)
│   │       ├── capitalcom.py         # Existing Capital.com provider (upstream, unchanged)
│   │       ├── csv.py                # NEW (Phase E1) — reference CSV provider (stdlib deps)
│   │       └── sqlite.py             # NEW (Phase E1) — reference SQLite provider (stdlib deps)
│   └── pyne_compiler/                # NEW — our clean-room Pine v5/v6 compiler + core runtime
│       ├── __init__.py               # Owns pyne_compiler.__version__; absorbs the sys.path bridge from openbb_pine (Rev 3)
│       ├── lexer.py                  # Was: openbb_pine/compiler/lexer.py
│       ├── parser.py                 # Was: openbb_pine/compiler/parser.py
│       ├── type_checker.py           # Was: openbb_pine/compiler/type_checker.py
│       ├── codegen.py                # Was: openbb_pine/compiler/codegen.py
│       ├── compile_cache.py          # Was: openbb_pine/compiler/compile_cache.py
│       ├── v5_migration.py           # Was: openbb_pine/compiler/v5_migration.py
│       ├── ir.py, types.py, ...      # Was: openbb_pine/compiler/*.py
│       ├── grammar/*.lark            # Was: openbb_pine/compiler/grammar/
│       ├── builtin_signatures.py     # Was: openbb_pine/compiler/builtin_signatures.py
│       ├── telemetry.py              # NEW (E0.4) — TelemetrySink protocol; small in-process counter module (~90 LOC, no OpenBB deps)
│       ├── errors/                   # Compiler + runtime error package
│       │   ├── __init__.py           # Re-exports the PineError hierarchy
│       │   ├── base.py               # PineError base + compiler/runtime subclasses (from openbb_pine/compiler_errors.py — E0.1 split)
│       │   ├── codes.py              # Error code catalog (from openbb_pine/error_codes.py)
│       │   └── diagnostics.py        # Diagnostic + telemetry glue (from openbb_pine/diagnostics.py)
│       └── runtime/                  # Pine runtime plumbing that's not OpenBB-specific
│           ├── executor_core.py      # ScriptRunner adapter (from post-E0.3 openbb_pine/runtime/executor_core.py)
│           ├── pynecore_bridge.py    # sys.path bridge for submodule-vendored deployments; from E0.5, absorbed at E2 into pyne_compiler/__init__.py or kept as an explicit helper (see §6.E0.5)
│           ├── _pynecore_glue.py     # Kept as-is
│           ├── restricted.py         # Restricted-exec namespace
│           ├── limits.py             # Exec limits (timeout, RLIMIT_AS, bar cap)
│           ├── security_dispatcher.py # prefetch_security_contexts (bead c1x)
│           ├── secondary_cache.py    # SecondarySeriesCache
│           ├── security_hook.py     # install_secondaries_hook (bead n6j)
│           └── strategy_types.py     # TradeSummary + OpenPositionSummary (bead wxz)
├── tests/                            # OR nested under src/pyne_compiler/tests/ — see §6.E2 for layout choice
│   ├── unit/                         # Migrated compiler + core-runtime unit tests
│   └── conformance/                  # Conformance harness + Pine-fixture pairs
├── LICENSE                           # Apache-2.0 (from PyneSys)
├── NOTICE                            # Attribution: PyneCore upstream + our compiler additions
├── CLEANROOM.md                      # NEW (Rev 3) — provenance doc placed at repo root so it always ships in the sdist (not just wheel package-data)
└── pyproject.toml                    # Declares BOTH pynecore and pyne_compiler; `packages.find = { where = ["src"] }` picks up both

prajoria/OpenBB  (openbb-fork, on openbb_pine_support)
├── openbb_platform/extensions/pine/
│   └── openbb_pine/
│       ├── __init__.py              # obb.pine facade; loses _install_pynecore_path() bridge after E3 (bridge moves to pyne_compiler)
│       ├── pine_router.py           # about() endpoint
│       ├── routers/                 # /pine/run, /pine/run_byo, /pine/indicators/list, /pine/strategies/*, /pine/health, /pine/builtins/coverage
│       │   ├── run_router.py
│       │   ├── strategies_router.py
│       │   ├── catalog_router.py
│       │   ├── health_router.py
│       │   ├── compile_router.py    # Rev 3: swap `openbb_pine.__version__` → `pyne_compiler.__version__` (E3 step 7) so cache-key hash matches pynecore-side
│       │   └── _models.py           # Shared Pydantic request/response models
│       ├── mcp_tools.py             # MCP tool registrations
│       ├── cli/                     # openbb pine doctor CLI
│       ├── about.py                 # PineAbout model
│       ├── attribution.py           # §4(d) attribution strings
│       ├── telemetry.py             # STAYS — implementation of pyne_compiler.telemetry.TelemetrySink protocol; injected by routers into compile_pine(telemetry=...)
│       ├── compiler/                # Rev 3: E3 does NOT delete outright — retained as deprecation SHIM (one release) re-exporting from pyne_compiler.* with DeprecationWarning
│       ├── runtime/                 # OpenBB-specific runtime glue
│       │   ├── fmp_provider.py      # FMP provider (Rev 3: refactored to inherit pynecore.providers.Provider and override stream/fetch for direct REST optimization)
│       │   ├── fmp_retry.py         # Shared retry budget for FMP
│       │   ├── byo_provider.py      # BYODataProvider (Rev 3: refactored to inherit pynecore.providers.Provider — may raise on symbol/tf mismatch vs. construction-time)
│       │   ├── executor_shell.py    # Post-E0.3 — thin FMP/BYO/attribution wrapper delegating to pyne_compiler.runtime.executor_core.run_compiled()
│       │   ├── executor.py          # Rev 3: E3 does NOT delete outright — retained as deprecation SHIM
│       │   └── provider_selection.py # Provider precedence + non-FMP fast-fail
│       ├── assets/widgets.json      # Bundled OpenBB Workspace widgets (Bollinger etc.)
│       ├── _coverage_manifest.py    # OpenBB-side coverage attribution
│       ├── errors.py                # Provider-side errors ONLY, post-E0.1 split (PineProviderError, FMP subclasses, PineDataValidationError). Compiler+runtime errors moved to pyne_compiler.errors.
│       └── tests/                   # Only OpenBB-integration + FMP + provider-selection + stdlib bridge tests remain (see §6.E0.6 for the concrete split rule)
└── third_party/pynecore/            # Submodule → prajoria/pynecore (post-extraction HEAD)
```

**Line-count expectations after extraction (direct `wc -l` measurement on 2026-07-06 evening):**
- `pyne_compiler/` in pynecore: **~11,400 LOC** (compiler 6,840 + core runtime subset ~2,660 + errors/codes/diagnostics 1,911 — exact: `errors.py` 1082 + `error_codes.py` 444 + `diagnostics.py` 385 = 1,911)
- `openbb_pine/` remaining in openbb-fork: **~3,000 LOC** (routers 1,217 + FMP/BYO/retry/selection 821 + mcp/router/about/attribution/telemetry/coverage/__init__ 838 + CLI 119)
- Test migration: majority of the current 17,211 test LOC moves with the compiler+runtime. Exact split determined during E0.6 refactor via the concrete criterion in §6.E0.6. Baseline: **1,353 tests must stay green in whichever repo they land in.**

Approximate numbers ("~") reflect that some files (executor.py in particular) split rather than move wholesale; the LOC distribution across the boundary depends on how E0.3 draws the shell/core line. Rev 1 of this doc estimated ~9,500 + ~4,000 LOC — corrected in Rev 2 after direct measurement, corrected again in Rev 3 to use direct `wc -l` numbers rather than approximate splits.

### 4.1 Python version floor (added in Rev 3, addresses R6)

pynecore requires `requires-python = ">=3.11"`. openbb-fork's project docs advertise 3.10–3.13 support. Once `pyne_compiler` lives under pynecore's `pyproject.toml`, its supported floor is **`>=3.11`** — inherited from the host distribution. Implications:

- **Verify compiler already uses ≥3.11 features.** Spot-check for `match/case`, PEP 604 union syntax (`int | str`), `Self` type, `Never` type, `assert_type`, TypedDict generic parameters. If any of these are present, 3.10 support in openbb-fork was already nominal (compiler wouldn't have worked on 3.10 anyway). If not, note it and decide whether to keep the ≥3.11 floor or backport.
- **Downstream openbb-fork users on Python 3.10 lose access to Pine features** post-extraction. openbb-fork should update its own `pyproject.toml` to drop 3.10 (or scope it: "Pine features require Python ≥3.11").
- **Runtime version pin:** `pyne_compiler` implicitly requires `pynecore>=X` (where X is the pynecore version at extraction time) because both ship from the same distribution. No install-time skew possible; version compat is enforced by co-distribution, not by requirements pins. See §13.1 for the full compatibility rule.

### 4.2 Distribution + version compatibility contract (added in Rev 3, addresses R7)

Both `pynecore` and `pyne_compiler` are import packages that ship from a single distribution named `pynesys-pynecore`. Consequences:

- **A single `pip install pynesys-pynecore` installs BOTH packages.** They cannot version-skew at install time — the wheel either contains both or neither.
- **"Independent versioning" means independent `__version__` STRINGS**, not independently installable wheels. `pyne_compiler.__version__` may advance without bumping `pynecore.__version__` (and vice versa) so the compile-cache key and emitted `@pyne` docstrings reflect compiler changes without forcing a runtime version bump on downstream users. But there is only ever one distribution version.
- **If a future decision splits distributions** (e.g. `pip install pynecore` and `pip install pyne_compiler` become two separate installs), that is a re-architecture — the doc should be updated at that time, not now. Current design: one distribution, two `__version__` strings.
- **`pyne_compiler` implicitly pins `pynecore>=<distribution-version-at-extraction>`** via co-distribution. Cross-import (`from pynecore.types.ohlcv import OHLCV`) is safe because the two packages ship together.

## 5. Extending the existing `Provider` base class (Rev 3: replaces the Rev 2 `DataProvider` Protocol design)

### 5.0 Why unify with `Provider` instead of introducing a new Protocol

Rev 2 of this doc proposed a new `pynecore.adapters.DataProvider` runtime-checkable Protocol living in a new `adapters/` package alongside `core/lib/types`. External editorial review (§14 R2) pointed out this ignored the fact that pynecore already ships a full data-source abstraction: `src/pynecore/providers/` with `provider.py` (`class Provider(metaclass=ABCMeta)`), `ccxt.py`, and `capitalcom.py`.

Concretely, the existing `Provider`:

- Is **construction-parameterized**: `__init__(symbol, timeframe, ohlv_dir, config_dir)` locks a specific target.
- Is a **context manager** wrapping an `OHLCVWriter` (`__enter__`/`__exit__` open/close the file).
- Uses a **download-to-`.ohlcv`-file** model via the abstract `download_ohlcv()` method, then reads via `load_ohlcv_data() -> OHLCVReader`.
- Is coupled to `SymInfo` / `get_symbol_info()` for symbol metadata.
- Loads config from `providers.toml`.

Introducing a parallel `DataProvider` Protocol would have created:

- **A naming collision of concepts** — `Provider` (download-first, file-backed) vs. `DataProvider` (call-parameterized, in-memory). New contributors couldn't tell which to implement, and the docs would need to explain "both, they mean different things."
- **A duplicate metadata surface** — the proposed `SymbolInfo.symbol_info()` protocol overlapped with the existing `SymInfo` / `get_symbol_info()`.
- **A missed reuse opportunity** — the `FileAdapter` from Rev 2 wrapped `OHLCVReader`, which the existing `Provider` already knows about natively.

**Rev 3 decision:** Extend the existing `Provider` base class with two new concrete methods — `stream()` and `fetch()` — whose default implementations use the existing `download_ohlcv()` + `load_ohlcv_data()` flow. Subclasses may override for direct-query optimization. No new Protocol; no new `adapters/` directory; no parallel `SymbolInfo` type.

### 5.1 The extended `Provider` API

The new methods added to `pynecore.providers.provider.Provider`:

```python
# Additions to src/pynecore/providers/provider.py

from typing import Iterator
from datetime import datetime

class Provider(metaclass=ABCMeta):
    # ... existing fields, __init__, download_ohlcv, load_ohlcv_data, etc. ...

    def stream(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Iterator[OHLCV]:
        """Yield OHLCV bars in chronological order for (symbol, timeframe).

        Default implementation: write-then-read through the existing
        download_ohlcv() + load_ohlcv_data() flow. Subclasses MAY override
        for direct-query optimization (e.g. FMP's REST endpoint returns
        bars directly, skipping the file intermediate).

        Both ``start`` and ``end`` are inclusive when provided; ``None``
        means "from the beginning" or "to the end" respectively. Timestamps
        in yielded OHLCV records MUST be in UTC and monotonically
        non-decreasing.

        For closed historical ranges, ``list(stream(...))`` MUST equal
        ``fetch(...)``. For live/paginated ranges (e.g. an end date past
        the last closed bar) the two methods MAY differ — stream() may
        include a forming bar that fetch() excludes. See §5.2 conformance.
        """
        # Default implementation (subclasses may override):
        # 1. Optionally: ensure the on-disk .ohlcv file covers [start, end]
        #    by calling self.download_ohlcv(start, end) if it doesn't.
        # 2. Open self.load_ohlcv_data() and iterate, filtering to
        #    [start, end] and to matching (symbol, timeframe) if the
        #    subclass allows multi-symbol reads.
        # Concrete pseudo-code left to E1 implementation; the shape of
        # the default is "read from the .ohlcv file created by
        # download_ohlcv()", which preserves backward compat for existing
        # subclasses (ccxt.py, capitalcom.py) that only ever wrote files.

    def fetch(
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[OHLCV]:
        """Return a bar range as a materialized list.

        Default implementation: ``list(self.stream(symbol, timeframe,
        start=start, end=end))``. Subclasses MAY override to issue a
        single batched query (e.g. one SQL SELECT instead of iterating
        cursor rows).

        Returned bars follow the same ordering + UTC guarantees as
        stream().
        """
        return list(self.stream(symbol, timeframe, start=start, end=end))
```

**Backward compatibility:** Existing `ccxt.py` and `capitalcom.py` subclasses inherit the default `stream()`/`fetch()` implementations for free — they already implement `download_ohlcv()` and inherit `load_ohlcv_data()`. No changes required to existing pynecore code.

**Conformance model:** `isinstance(x, Provider)` IS meaningful because `Provider` is an ABCMeta subclass — subclasses that don't implement the abstract methods (`to_tradingview_timeframe`, `to_exchange_timeframe`, `get_list_of_symbols`, `update_symbol_info`, `get_opening_hours_and_sessions`, `download_ohlcv`) cannot be instantiated. Real *behavioral* conformance is still the §5.2 test suite; `isinstance` catches "did you forget to inherit at all" but not "did you implement `stream()` correctly."

### 5.2 Construction vs. call parameterization (refined in Rev 3)

Rev 2 framed this as a rewrite from construction-parameterized (`FMPOHLCVProvider(request=FMPRequest(...))`) to call-parameterized (`provider.stream(symbol, timeframe, ...)`). Rev 3 refines: since `stream()`/`fetch()` are added as METHODS on the existing `Provider` (which is already construction-parameterized with `symbol`/`timeframe`), providers now have **two** natural usage modes:

1. **Instance-scoped mode (existing pattern):** `Provider(symbol="AAPL", timeframe="1D", …)`; then `provider.stream(symbol="AAPL", timeframe="1D", …)` where the call-time symbol/timeframe MUST match the construction-time values. If they don't match, the provider MAY raise `ValueError`. This is the correct mode for BYO providers (whose backing DataFrame is bound to one symbol at construction time) and for legacy CCXT/Capital.com uses.

2. **Multi-target mode (new for FMP-like providers):** `Provider()` or `Provider(api_key=…)` with no symbol/timeframe at construction; then `provider.stream("AAPL", "1D", …)` + `provider.stream("MSFT", "1D", …)` on the same instance. Requires the subclass to override `stream()`/`fetch()` (the default file-backed implementation assumes a single symbol/timeframe target via `ohlcv_path`). This is the correct mode for `security_dispatcher`'s pattern of fetching many secondary symbols from one provider.

The `FMPOHLCVProvider` refactor in E3 puts it in mode 2: construction takes only configuration (api_key, cache_dir, base_url), and `stream()`/`fetch()` handle arbitrary (symbol, timeframe) pairs. The `BYODataProvider` stays in mode 1: construction takes the DataFrame + symbol/timeframe; `stream("MSFT", "1D")` raises if construction-time symbol was "AAPL".

**State ownership:** Under mode 2, `bars_consumed` and retry-budget context are per-call, not per-instance. If a caller needs cumulative accounting across calls, the caller (not the provider) tracks it. The `security_dispatcher` refactor (E0.2) is the primary caller and is responsible for its own accounting.

### 5.3 Reference providers shipped in `src/pynecore/providers/`

| Provider | Backing store | Use case | Ships in core? |
|---|---|---|---|
| `Provider` (base) | Abstract | Base class — extended by all others | Core (unchanged) |
| `CCXTProvider` (existing) | CCXT exchanges | Crypto data via CCXT | Extra: `pynesys-pynecore[ccxt]` (unchanged) |
| `CapitalComProvider` (existing) | Capital.com REST | Capital.com data | Extra: `pynesys-pynecore[capitalcom]` (unchanged) |
| `CSVProvider` (NEW, Phase E1) | CSV files (RFC 4180) with `timestamp,open,high,low,close,volume` columns | Local backtests, tutorials | Core (stdlib deps only) |
| `SQLiteProvider` (NEW, Phase E1) | SQLite database with configurable table schema | Local persistence, embedded distributions | Core (stdlib deps only) |

The rule (see §13.2): **stdlib-only providers ship in core; any provider needing a non-stdlib dependency goes behind an extra named after the backing store.**

**Consuming-project providers (stay in their host projects):**

| Provider | Location | Backing store |
|---|---|---|
| `FMPOHLCVProvider` | openbb-fork `openbb_pine/runtime/fmp_provider.py` | Financial Modeling Prep REST API (with fmp_cached tier support) — extends `pynecore.providers.Provider`, overrides `stream`/`fetch` for direct REST |
| `BYODataProvider` | openbb-fork `openbb_pine/runtime/byo_provider.py` | User-supplied `list[dict]` records (REST BYO endpoint) — extends `pynecore.providers.Provider`, mode-1 usage |
| Future: `MySQLProvider`, `PostgresProvider`, etc. | Wherever their consumers live | Their respective backing stores |

### 5.4 Conformance testing (Rev 3 update, addresses R4 and R5)

Conformance is verified by a **behavioral test suite** shared across all provider implementations. `isinstance(x, Provider)` catches "did you inherit at all" but NOT signature errors (Python ABCMeta only enforces method-name presence on `@abstractmethod`, not signature shapes) and NOT semantic errors. The behavioral suite is the real gate.

`src/pynecore/providers/tests/test_conformance.py` ships a shared suite that every provider must pass:

```python
# src/pynecore/providers/tests/test_conformance.py
import pytest
from datetime import datetime, timezone

def _conformance_suite(provider: "Provider", *, closed_only: bool):
    """Behavioral checks every Provider's stream()/fetch() must satisfy.

    Called by provider-specific test modules with a fixture-configured
    provider instance and a corpus of known bars.

    :param closed_only: When True, the fixture guarantees the range is
        entirely closed (no forming bar). Live providers (FMP realtime)
        must call with closed_only=True for check #1; call with
        closed_only=False to skip that check.
    """
    # 1. stream() and fetch() return equivalent data for CLOSED historical
    #    ranges. Live/paginated providers may include a forming bar in
    #    stream() but not fetch(); check only when the fixture guarantees
    #    closed ranges. (Rev 3 refinement — Rev 2 required byte-equivalence
    #    unconditionally, which over-constrained live providers.)
    if closed_only:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 10, tzinfo=timezone.utc)
        streamed = list(provider.stream("TESTSYM", "1D", start=start, end=end))
        fetched = provider.fetch("TESTSYM", "1D", start=start, end=end)
        assert streamed == fetched, "stream() and fetch() must return identical bars for closed ranges"

    # 2. Timestamps monotonically non-decreasing
    fetched = provider.fetch("TESTSYM", "1D",
                              start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                              end=datetime(2024, 1, 10, tzinfo=timezone.utc))
    timestamps = [bar.timestamp for bar in fetched]
    assert timestamps == sorted(timestamps), "bars must be chronological"

    # 3. Empty range returns empty list, not error
    empty = provider.fetch("TESTSYM", "1D",
                           start=datetime(2020, 1, 1, tzinfo=timezone.utc),
                           end=datetime(2020, 1, 2, tzinfo=timezone.utc))
    assert empty == [], "unknown range must return [] cleanly"

    # 4. start > end returns [] (natural SQL/SELECT semantics; consistent
    #    with check #3). Rev 3 change: Rev 2 required a raise, which
    #    forced every subclass to add a guard. [] is simpler and consistent.
    reversed_range = provider.fetch("TESTSYM", "1D",
                                     start=datetime(2024, 1, 10, tzinfo=timezone.utc),
                                     end=datetime(2024, 1, 1, tzinfo=timezone.utc))
    assert reversed_range == [], "start > end must return [] (not raise)"

    # 5. Missing symbol raises typed error
    with pytest.raises((KeyError, LookupError, ValueError)):
        provider.fetch("NEVER_EXISTS_XYZ", "1D",
                       start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                       end=datetime(2024, 1, 10, tzinfo=timezone.utc))

    # 6. UTC-timezone enforcement (added in Rev 3 per subagent GAP #7 feedback)
    for bar in fetched:
        # Accept both timezone-aware UTC and epoch-seconds representations.
        # Reject naive datetimes and non-UTC timezones.
        if hasattr(bar.timestamp, 'tzinfo'):
            assert bar.timestamp.tzinfo == timezone.utc, "timestamps must be UTC"

    # 7. Stateless-across-calls (added in Rev 3 per subagent GAP #7 feedback):
    #    calling fetch() twice with the same args returns identical results.
    #    Enforces the "providers MUST NOT hold cursor state between calls" rule.
    a = provider.fetch("TESTSYM", "1D",
                       start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                       end=datetime(2024, 1, 10, tzinfo=timezone.utc))
    b = provider.fetch("TESTSYM", "1D",
                       start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                       end=datetime(2024, 1, 10, tzinfo=timezone.utc))
    assert a == b, "fetch() must be stateless (repeated calls yield identical results)"
```

Each concrete provider (`test_csv.py`, `test_sqlite.py`, and downstream `test_fmp_provider.py` in openbb-fork) instantiates itself with a fixture dataset and calls `_conformance_suite(self.provider, closed_only=...)`. Signature-mismatched implementations fail at TEST time, not at production call time.

For live/paginated providers (FMP realtime), the fixture harness pins a historical range (e.g. bars from a month ago) where the closed-only guarantee holds, then passes `closed_only=True`. If the harness cannot pin a closed range, it passes `closed_only=False` and check #1 is skipped — the other 6 checks still apply.

## 6. The migration process (five phases — was four; E0 added in rev 2, expanded in rev 3)

### Phase E0 — Pre-extraction refactor (INSIDE openbb-fork, before any file moves)

**Where:** openbb-fork on a feature branch (`refactor/pine-pre-extraction-decoupling`).

**Why:** PR #328 review (rev 1) surfaced that compiler + core-runtime files as-shipped have ~15 cross-cutting imports of code that stays in openbb-fork (FMP provider, BYO provider, telemetry, attribution, provider-side errors). Extracting them as-is produces dangling imports in pynecore. The clean fix is to refactor the boundary IN PLACE first, so the pre-extraction openbb-fork tree already has the "compiler+runtime-only" and "provider+glue" halves cleanly separable. Once E0 lands, E2's `git filter-repo` can safely move the compiler+runtime half with zero dangling imports.

**Dependency graph among E0 sub-refactors (added in Rev 3):**

```
E0.1 (errors split) ────────┬─→ E0.2 (dispatcher refactor)
                            ├─→ E0.3 (executor split)
                            └─→ E0.6 (test refactor)

E0.4 (telemetry injection) ─→ E0.6 (test refactor)   [test_error_model.py uses openbb_pine.telemetry]

E0.5 (pynecore_bridge)  ────  (independent)

E0.6 depends on: E0.1, E0.2, E0.3, E0.4 all landing.
E0.2 and E0.3 can proceed in parallel after E0.1.
E0.4 and E0.5 are independent — can run in parallel with anything.
```

Recommended landing order: **E0.1 → (E0.2 ‖ E0.3 ‖ E0.4 ‖ E0.5) → E0.6**.

**What (six sub-refactors, each is its own commit / possibly its own PR):**

**E0.1 — Split `errors.py` into two files.** Current `errors.py` is 1082 LOC (direct `wc -l` measurement on 2026-07-06) with 20+ classes mixing compiler errors (`PineSyntaxError`, `PineTypeError`, `PineCodegenError`, etc.) and provider-side errors (`PineFMPRequiredError`, `PineFMPUnreachableError`, `PineProviderError`). After E0.1:

- `openbb_pine/errors.py` — provider-side errors ONLY. **STAY list** (per Rev 3 explicit assignment):
  - `PineProviderError` (base for provider-side errors)
  - `PineFMPRequiredError`, `PineFMPUnreachableError` (FMP-specific)
  - `PineDataValidationError` (provider-boundary schema validation — raised when input data fails validation at the provider boundary; provider concern)
  - Any future provider-side errors added by consumers
- `openbb_pine/compiler_errors.py` — compiler + runtime errors that will move to pynecore. **MOVE list** (per Rev 3 explicit assignment):
  - `PineError` (base for compiler+runtime errors)
  - `Diagnostic` (dataclass shared by all compiler errors)
  - `PineCompileError`, `PineSyntaxError`, `PineTypeError`, `PineUnsupportedBuiltinError`, `PineUnsupportedFeatureError`, `PineCodegenError`, `PineInternalCompilerError`, `PineCacheError` (all compiler concerns)
  - `PineRuntimeError`, `PineStrategyNotYetImplementedError`, `PineSecurityError`, `PineExecTimeoutError` (all runtime concerns; live in pyne_compiler.runtime.*)
  - `PineDataResolverError` — **MOVES** (Rev 3 explicit assignment). Raised by `security_dispatcher.py` runtime code when a user-supplied `data_resolver` callback fails. This is a runtime concern despite being triggered by user code. openbb-fork routers that catch it will need to import from `pyne_compiler.errors` post-extraction, or the shim (§13.5) will re-export it.
  - `PineSecurityContextNotFoundError` — **MOVES** (Rev 3 explicit assignment). Raised by `security_hook.install_secondaries_hook` when a requested (symbol, timeframe) is not in the prefetched context dict. Purely runtime concern.
- `openbb_pine/compiler_errors.py` becomes what gets renamed to `pyne_compiler/errors/base.py` in E2.
- Every existing import site of `errors.py` gets updated to the correct new import path.

**E0.2 — Refactor `security_dispatcher.py` to take a `Provider` base, not `FMPOHLCVProvider` directly.** The dispatcher currently does `from openbb_pine.runtime.fmp_provider import FMPOHLCVProvider, FMPRequest, infer_asset_class`. That coupling is the exact thing the extraction is meant to break. After E0.2:

- Dispatcher's `prefetch_security_contexts()` accepts a `provider` argument typed as the future `Provider` base class (per Rev 3 unification decision — see §5).
- FMP-specific concepts (`FMPRequest`, `infer_asset_class`, `call_with_retry` from `fmp_retry`) get pushed UP to the caller (either `executor_shell.py` or the router that instantiates the dispatcher). Post-E0.2, `fmp_retry` lives entirely on the caller-side of the abstraction.
- **Temporary in-repo stub for E0** (per Rev 3 concrete-filename note): before E1 has landed the real extended `Provider` base in pynecore, we cannot import it from openbb-fork. Solution: create a small stub file `openbb_pine/runtime/_data_provider_stub.py` containing a minimal ABC (post-Rev-3 unification: a thin ABC with `stream(symbol, tf, *, start, end)` and `fetch(symbol, tf, *, start, end)` abstract methods — this matches the shape the real `Provider` base will expose after E1). The dispatcher imports from this stub for E0 → E2. At E2 import-fixup time, the stub file is DELETED and imports rewrite to `from pynecore.providers import Provider`. Grep-gate for E2: `find openbb_pine/runtime -name '_data_provider_stub.py'` returns nothing after E2.
- After the refactor, dispatcher only depends on the abstract `Provider` interface + `SecurityContext` + `SecondarySeriesCache` — all of which are on the move side of the boundary.

**E0.3 — Refactor `executor.py` similarly.** Current `executor.py` directly imports `FMPOHLCVProvider`, `BYODataProvider`, `POWERED_BY_FULL`, and provider errors. After E0.3:

- `executor.py` splits into two pieces:
  - `pyne_compiler/runtime/executor_core.py` (moves) — the compile-cache lookup, `_pynecore_glue` wiring, `_bar_iter` loop, per-bar snapshot capture, `OBBject.results` build. Takes a `Provider` instance as input. No knowledge of FMP, BYO, or attribution.
  - `openbb_pine/runtime/executor_shell.py` (stays) — the thin wrapper that instantiates the concrete provider (FMP-cached / FMP / BYO), attaches attribution (`POWERED_BY_FULL`), populates OpenBB-specific `.extra` fields, and delegates to `executor_core.run_compiled()`.
- Routers (`run_router.py`, `strategies_router.py`) call `executor_shell` instead of `executor`. Behavior is byte-identical.
- **Rev 3 shim note:** the old `openbb_pine/runtime/executor.py` file is NOT deleted at E3 — it is retained as a one-release deprecation shim that re-exports the public names from their new locations with a `DeprecationWarning`. See §13.5.

**E0.4 — Abstract telemetry behind an injection point.** Compiler imports `openbb_pine.telemetry` in 9 sites (`codegen.py`, `type_checker.py`, `v5_migration.py`, `compiler/__init__.py`). After E0.4:
- `pyne_compiler.telemetry` (created as a new module in E0.4, migrates in E2) defines a `TelemetrySink` protocol with 2 methods: `record_unsupported_feature(name)` and `record_unsupported_builtin(name)`. Small counter-only module (~90 LOC, no OpenBB deps).
- Compiler's `compile_pine()` takes an optional `telemetry: TelemetrySink | None = None` kwarg. Compiler code paths do `if telemetry: telemetry.record_unsupported_feature(...)` instead of `from openbb_pine.telemetry import ...`.
- `openbb_pine.telemetry` becomes an implementation of `TelemetrySink` that stays in openbb-fork. Openbb-fork's routers instantiate it and pass it to `compile_pine(telemetry=OpenBBTelemetrySink())`.
- Zero cross-repo import; compiler doesn't know openbb-fork exists.

**E0.5 — Refactor `_pynecore_glue.py` sys.path bridge.** Current bridge lives in `openbb_pine/__init__.py`'s `_install_pynecore_path()`, which prepends `third_party/pynecore/src` to `sys.path` so `_pynecore_glue.py`'s lazy `from pynecore...` imports resolve when running against the submodule-vendored deployment (rather than a pip-installed pynecore).

After E0.5, and clarified per Rev 3 subagent GAP #8 feedback:

- **When the bridge fires:** ONLY when `pyne_compiler` is used against a checkout of `pynecore` that isn't yet pip-installed (i.e. the submodule-vendored deployment openbb-fork uses today). If both `pynecore` and `pyne_compiler` are pip-installed (the happy path once both live in the same distribution), the bridge is a no-op — pip has already put them on `sys.path` via the pyproject.
- **E0 (in openbb-fork):** create `openbb_pine/runtime/pynecore_bridge.py` containing the sys.path-insertion logic (moved from `openbb_pine/__init__.py`'s `_install_pynecore_path()`). `_pynecore_glue.py` gets a top-of-file `from openbb_pine.runtime import pynecore_bridge  # noqa: F401` (intra-package import; safe for E0 since both files are in openbb-fork).
- **E2 (during filter-repo):** `pynecore_bridge.py` moves with `_pynecore_glue.py` to `src/pyne_compiler/runtime/pynecore_bridge.py`.
- **E3 (openbb-fork import fixup):** the `openbb_pine/__init__.py` `_install_pynecore_path()` call is REPLACED by an import of `pyne_compiler` (which triggers `pyne_compiler/__init__.py` — and that file conditionally calls the bridge if pynecore isn't yet on `sys.path`). Effectively the bridge moves ownership from openbb-fork to pyne_compiler.
- **Alternative (simpler):** if experimentation during E2 shows both packages are always pip-installed together in every real deployment (submodule + `pip install -e third_party/pynecore` in openbb-fork's own bootstrap), the bridge becomes dead code and is DELETED at E2 instead of moved. Decide at E2 implementation time based on measured install behavior. The design allows either.

**E0.6 — Refactor test files to split imports along the extraction line.** Currently ~77 test files in `openbb_pine/tests/unit/` mix imports across the extraction boundary. Rev 3 provides a **concrete decision rule** (was: sketched-only in Rev 2):

> **A test file moves to pynecore iff all its non-stdlib imports are either (a) pynecore-side modules (`pyne_compiler.*`, `pynecore.*`) OR (b) stdlib/test fixtures (pytest, hypothesis, unittest.mock, tempfile, pathlib). Any test importing an openbb-fork-side module (`openbb_pine.stdlib.*`, `openbb_pine.attribution`, `openbb_pine.telemetry` [but see below], `openbb_pine.routers.*`, `openbb_pine.mcp_tools`, `openbb_pine.runtime.fmp_provider`, `openbb_pine.runtime.byo_provider`, `openbb_pine.runtime.fmp_retry`, `openbb_pine.runtime.provider_selection`, `openbb_pine._coverage_manifest`, `openbb_pine.cli`, `openbb_pine._load_bundled_widgets`, or the OpenBB extension entrypoint) STAYS in openbb-fork as an integration test.**

Special cases (Rev 3 clarifications):

- `test_error_model.py` (imports `openbb_pine.telemetry` at 8 sites): after E0.4, the telemetry import is replaced by the injected `TelemetrySink` protocol, so this test's non-stdlib imports become pynecore-only → it **MOVES**.
- `test_executor.py` (imports `openbb_pine.attribution` + `runtime.fmp_provider`): after E0.3, this test SPLITS into `test_executor_shell.py` (STAYS — tests the shell + attribution + FMP wiring) and a new `test_executor_core.py` (MOVES — tests the pure compile-cache/glue/bar-iter loop).
- `test_stdlib_math_*.py` (7 files) + `test_stdlib_ta_*.py` (28 files): these test the `openbb_pine.stdlib` bridges directly → **STAY** (stdlib itself stays in openbb-fork; per §7 it's not in the migration path).
- `test_widgets.py`, `test_about.py`, `test_attribution_surfaces.py`, `test_prefetch_security.py`, `test_extension_loads.py`, `test_routers_*.py` (5 files), `test_router_command_bare_obbject.py`, `test_no_side_effects.py`, `test_mcp_tools.py`, `test_cli_main.py`, `test_fmp_provider.py`, `test_fmp_retry.py`, `test_byo_provider.py`, `test_provider_selection.py`: ALL **STAY** by the rule above.
- Compiler-internal tests (`test_lexer.py`, `test_parser.py`, `test_type_checker.py`, `test_codegen.py`, `test_compile_cache.py`, `test_v5_migration.py`, `test_ir.py`, conformance harness tests, etc.): **MOVE** (their only openbb-side imports are for fixtures, which the E0 refactor already decouples).

**E0 verification (Rev 3 update — verification is now a hard grep-gate, not just tests-green):**

The E0 completion criterion is BOTH of:

1. **Full pine test suite green (1353 passing).** Necessary for functional correctness.
2. **Zero cross-boundary imports.** The following grep MUST return zero hits, run as a pre-merge gate (add to CI or `.pre-commit-config.yaml`):

   ```bash
   # After E0.1-E0.6 land, this MUST return zero hits:
   grep -rE "from openbb_pine\.(attribution|telemetry|routers|mcp_tools|_coverage_manifest|cli)\.|from openbb_pine\.runtime\.(fmp_provider|byo_provider|fmp_retry|provider_selection)" \
     openbb_platform/extensions/pine/openbb_pine/compiler/ \
     openbb_platform/extensions/pine/openbb_pine/runtime/{executor_core,security_dispatcher,secondary_cache,security_hook,strategy_types,restricted,limits,_pynecore_glue,pynecore_bridge}.py \
     openbb_platform/extensions/pine/openbb_pine/compiler_errors.py
   ```

   Tests passing WITHOUT this grep gate would be misleading: coupling could still be present but latent (e.g. a helper function that grabs from `openbb_pine.attribution` but happens not to be exercised by the current tests). The grep is the definition of "E0 is done."

**Estimated effort:** **5–7 days** (was: ~3–4 days in Rev 2 — reviewer noted the per-sub-refactor sum is 5–7 days; Rev 3 accepts the reviewer's estimate). Breakdown:
- E0.1 (errors split + 20+ import sites): ~1 day
- E0.2 (dispatcher refactor + stub file): ~1 day
- E0.3 (executor split into shell/core + rewire routers): ~1.5 days
- E0.4 (telemetry injection wiring + 9 call sites): ~1 day
- E0.5 (pynecore_bridge move): ~0.5 day
- E0.6 (test file audit + splitting + moves): ~1–2 days

Recommended: 6 sequential feature-branch PRs to `openbb_pine_support` (per the dependency graph above) for reviewability.

**Deliverables:** openbb-fork tree where compiler+runtime code has ZERO imports of provider/glue/telemetry/attribution code. All cross-cutting concerns are behind explicit injection points. Grep gate passes.

### Phase E1 — Extend the `Provider` base class + build reference concrete providers

**Where:** `prajoria/pynecore` on a feature branch (`feat/provider-stream-fetch`).
**What (Rev 3 — was: "Design the `DataProvider` protocol + build reference adapters"):**
- Extend `src/pynecore/providers/provider.py`: add concrete `stream()` and `fetch()` methods to the `Provider` base class with default implementations backed by `download_ohlcv()` + `load_ohlcv_data()`. (See §5.1 for the API.)
- Add `src/pynecore/providers/csv.py` (new — reads RFC 4180 CSV with `timestamp,open,high,low,close,volume` columns).
- Add `src/pynecore/providers/sqlite.py` (new — reads SQLite via stdlib `sqlite3` with configurable table schema).
- Unit tests for each concrete provider (per-fixture round-trip: known input → expected output).
- Shared behavioral conformance suite (`src/pynecore/providers/tests/test_conformance.py` — see §5.4) that every subclass runs against its own fixture data.
- Verify existing `ccxt.py` and `capitalcom.py` STILL pass their existing tests — they inherit the new default `stream()`/`fetch()` for free and must not regress.
- Verify `pip install -e .` on the pynecore repo installs BOTH `pynecore` AND `pyne_compiler` (the latter is empty until E2 lands its files, but the package directory must be discoverable by setuptools' `packages.find = { where = ["src"] }`). Fix `pyproject.toml` if needed.
- Merge to pynecore `main` before starting Phase E2.

**Estimated effort:** ~4 days.

**Deliverables:** Extended `Provider` base class + 2 new reference concrete providers + tests, all merged to pynecore main. Existing `ccxt.py`/`capitalcom.py` unchanged and still green.

### Phase E2 — Extract compiler + core runtime via `git filter-repo`

**Where:** openbb-fork source tree → new pynecore branch (`feat/extract-openbb-pine-compiler`).
**What:**
1. In a scratch clone of `prajoria/OpenBB`, run `git filter-repo` to isolate `openbb_platform/extensions/pine/openbb_pine/` history (see §7 for the concrete command; Rev 3 uses `src/`-prefixed rename targets).
2. Verify the rewritten history: every commit's Clean-room trailer preserved, per-bead attribution intact, `git log --follow` on moved files works. **Rev 3 addition:** deliberately include at least one E0-split file (`executor_core.py`, `compiler_errors.py`, or `pynecore_bridge.py`) in the spot-check so the reviewer understands the file's history only reaches back to its E0 creation commit, not further (§7 and §12).
3. In `prajoria/pynecore` on a new branch, merge the rewritten history with `--allow-unrelated-histories` (per §13.3 lock).
4. Resolve any path collisions manually (none expected since `src/pyne_compiler/` is a fresh directory).
5. Update `pynecore/pyproject.toml` — because it already uses `packages.find = { where = ["src"] }`, the new `src/pyne_compiler/` package is picked up automatically once its `__init__.py` exists. Verify: `pip install -e .` on the post-extraction repo installs BOTH `pynecore` AND `pyne_compiler` as importable packages. **Rev 3 verification step (was implicit in Rev 2):** `python -c "import pynecore, pyne_compiler; print(pynecore.__version__, pyne_compiler.__version__)"` must succeed.
6. **DELETE the temporary stub file** `openbb_pine/runtime/_data_provider_stub.py` (created in E0.2) — its role is now filled by the real `pynecore.providers.Provider` base class. Rewrite the dispatcher's import from `from openbb_pine.runtime._data_provider_stub import DataProviderStub` to `from pynecore.providers import Provider`. (Note: since dispatcher itself moves in E2, this rewrite happens as part of the filter-repo path renames.)
7. Open PR to pynecore main.

**Estimated effort:** ~2 days (bulk is verification, not filter-repo itself).

**Deliverables:** `prajoria/pynecore` HEAD includes `src/pyne_compiler/` with preserved history (with the E0-split-file lineage caveat noted in §7 and §12), tests still green under the new module paths.

### Phase E3 — Refactor openbb-fork to consume the extracted pynecore

**Where:** openbb-fork on a feature branch (`refactor/pine-consumes-pyne_compiler`).
**What:**
1. Bump `third_party/pynecore/` submodule to the post-extraction pynecore HEAD.
2. Refactor `openbb_pine/runtime/fmp_provider.py` to inherit from `pynecore.providers.Provider` and override `stream()`/`fetch()` for direct REST-query optimization (see §5.2 mode 2). Construction takes only configuration (api_key, cache_dir, base_url); symbol/timeframe move to method parameters.
3. Refactor `openbb_pine/runtime/byo_provider.py` to inherit from `pynecore.providers.Provider` in mode 1 (construction-scoped to a single symbol/timeframe; `stream()` for a different (symbol, timeframe) raises `ValueError`).
4. Update all `openbb_pine/*` imports:
   - `from openbb_pine.compiler.xxx import ...` → `from pyne_compiler.xxx import ...`
   - `from openbb_pine.runtime.executor import ...` → `from pyne_compiler.runtime.executor_core import ...` (via `executor_shell` for the shell/attribution wrapping)
   - `from openbb_pine.runtime.security_dispatcher import ...` → `from pyne_compiler.runtime.security_dispatcher import ...`
   - Same for `security_hook`, `secondary_cache`, `strategy_types`, `restricted`, `limits`
   - `from openbb_pine.errors import ...` where the error is a compiler/runtime error → `from pyne_compiler.errors import ...`
5. **Rev 3 update:** the now-obsolete `openbb_pine/compiler/` directory + migrated files under `openbb_pine/runtime/` are NOT deleted outright. Instead, they become **one-release deprecation shims** (per §13.5): each old-path module re-exports the public names from the corresponding new-path location and emits a `DeprecationWarning` at import time. Shims live for one release; the next minor bump removes them entirely. This gives external notebooks / `Analysis/` / doc examples a migration window.
6. Update `openbb_pine/tests/` to import from new locations. Delete tests that migrated to pynecore (per the E0.6 split rule).
7. **Update `openbb_pine.__version__` references in migrated compiler code AND remaining openbb-fork call sites to `pyne_compiler.__version__`.** Specifically:
   - `codegen.py` embeds the compiler version string in every emitted script header + populates `CompiledModule.compiler_version` field. Post-extraction these must point at `pyne_compiler.__version__` (defined in `pyne_compiler/__init__.py`).
   - **Rev 3 addition** (per subagent GAP #9 caveat): `openbb_pine/routers/compile_router.py` also does `from openbb_pine import __version__ as _pine_version` and passes it into the compile-cache-key hash + `PineCompileResponse(compiler_version=...)`. Post-extraction this MUST use `pyne_compiler.__version__` so the router's cache-key hash matches the on-disk cache key that pynecore computes. If they diverge, every compile becomes a miss.
   - Grep before-and-after: `grep -rn "openbb_pine.__version__\|openbb_pine import.*__version__" pyne_compiler/ openbb_platform/extensions/pine/openbb_pine/` should return zero hits after the refactor (the routers/compile_router.py case is the one the Rev 2 grep pattern missed).
8. Update `openbb_pine/README.md` to reference the extracted architecture.
9. Run full test suite (openbb-fork side) — must be 100% green.
10. Open PR to `openbb_pine_support`.

**Estimated effort:** ~3 days (bulk is import-fixups; ~1 day of test-suite baby-sitting; deprecation-shim boilerplate is ~2 hours).

**Deliverables:** `openbb_pine_support` branch that consumes the extracted pynecore, tests green, no behavior change for downstream users. Deprecation shims installed for one release.

### Phase E4 — Resume Phase 2 in the new location

**Where:** Both repos, per-bead.
**What:**
- Update every open Phase 2 P1 bead's DESIGN field to reference the new module paths (`pyne_compiler/` instead of `openbb_pine/compiler/`).
- Re-dispatch Wave 3 (beads `aeh`, `god`, `5k0`) against `prajoria/pynecore` instead of `prajoria/OpenBB`.
- Downstream Wave 4 (`liz`, `4d0`, `250`, conformance harness) similarly split: runtime work goes to pynecore, platform endpoints stay in openbb-fork.

**Estimated effort:** Phase 2 timeline unchanged from pre-extraction estimate — this phase is bead re-scoping, not net-new work.

## 7. Git-history preservation details (Phase E2 mechanics)

**Tool:** `git filter-repo` v2.34+ (Python-based, actively maintained; official recommended replacement for `git filter-branch`).

**Command (illustrative, Rev 3 — all `--path-rename` targets are now `src/`-prefixed per R1):**
```bash
cd /tmp/openbb-extract-scratch
git clone --no-local /path/to/openbb-fork .
git filter-repo \
  --path openbb_platform/extensions/pine/openbb_pine/compiler/ \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/executor_core.py \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/_pynecore_glue.py \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/pynecore_bridge.py \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/restricted.py \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/limits.py \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/security_dispatcher.py \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/secondary_cache.py \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/security_hook.py \
  --path openbb_platform/extensions/pine/openbb_pine/runtime/strategy_types.py \
  --path openbb_platform/extensions/pine/openbb_pine/compiler_errors.py \
  --path openbb_platform/extensions/pine/openbb_pine/error_codes.py \
  --path openbb_platform/extensions/pine/openbb_pine/diagnostics.py \
  --path openbb_platform/extensions/pine/openbb_pine/telemetry.py \
  --path <curated-list-of-migrating-test-files-per-E0.6-rule> \
  --path-rename openbb_platform/extensions/pine/openbb_pine/compiler/:src/pyne_compiler/ \
  --path-rename openbb_platform/extensions/pine/openbb_pine/runtime/:src/pyne_compiler/runtime/ \
  --path-rename openbb_platform/extensions/pine/openbb_pine/compiler_errors.py:src/pyne_compiler/errors/base.py \
  --path-rename openbb_platform/extensions/pine/openbb_pine/error_codes.py:src/pyne_compiler/errors/codes.py \
  --path-rename openbb_platform/extensions/pine/openbb_pine/diagnostics.py:src/pyne_compiler/errors/diagnostics.py \
  --path-rename openbb_platform/extensions/pine/openbb_pine/telemetry.py:src/pyne_compiler/telemetry.py \
  --path-rename openbb_platform/extensions/pine/openbb_pine/tests/:src/pyne_compiler/tests/
```

**Rev 3 correctness note:** every `--path-rename` target is `src/`-prefixed. Rev 2's targets (`pyne_compiler/...`) would have placed files OUTSIDE pynecore's `packages.find = { where = ["src"] }` discovery root, so setuptools would silently skip them at install time. `import pyne_compiler` would then fail at runtime everywhere.

**Note on tests migration:** the `--path openbb_platform/extensions/pine/openbb_pine/tests/` line above is a placeholder. Rev 3 replaces the Rev 2 blanket `--path tests/` + `--path-rename tests/:src/pyne_compiler/tests/` with a **curated per-file list** generated by the E0.6 decision rule (§6.E0.6). The blanket rename in Rev 2 would have moved ~50 tests into pynecore that import openbb-fork-side modules and would fail at collection time. The curated list moves ONLY compiler+runtime-internal tests.

**Note on telemetry.py:** the `openbb_pine/telemetry.py` file itself DOES migrate to `src/pyne_compiler/telemetry.py` — but only in its post-E0.4 form (the `TelemetrySink` protocol + counters). The openbb-fork-side implementation of the protocol (which is what routers wire up) is a NEW file created in E0.4 also named `openbb_pine/telemetry.py` and remains in openbb-fork. So the file name is reused; the pre-E0.4 file content moves under `pyne_compiler/`, and a fresh file of the same name is created in openbb-fork.

**Trailer preservation:** `git filter-repo` preserves commit messages VERBATIM. The `Clean-room: I have not viewed TradingView or PyneComp source code.` trailer on every compiler-touching commit remains intact.

**Author/date preservation:** All committer and author identities and timestamps preserved.

**SHA rewriting:** Commit SHAs change (unavoidable — tree hashes change when paths change). Cross-repo references (e.g. bead descriptions that cite `68f655584`) become historical breadcrumbs — the referenced commit is findable via message search but not clickable.

### 7.1 Partial history for E0-split files (Rev 3, addresses R3)

The following files DO NOT EXIST YET — they are created by Phase E0:

- `openbb_pine/compiler_errors.py` (created by E0.1)
- `openbb_pine/runtime/executor_core.py` (created by E0.3)
- `openbb_pine/runtime/pynecore_bridge.py` (created by E0.5)

Because `git filter-repo` rewrites the ENTIRE history and the pre-E0 logic lived in `errors.py` / `executor.py` / `__init__.py` — files which are EXCLUDED from the migration by design (they carry openbb-fork-side content) — the migrated `executor_core.py`, `compiler_errors.py`, and `pynecore_bridge.py` in pynecore will carry history **only from the E0 creation commit forward**. Their earlier lineage stays in openbb-fork under the original files.

Consequences:

- `git log --follow src/pyne_compiler/runtime/executor_core.py` in pynecore shows commits from the E0.3 commit onwards, NOT the ~40 pre-E0 commits that touched `executor.py`.
- `git blame` on lines within `executor_core.py` correctly attributes lines TO their E0.3-and-later authors. Lines that moved WHOLESALE from the old `executor.py` at E0.3 will show the E0.3 refactor commit as their "last touched" — not the original author who wrote them in bead `f8x` (or wherever). To find the ORIGINAL author, cross-reference via commit-message search in openbb-fork's history.
- The Clean-room trailer on the E0.3 commit itself IS preserved and does cover the moved lines from openbb-fork's `executor.py` (which itself had Clean-room trailers on every commit).

**This is acceptable** — the alternative (rewriting `errors.py`/`executor.py` in-place then trying to split them mid-filter-repo) is significantly more complex and error-prone. The trade-off is: perfect blame lineage for wholesale-moved files (all of `compiler/`) vs. E0-commit-forward lineage for the E0-split files. The design accepts this trade-off knowingly.

Section 12's success criteria requires the "spot-check 5 commits" verification to include AT LEAST ONE E0-split file so the reviewer sees and signs off on the truncated-lineage behavior explicitly.

### 7.2 Merge into pynecore

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

Files created by Phase E0 (executor_core.py, compiler_errors.py,
pynecore_bridge.py, telemetry.py) carry history from their E0 creation
commit forward only, per §7.1.
"
```

## 8. Error handling + failure modes

**Where can extraction go wrong?**

| Failure mode | Detection | Recovery |
|---|---|---|
| `git filter-repo` misses a file | Test suite fails in pynecore with `ModuleNotFoundError` | Re-run filter-repo with corrected `--path` list; the rewrite is idempotent on a fresh scratch clone |
| Import fixup in openbb-fork misses a call site | Test suite fails in openbb-fork with `ModuleNotFoundError` | grep for the old import string, fix; run tests again |
| Extended `Provider` base doesn't accommodate FMP's rate-limit behavior | FMP tests fail after refactor | Extend the `Provider` base class (backward-compatible: add optional methods with default no-op impls) OR wrap the rate-limit logic in the FMP provider subclass itself outside the base class contract |
| Reference provider (CSV/SQLite) has a bug caught only by real users later | Bug report, fix via patch release | Standard bugfix loop — the base-class interface is stable, the impl can iterate |
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

- **Phase E1 (extended `Provider` base + reference providers):** Each concrete provider has unit tests for round-trip fidelity, malformed input handling, and edge cases (empty range, single bar, start > end). The shared behavioral conformance suite (§5.4) verifies each provider satisfies the base-class contract. **Rev 3 clarification (addresses R4):** conformance is verified via the behavioral suite — NOT via `isinstance(x, Provider)`. While ABCMeta does enforce that abstract methods (`download_ohlcv` etc.) are implemented (unlike Rev 2's `runtime_checkable` Protocol which only checked method names), `isinstance` STILL doesn't validate `stream()`/`fetch()` signatures or semantics — those are only concrete methods on the base, not abstract. The behavioral suite is the real gate. Additionally, run `mypy --strict` on each provider module — mypy DOES check signature compatibility with the parent class, which catches the class of errors `isinstance` misses.

- **Phase E2 (extraction):** Post-migration, run the full pine test suite from pynecore. Baseline: **1,353 passing** (matches openbb-fork's current count for the migrated subset per `pytest --collect-only -q`). Any test count change is a regression signal. Note: baseline was 1,343 in Rev 1 of this doc but 10 tests landed in Wave 2 review fixes between the doc draft and now.

- **Phase E3 (openbb-fork refactor):** Full pine test suite in openbb-fork must remain green — this is the definitive "no behavior change" gate. Additionally: run the M1 smoke test (`from openbb import obb; obb.pine.run(source, symbol="AAPL")`) end-to-end against the FMP adapter to verify the refactored `fmp_provider.py` still delivers correct bars. **Rev 3 addition:** exercise the deprecation shims (§13.5) — `import openbb_pine.compiler.codegen` should still work and emit a `DeprecationWarning` pointing at `pyne_compiler.codegen`.

- **Phase E4 (Phase 2 resumption):** Each resumed bead gets its own PR + review + fix loop per the pattern established in Wave 2 tonight. No cross-cutting test change — each bead's tests land with the bead.

**Regression guard:** Add a `pyne_compiler.tests.test_import_stability` module that asserts every public compiler entry point (`compile_pine`, `CompiledModule`, `PineError` hierarchy, etc.) can be imported at the documented module path. This catches accidental import-path breakage from future refactors.

## 10. Legal + audit considerations

- **Clean-room trailer preservation:** All ~40 compiler-touching commits in openbb-fork carry `Clean-room: I have not viewed TradingView or PyneComp source code.` Extraction preserves these verbatim via `git filter-repo`. New commits in `src/pyne_compiler/` must continue the trailer per PRD §2.5.
- **Apache-2.0 attribution:** `pynecore/NOTICE` (at repo root, ships in every wheel/sdist automatically) gets a new line naming our compiler additions. Wording (draft): *"src/pyne_compiler/ — clean-room Pine v5/v6 compiler contributed by Prashant Rajoria under Apache-2.0. See CLEANROOM.md for provenance."*
- **`CLEANROOM.md` placement (Rev 3, addresses R10):** Place `CLEANROOM.md` at the **repo root** (alongside `LICENSE`, `NOTICE`, `README.md`), NOT under `src/pyne_compiler/`. Reasons:
  - Files under `src/pyne_compiler/` do not automatically ship in the built wheel unless declared in `[tool.setuptools.package-data]` or listed in `MANIFEST.in`. Rev 2's placement (`src/pyne_compiler/CLEANROOM.md`) would ship in the sdist tarball but NOT in the wheel that users install. That defeats the "provenance visible to auditors" purpose.
  - Repo-root placement guarantees the file is visible on GitHub, ships in the sdist, ships in the wheel (setuptools includes top-level LICENSE/NOTICE-style files by default via the `license-files` config), and doesn't get lost in the package directory tree.
  - Alternative (if repo-root placement is undesired): add `include-package-data = true` to `[tool.setuptools]` and either `[tool.setuptools.package-data]."pyne_compiler" = ["CLEANROOM.md"]` or a `MANIFEST.in` line `include src/pyne_compiler/CLEANROOM.md`. Both work; repo-root is simpler.
- **Counsel signoff (bead 0e9.4.1):** The 2026-07-04 approval was scoped to "openbb-fork ships an extension using vendored PyneCore." This extraction changes that architecture. Recommended action: file a follow-up bead requesting counsel confirmation that the extraction preserves the Clean-room posture. Not blocking for extraction, but worth doing before pynecore's first published release.
- **License compatibility:** Everything stays Apache-2.0. No mixing, no dual-licensing, no CLAs required.

## 11. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `git filter-repo` command has a wrong path spec, produces partial history | Medium | High (would need re-run + re-review) | Do it in a scratch clone first; verify with `git log --follow` on 5+ representative files before pushing to pynecore. |
| Refactor breaks a subtle FMP-provider behavior not covered by unit tests | Medium | Medium | Run the M1 smoke test end-to-end against real FMP before landing the openbb-fork refactor PR. |
| Wave 3 subagents work in the OLD location while extraction is in flight | Medium | Low-Medium | Freeze Phase 2 via `bd update <id> --status blocked` on all open P1 sub-beads until extraction lands. Frozen bead IDs captured in `bd remember pine-phase2-frozen-for-extraction`. Unfreeze via §12 success-criteria checklist. |
| PyneCore upstream lands a change that conflicts with our fork during extraction window | Low | Low | Freeze upstream fetches until extraction is complete. Estimated extraction window: ~2 weeks. |
| A subtle circular import emerges (compiler needs runtime types, runtime needs compiler errors) | Medium | Low | Fix inline as import failures surface during Phase E3 — the extraction is a chance to enforce cleaner boundaries. |
| Bead references (in `bd`) become stale (referencing openbb-fork paths after extraction) | High | Low | Bulk-update all Phase 2 bead DESIGN fields as part of Phase E4 kickoff. |
| Documentation (`docs/designs/openbb-pine/D1-D5.md`) still references old paths | High | Low | Cross-reference cleanup as part of Phase E4. |

## 12. Success criteria

Extraction is complete when:

1. `prajoria/pynecore` main HEAD contains `src/pyne_compiler/` with full preserved history — verified by spot-checking **5 commits' trailers + author + date**, WHERE THE 5 SPOT-CHECKS INCLUDE AT LEAST ONE E0-SPLIT FILE (Rev 3, per R3) — i.e. at least one of `executor_core.py`, `compiler_errors.py`, `pynecore_bridge.py`, or `telemetry.py`. The reviewer explicitly acknowledges that the E0-split file's git history reaches back only to the E0 commit, not to earlier commits on the original `errors.py`/`executor.py`/etc. (per §7.1). This truncated-lineage behavior is accepted knowingly.
2. `prajoria/pynecore` main HEAD contains `src/pynecore/providers/{csv,sqlite}.py` and the extended `Provider` base class in `src/pynecore/providers/provider.py`, all with tests green. Existing `ccxt.py` and `capitalcom.py` still pass their tests (they inherit the new default `stream()`/`fetch()` without changes).
3. `openbb_pine_support` HEAD in openbb-fork consumes the extracted pynecore via updated submodule; full pine test suite green (baseline 1,353 passing preserved).
4. `obb.pine.run(source, symbol="AAPL", provider="fmp")` produces byte-identical output vs. pre-extraction baseline (verified by re-running M1 smoke test).
5. Deprecation shims installed under `openbb_pine/compiler/` and `openbb_pine/runtime/{executor,security_dispatcher,secondary_cache,security_hook,strategy_types,restricted,limits,_pynecore_glue}.py` — each re-exports the public names from `pyne_compiler.*` and emits a `DeprecationWarning` at import time (per §13.5).
6. All open Phase 2 P1 sub-beads have updated DESIGN fields pointing at `pyne_compiler/*` module paths, ready for Wave 3 resumption.
7. **Freeze/unfreeze checklist (Rev 3, addresses R9):** Every bead that was frozen before extraction is EITHER unfrozen (status changed from `blocked` back to `open` or `ready`) OR explicitly re-classified with a reason. Verification command:
   ```bash
   # The set of frozen beads is captured in the pine-phase2-frozen-for-extraction memory.
   # After extraction, each ID in that memory should either be:
   #   (a) unblocked (`bd show <id>` shows status != blocked), OR
   #   (b) have a `bd remember pine-<id>-still-blocked-because "..."` explanation.
   bd memories pine-phase2-frozen  # lists frozen beads
   for id in $(bd memories pine-phase2-frozen --keys | ...); do
     bd show $id | head -3  # verify status transitioned
   done
   ```
   No bead may be silently left in `blocked` state — either it's ready to resume, or the reason it's still blocked is documented as a memory.
8. `bd remember pine-extraction-completed "extracted YYYY-MM-DD; pynecore HEAD <sha>; openbb-fork HEAD <sha>; deprecation-shim removal target release <version>"` captures the transition point + the shim-removal deadline.
9. Follow-up bead `OpenBBTechnical-qj7` (h14 Signature.kwargs normalization, per §13.4) is unblocked (its `tracks` dependency on `rbf` resolves once extraction completes).

## 13. Open questions (deferred to implementation planning)

**Resolved in Rev 2, refined in Rev 3:**

- ~~Should `pyne_compiler/` be a distinct Python package with its own version, or a subpackage of `pynecore` (i.e. `pynecore.compiler`)?~~ **RESOLVED — distinct import package `pyne_compiler` living at `src/pyne_compiler/`, shipped from the same `pynesys-pynecore` distribution, carrying its own `__version__` string and a documented `pynecore` runtime-version floor.** (Rev 3 amendment per R7 wording.) Rationale: (a) clean provenance boundary (visible at directory level under `src/`), (b) `pyne_compiler.__version__` can advance independently of `pynecore.__version__` (compiler bugfixes shouldn't force a runtime version bump — but this is an independent VERSION STRING, not an independently installable wheel — see §4.2 for the full compatibility contract), (c) `import pyne_compiler` reads as intent-revealing vs. `import pynecore.compiler` which sounds like an internal upstream module.

**Resolved in Rev 3:**

- ~~Do we need a `pynecore-providers` extras group (`pip install pynecore[csv]` / `pip install pynecore[sqlite]`) or ship all providers unconditionally?~~ **RESOLVED — ship CSV/SQLite unconditionally in core** (per §15 feedback on §13.2). Rule: **stdlib-only providers ship in core; any provider needing a non-stdlib dep goes behind an extra named after the backing store.** Rationale: `csv` and `sqlite3` are stdlib — an extras group buys nothing but packaging surface. This mirrors the existing pattern in pynecore's `pyproject.toml`: `optional-dependencies.ccxt = ["ccxt"]` and `.capitalcom = ["httpx", "pycryptodome"]` (both non-stdlib). Future MySQL/Postgres/etc. providers follow the pattern (`optional-dependencies.mysql = ["mysqlclient"]`, `.postgres = ["psycopg"]`).

- ~~Should the extraction PR to pynecore be one giant merge commit, or should we cherry-pick commits in per-bead groups?~~ **RESOLVED — one `--allow-unrelated-histories` merge** (per §13.3 lock). Rationale: cherry-picking across unrelated histories loses the merge base, is error-prone at ~11k LOC, and gains nothing. Reviewability does NOT come from a small PR diff here (the diff is a whole subtree) — it comes from (a) this design doc, (b) preserved `git log --follow`/blame, (c) the green 1,353-test gate. Keep the pre-extraction tag from §8. **How to review an extraction PR (Rev 3 addition):** review the **rename map** (§7 `--path-rename` list) and the **test delta** (which tests moved vs. stayed vs. split), NOT the line diff. The line diff is by design a whole-subtree copy — reviewing it line-by-line is not the value-add.

- **§13.4 — `Signature.kwargs` slot vs. h14's trailing-tuple-kwargs inconsistency (flagged in Wave 2 h14 review).** **RESOLVED — bead filed as `OpenBBTechnical-qj7`** (linked as `tracks` to the extraction epic `OpenBBTechnical-rbf`). Not an extraction blocker; belongs in the first post-extraction cleanup PR. Filing the bead now (2026-07-06) survives Phase 2 freeze/unfreeze churn — the "we'll clean it up later" note that lives only in this doc would be lost once Phase 2 resumes in the new location.

### §13.5 — Deprecation strategy for old `openbb_pine.compiler.*` and `openbb_pine.runtime.*` import paths (Rev 3, new)

**Question:** §6.E3 originally proposed deleting `openbb_pine/compiler/` outright after E3. If notebooks / `Analysis/` code / doc examples / external users of the fork import those paths (`openbb_pine.compiler.codegen.compile_pine`, `openbb_pine.runtime.executor.run_compiled`, etc.), they break with no shim.

**Decision (Rev 3): Ship a one-release deprecation shim.**

Given §3 (non-goal-violation risk: "no behavior change for downstream users"), the hard-cut alternative violates the intent. Ship a re-export shim for one release, then remove.

**Concrete implementation:**

- After E3, `openbb_pine/compiler/__init__.py` (and each submodule that had a re-exported public API — `codegen.py`, `type_checker.py`, `parser.py`, etc.) contains:
  ```python
  """DEPRECATED: openbb_pine.compiler.* moved to pyne_compiler.*. This shim will be removed in the next minor release."""
  import warnings
  from pyne_compiler.codegen import *  # noqa: F401,F403
  from pyne_compiler.codegen import compile_pine, emit  # explicit re-exports for star-import safety
  warnings.warn(
      "openbb_pine.compiler.codegen is deprecated; import from pyne_compiler.codegen instead. "
      "This shim will be removed in the next minor release.",
      DeprecationWarning,
      stacklevel=2,
  )
  ```
- Same treatment for `openbb_pine/runtime/{executor,security_dispatcher,secondary_cache,security_hook,strategy_types,restricted,limits,_pynecore_glue}.py`.
- Same treatment for compiler+runtime error re-exports: `openbb_pine/errors.py` currently exports the full `PineError` hierarchy. Post-E3 it should still export the compiler+runtime error names (re-exported from `pyne_compiler.errors`) alongside its own provider-side errors. External code that does `from openbb_pine.errors import PineSyntaxError` continues to work; a `DeprecationWarning` at module-import time flags the migration.
- **Removal target:** the next `pynesys-pynecore` minor version bump (e.g. 6.5.x → 6.6.0). Documented in the E3 PR body + release notes.
- **Test coverage:** the E3 test suite exercises both old-path and new-path imports and asserts a `DeprecationWarning` fires on the old path (per §9 phase E3 note).

**Alternatives considered and rejected:**

- **Hard cut (no shim, only release-notes).** Cheaper (~0.5 day less work) but breaks any external notebook / `Analysis/` code / doc example that pinned to the old paths. Violates §3.
- **Permanent shim.** Locks in the old path forever, defeats the "clean provenance boundary" rationale for the extraction. Reject.
- **Shim for two releases.** Splits the difference but reads as "we can't commit to the migration" — one release is enough for anyone actively maintaining code, and passive users are already on the old openbb-fork version anyway.

---

**Approval sought:** User review of this document before proceeding to a written implementation plan.

---

## 14. Review comments (architect + senior developer)

Reviewed against the working tree on 2026-07-06. Overall this is a strong,
well-sequenced design — the addition of **Phase E0** in rev 2 is the right call
and is validated by the code: the compiler directory currently has **55**
`openbb_pine.*` references (telemetry confirmed in `codegen.py`,
`type_checker.py`, `v5_migration.py`, `compiler/__init__.py`), so a
decouple-in-place pass before any `filter-repo` move is genuinely necessary, not
ceremony. The rollback reasoning in §8 (submodule pins by SHA + pre-extraction
tag) is correct and unusually thorough.

That said, there are two **blocking** issues that must be resolved before an
implementation plan, plus several gaps. Severity tags: **[BLOCK]** must fix,
**[GAP]** design incomplete, **[NIT]** polish.

### R1 — [BLOCK] The topology assumes a flat layout; pynecore uses a `src/` layout

`third_party/pynecore/pyproject.toml` declares:

```toml
[tool.setuptools]
package-dir = { "pynecore" = "src/pynecore" }
packages.find = { where = ["src"] }
```

So the real tree is `src/pynecore/…`, **not** top-level `pynecore/…`. This breaks
the design in three concrete places:

- **§4 topology** shows `pynecore/adapters/` and a top-level `pyne_compiler/`. Actual
  targets must be `src/pynecore/adapters/` and `src/pyne_compiler/`.
- **§7 `git filter-repo` `--path-rename`** targets (`…:pyne_compiler/`,
  `…:pyne_compiler/errors/base.py`, etc.) would place the package *outside* the
  `where = ["src"]` discovery root — setuptools will silently **not** install
  `pyne_compiler`, and every `import pyne_compiler` fails at runtime. All renames
  must be prefixed with `src/`.
- **§6 E2 step 5** ("list `pyne_compiler` as a second package") needs to either drop
  the new package under `src/` (so `packages.find` picks it up automatically) or add
  an explicit `package-dir`/`packages` entry. State which, and note the distribution
  name stays `pynesys-pynecore` (or is renamed) — see R7.

This is mechanical but it invalidates the exact commands the plan will be built
from, so it must be corrected in the doc, not left to implementation.

### R2 — [BLOCK] pynecore already ships a `providers/` data abstraction that the design ignores

`src/pynecore/providers/` already exists and contains `provider.py`
(`class Provider(metaclass=ABCMeta)`), plus `ccxt.py` and `capitalcom.py`. That
existing `Provider` is:

- **construction-parameterized** (`__init__(symbol, timeframe, ohlv_dir, config_dir)`),
- **stateful** (context manager, holds an `OHLCVWriter`),
- a **download-to-`.ohlcv`-file** model, and
- already coupled to `SymInfo` / `get_symbol_info`.

The design introduces a *parallel* `DataProvider` **Protocol** (call-parameterized,
stateless, read-at-runtime) in a **new** `adapters/` directory and never mentions
the existing package. Problems this creates:

1. **Naming collision of concepts:** the repo would have both `Provider` (download)
   and `DataProvider` (runtime read). New contributors cannot tell which to
   implement. The §5 `SymbolInfo.symbol_info()` protocol also duplicates the
   existing `SymInfo` / `get_symbol_info` surface.
2. **§4 topology misrepresents the tree** by omitting `providers/` entirely, which
   makes the "clean two-directory provenance" story look tidier than reality.
3. **Missed reuse:** the existing `FileAdapter` you plan to add wraps `OHLCVReader`,
   which the existing `Provider` already knows about — there may be a cleaner unification.

**Required:** add a subsection reconciling the two. At minimum, justify *why* a new
`adapters/` package is preferable to extending `providers/`, rename to avoid the
`Provider`/`DataProvider` confusion (e.g. `OHLCVSource`), and update §4 to show the
real `providers/` sibling. If the two are meant to coexist permanently, say so and
document the boundary (download-time vs. run-time).

### R3 — [GAP] "Full history preservation" is only partially true for the E0-split files

`executor_core.py`, `compiler_errors.py`, and `pynecore_bridge.py` **do not exist
yet** — E0 creates them. Because `git filter-repo` rewrites the *entire* history and
the pre-E0 logic lived in `executor.py` / `errors.py` (which are **excluded** from the
move), the migrated `executor_core.py` will carry history only from the E0 commit
forward; its earlier lineage stays in openbb-fork under `executor.py`. So the
"every commit's Clean-room trailer + `git blame` continue to work" claim (§2, §7,
§12.1) holds for wholesale-moved files (all of `compiler/`) but is **partial** for the
E0-split files.

This is probably acceptable, but it must be stated explicitly in §7 and the §12
success criteria ("spot-check 5 commits") should deliberately include at least one
E0-split file so the reviewer sees the truncated-lineage behavior and signs off on it
knowingly.

### R4 — [BLOCK-ish contradiction] §9 re-introduces the `isinstance` conformance claim that §5.2 correctly rejects

§5.2 is right: `@runtime_checkable` only checks *method names*, so `isinstance` is not
real conformance. But §9 Phase E1 says conformance is verified "at static-type-check
level (via `isinstance(adapter, DataProvider)` since Protocol is `runtime_checkable`)".
That directly contradicts §5.2. Delete the `isinstance` sentence from §9 and point it
at the §5.2 behavioral suite instead.

### R5 — [GAP] The `stream() == fetch()` conformance contract may over-constrain live providers

Conformance check #1 asserts `list(stream(...)) == fetch(...)` byte-identical, and #4
requires `start > end` to **raise**. For the reference CSV/SQLite adapters that's fine,
but the downstream FMP/BYO adapters (which must also pass the suite per §5.2) are live/
paginated:

- A realtime feed can legitimately differ between `stream()` (may include a forming
  bar) and `fetch()` (closed bars only). Recommend scoping the equivalence guarantee to
  **closed historical ranges**.
- `start > end` returning `[]` is the natural SQL/`SELECT` semantics; forcing a raise
  adds a guard to every adapter. Pick one deliberately — I'd lean `[]` for consistency
  with check #3's "empty range returns empty, not error."

### R6 — [GAP] Python floor mismatch is unaddressed

pynecore is `requires-python = ">=3.11"`; the OpenBB fork advertises 3.10–3.13
(CLAUDE.md). Once the compiler lives in `pyne_compiler` under pynecore's pyproject, its
supported floor is governed there. Confirm the compiler already relies on ≥3.11
features (so 3.10 support in openbb-fork was already nominal), or set an explicit
`pyne_compiler` floor and a `pynecore>=X` runtime-dependency pin (it imports
`pynecore.types.ohlcv.OHLCV`). This interacts with R7.

### R7 — [GAP] "Independent versioning" needs a stated compatibility contract

§13's resolved decision (independent `pyne_compiler.__version__`) is reasonable, but two
import packages shipping from one distribution (`pynesys-pynecore`) with independent
versions needs an explicit compatibility rule: `pyne_compiler` depends on
`pynecore`-runtime types (`OHLCV`, `ScriptRunner`), so define the minimum `pynecore`
version `pyne_compiler` requires and where that pin lives (single pyproject → they can't
actually version-skew at install time; only the `__version__` *strings* differ). Clarify
that "independent versioning" means independent *semantic version strings*, not
independently *installable* wheels (unless you intend to split distributions, which the
doc should then say).

### R8 — [NIT] Line-count precision drifts from the tree

Measured today: `errors.py` = **916** LOC (not 1050), `error_codes.py` = 417,
`diagnostics.py` = 325 → combined **1,658**, whereas §4 states **1,911** and §6 E0.1's
`350 + 700 = 1050` split doesn't reconcile with 916. The doc leans on exact numbers
elsewhere (the "1,353 tests" gate), so either re-measure and fix, or explicitly label
these as approximate ("~"). Same for the §4 `pyne_compiler` ~11,400 roll-up, which
inherits the errors overcount.

### R9 — [NIT] Freeze/unfreeze coordination should be a first-class checklist

The risk table mentions freezing Phase 2 via `--status blocked`, but with 17 open P1
sub-beads plus in-flight Wave 3 subagents, recommend: (a) one tracking bead that lists
every frozen bead, (b) a `bd remember pine-extraction-freeze …` note recorded **before**
E0 starts, and (c) an explicit unfreeze checklist added to §12 success criteria so
resumption in E4 can't silently miss a bead.

### R10 — [NIT] `NOTICE`/`CLEANROOM.md` placement under `src/`

§10 references `pynecore/NOTICE` and a `pyne_compiler/CLEANROOM.md`. With the `src/`
layout, `CLEANROOM.md` under `src/pyne_compiler/` won't ship in the wheel unless added to
`package-data`/`MANIFEST.in`. Minor, but call it out so provenance docs actually make it
into the distribution.

### What I'd keep as-is (endorsed)

- E0-before-move sequencing and the six-sub-refactor decomposition — correct and
  code-justified.
- The behavioral conformance suite in §5.2 (once §9 is reconciled) — this is the right
  way to enforce a Protocol.
- Call-parameterized `DataProvider` over per-`(symbol, timeframe)` construction (§5.1) —
  correct for `request.security()`; keeps constructor logic out of the runtime.
- The pre-extraction tag + SHA-pin rollback story (§8) — genuinely robust.

---

## 15. Feedback on §13 open questions

**§13.1 — `pyne_compiler` as a distinct top-level package (RESOLVED).**
Agree with a distinct package + independent version *string*. **But "top-level" is
factually wrong given the `src/` layout** — it must be `src/pyne_compiler/` (see R1),
and "independent version" needs the compatibility contract in R7. Suggest amending the
resolution text to: *"distinct import package `pyne_compiler` living at
`src/pyne_compiler/`, shipped from the same `pynesys-pynecore` distribution, carrying its
own `__version__` string and a documented `pynecore` runtime-version floor."*

**§13.2 — adapters extras group (`pynecore[csv]` / `pynecore[sqlite]`)?**
**Lock it now, don't defer: ship unconditionally.** `csv` and `sqlite3` are stdlib, so
an extras group buys nothing but packaging surface. Reserve `optional-dependencies` for
the *future* adapters that pull real deps (`mysql` → a driver, `postgres` → `psycopg`) —
which is exactly the pattern the existing pyproject already uses
(`optional-dependencies.ccxt`, `.capitalcom`). Recommended rule to write into the doc:
"stdlib-only adapters ship in core; any adapter needing a non-stdlib dependency goes
behind an extra named after the backing store."

**§13.3 — one `--allow-unrelated-histories` merge vs. per-bead cherry-pick?**
**Choose the single merge; lock it.** Cherry-picking across unrelated histories loses the
merge base, is error-prone at ~11k LOC, and gains nothing: reviewability does *not* come
from a small PR diff here (the diff is a whole subtree) — it comes from (a) this design
doc, (b) preserved `git log --follow`/blame, and (c) the green 1,353-test gate. Keep the
pre-extraction tag from §8. The only thing worth adding: a short "how to review an
extraction PR" note in the PR body (review the *rename map* + test delta, not the line
diff).

**§13.4 — `Signature.kwargs` vs. h14 trailing-tuple-kwargs normalization.**
Agree it's **not an extraction blocker** and belongs in the first post-extraction cleanup
PR. One ask: **file the bead now** (blocked-by the extraction epic) so it survives the
freeze/unfreeze churn — an "we'll clean it up later" note that lives only in this doc will
be lost once Phase 2 resumes in the new location.

**One open question I'd add to §13:** *What is the deprecation/redirect story for the old
`openbb_pine.compiler.*` and `openbb_pine.runtime.executor` import paths?* §6 E3 step 5
deletes them outright. If anything outside the pine extension (notebooks, `Analysis/`,
docs examples, external users of the fork) imports those paths, they break with no
shim. Decide: hard cut (documented in release notes) vs. a thin re-export shim in
`openbb_pine/` for one release. Given "no behavior change for downstream users" is a
stated non-goal-violation risk (§3), a one-release shim is the safer default.
