# E0.6 Test-Split Manifest (bd-209 / OpenBBTechnical-209)

**Base branch:** `openbb_pine_support`  |  **Feature branch:** `feat/e06-test-split`
**Spec:** `docs/superpowers/specs/2026-07-06-pine-extraction-to-pynecore-design.md` §6.E0.6
**Plan task:** `docs/superpowers/plans/2026-07-07-pine-extraction-implementation.md` E0.6
**Baseline:** 1384 passed + 10 skipped (unchanged after refactor)
**Total files audited:** 82 unit test files under
`openbb_platform/extensions/pine/openbb_pine/tests/unit/` (81 pre-existing
+ 1 new `test_telemetry_module_globals.py` produced by the gray-zone
refactor; the `__init__.py` is not counted as a test).

**Ground truth for all counts below:** the E2 filter-repo list at
lines 148–171 is authoritative. Every other bucket in this document
(header total, MOVE/STAY tables, Counts section, Surprises notes) is
derived from it: `MOVE = |E2 list| = 24`; `STAY = |disk test_*.py| − MOVE = 82 − 24 = 58`.

## Decision rule (spec §6.E0.6)

> A test file MOVES to pynecore iff all its non-stdlib imports are either
> (a) pynecore-side (`pyne_compiler.*`, `pynecore.*`) OR (b) stdlib/test
> fixtures (pytest, hypothesis, unittest.mock, tempfile, pathlib). Any
> test importing an openbb-fork-side module STAYS as an integration test.

Fork-side surfaces that force STAY: `openbb_pine.attribution`,
`openbb_pine.telemetry` (except after the E0.6 refactor), `openbb_pine.routers.*`,
`openbb_pine.mcp_tools`, `openbb_pine._coverage_manifest`, `openbb_pine.cli.*`,
`openbb_pine._load_bundled_widgets`, `openbb_pine.about`,
`openbb_pine.diagnostics`, `openbb_pine.stdlib.*`, and the runtime
provider glue (`fmp_provider`, `byo_provider`, `fmp_retry`,
`provider_selection`), plus any `openbb_core.*` import.

Grep used to classify:
```
grep -l "openbb_pine\.\(attribution\|telemetry\|routers\|mcp_tools\|_coverage_manifest\|cli\|_load_bundled_widgets\|about\|diagnostics\|stdlib\)\|openbb_pine\.runtime\.\(fmp_provider\|byo_provider\|fmp_retry\|provider_selection\)\|openbb_core" <file>
```

---

## MOVE (24 files) — pynecore-side only

These tests import only compiler internals, IR, error classes, runtime
core primitives, or stdlib/test fixtures. They belong in
`pyne_compiler/tests/` after E2's `git filter-repo --path`.

| File | Rationale (imports) |
|---|---|
| `test_builtin_signatures.py` | pytest + `openbb_pine.compiler.builtin_signatures` + `.compiler.types` only |
| `test_codegen.py` | `openbb_pine.compiler.{codegen,emit,ir,types}` + `.errors` |
| `test_codegen_allowlist.py` | `openbb_pine.compiler.codegen` + `.errors` |
| `test_compile_cache.py` | `openbb_pine.compiler.compile_cache` + `.compiler.types` + `.errors` + stdlib mock |
| `test_compiled_module_shape.py` | `openbb_pine.compiler.types` only |
| `test_error_classes.py` | `openbb_pine.errors` only |
| `test_error_model.py` | After E0.6 refactor: `openbb_pine.compiler.*` + `.errors` + `.error_codes` only (telemetry module-globals extracted; integration tests now use an in-test `_CountingSink`) |
| `test_error_split.py` | `openbb_pine.errors` + `.compiler_errors` |
| `test_executor_core.py` | `openbb_pine.runtime.executor_core` + `.compiler.types` + `pynecore.lib` (test also inspects source for banned tokens — those are string literals, not imports) |
| `test_executor_deprecation_shim.py` | `openbb_pine.runtime.{executor,executor_shell,executor_core}` — all runtime-core; shim itself will move with executor_core |
| `test_grammar_strategy.py` | `openbb_pine.compiler.{lexer,parser,ir,compile_pine_to_program}` |
| `test_ir.py` | `openbb_pine.compiler.{ir,types}` only |
| `test_lexer.py` | `openbb_pine.compiler.lexer` + `.errors` |
| `test_limits.py` | `openbb_pine.runtime.limits` + `.errors` (runtime-core primitive) |
| `test_parser.py` | `openbb_pine.compiler.{ir,lexer,parser}` + `.errors` |
| `test_pynecore_bridge.py` | `openbb_pine.runtime.pynecore_bridge` only (moves with bridge per E0.5) |
| `test_restricted.py` | `openbb_pine.runtime.restricted` only (runtime-core sandbox) |
| `test_security_context_collection.py` | `openbb_pine.compiler.{compile_pine,types}` + `.errors` |
| `test_security_hook_monkey_patch.py` | `openbb_pine.runtime.security_hook` + `.compiler.types` + `.errors` |
| `test_strategy_types.py` | `openbb_pine.runtime.strategy_types` only |
| `test_type_checker.py` | `openbb_pine.compiler.{ir,lexer,parser,type_checker}` + `.errors` |
| `test_type_checker_strategy.py` | `openbb_pine.compiler.{compile_pine,builtin_signatures,types}` + `.errors` (stdlib string in module docstring only) |
| `test_types.py` | `openbb_pine.compiler.types` + `.errors` |
| `test_v5_migration.py` | `openbb_pine.compiler.{compile_pine,compile_pine_to_program,ir,v5_migration}` + `.errors` |

**Note on `test_telemetry_injection.py`:** this file is NOT in the MOVE
table above — it stays in the fork. It imports
`openbb_pine.telemetry.OpenBBTelemetrySink` at 10+ call sites (grep:
`from openbb_pine.telemetry import OpenBBTelemetrySink` at lines 144,
158, 181, 226, 260, 286, 317, 335, 354, …) to verify the concrete
fork-side sink implements the Protocol correctly. That is a fork-side
surface by the rule → STAY. See STAY table below.

---

## STAY (58 files) — openbb-fork integration tests

Any test hitting attribution, routers, MCP, CLI, providers, stdlib
bridges, `_coverage_manifest`, `_load_bundled_widgets`, `about`,
`diagnostics`, or `openbb_core` stays as an integration/wiring test.

| File | Rationale |
|---|---|
| `test_about.py` | Tests `openbb_pine.about` (fork-side entry surface) |
| `test_attribution_surfaces.py` | `openbb_pine.attribution` (POWERED_BY_*) |
| `test_byo_provider.py` | `openbb_pine.runtime.byo_provider` |
| `test_cli_main.py` | `openbb_pine.cli.main` + `.diagnostics` + `.attribution` |
| `test_diagnostics.py` | `openbb_pine.diagnostics` (fork-side, drives `about`+CLI) |
| `test_executor_shell.py` | `openbb_pine.attribution` + `.runtime.executor_shell` — the shell + FMP wiring layer that stays |
| `test_extension_loads.py` | Imports `openbb_pine` itself + `.about` (extension entrypoint) |
| `test_fmp_provider.py` | `openbb_pine.runtime.fmp_provider` |
| `test_fmp_retry.py` | `openbb_pine.runtime.fmp_retry` |
| `test_mcp_tools.py` | `openbb_pine.mcp_tools` + `_load_bundled_widgets` |
| `test_no_side_effects.py` | Subprocess-imports `openbb_pine` + `openbb_core.app.service.*` |
| `test_prefetch_security.py` | `openbb_pine.compiler_errors` + `.runtime.{secondary_cache,security_dispatcher,_data_provider_stub}` — plus test asserts absence of banned FMP-provider strings (fork-side wiring test) |
| `test_provider_selection.py` | `openbb_pine.runtime.provider_selection` |
| `test_router_command_bare_obbject.py` | AST-walks the fork's router modules for OBBject shape enforcement |
| `test_routers_catalog.py` | `openbb_core.app.model.obbject` + `openbb_pine.routers._models` |
| `test_routers_compile.py` | `openbb_core.app.model.obbject` + `openbb_pine.routers._models` + `.attribution` |
| `test_routers_health.py` | `openbb_core.app.model.obbject` + `openbb_pine.attribution` + `.diagnostics` |
| `test_routers_models.py` | `openbb_pine.attribution` + `.routers._models` |
| `test_routers_run.py` | `openbb_core.app.model.obbject` + `openbb_pine.errors` (drives the router execution path) |
| `test_stdlib_math_abs.py` … `test_stdlib_math_sum.py` (7 files) | `openbb_pine._coverage_manifest` + `.stdlib.math` |
| `test_stdlib_ta_*.py` (29 files: adx, atr, barssince, bb, cci, change, crossover, crossunder, cum, ema, highest, linreg, lowest, macd, median, mfi, mom, obv, percentile_linear_interpolation, rma, roc, rsi, sar, sma, stdev, stoch, tr, vwap, wma) | Each imports `openbb_pine.stdlib.ta` (and most import `_coverage_manifest`) — the stdlib bridge stays in the fork per §7 |
| `test_telemetry_injection.py` | `openbb_pine.telemetry.OpenBBTelemetrySink` — validates the concrete fork-side Protocol implementer (see MOVE note above) |
| `test_telemetry_module_globals.py` | **NEW (E0.6 refactor):** owns `openbb_pine.telemetry.{record_unsupported_*,reset_metrics,get_unsupported_*_counts}` module-global tests extracted from `test_error_model.py` |
| `test_widgets.py` | `openbb_pine._load_bundled_widgets` + `.attribution` + `.compiler` |

**Counted STAY: 58** (22 named files above + 7 `test_stdlib_math_*` + 29
`test_stdlib_ta_*`).

---

## Special cases — gray-zone refactors applied

| File | Action | Rationale |
|---|---|---|
| `test_error_model.py` | **REFACTORED → MOVE.** Extracted `TestTelemetryCounters` (module-global counter API) to new `test_telemetry_module_globals.py` (STAY). Rewrote `TestTelemetryIntegration` to instantiate an in-test `_CountingSink` implementing the `TelemetrySink` Protocol shape instead of importing `openbb_pine.telemetry.OpenBBTelemetrySink`. Removed the `reset_metrics`-based `setup_method` (no longer needed once each test owns its sink). Result: file's only non-stdlib imports are now `openbb_pine.{compiler.*, errors, error_codes}` → cleanly MOVE. |
| `test_telemetry_module_globals.py` | **NEW file (STAY).** Holds the extracted `TestTelemetryCounters` class covering the module-global counter shim in `openbb_pine.telemetry`. This surface stays in the fork alongside `OpenBBTelemetrySink`. |
| `test_executor.py` → `test_executor_shell.py` + `test_executor_core.py` | Already split in E0.3 (bd-9zb, commit 53c4a9dbf). Shell STAYS (attribution + FMP wiring); core MOVES. `test_executor_deprecation_shim.py` also MOVES because the shim module itself moves. |
| `test_telemetry_injection.py` | Contract test for the E0.4 injection wiring. Because it verifies the concrete `openbb_pine.telemetry.OpenBBTelemetrySink` implements the Protocol (imported at multiple sites), it **STAYS** as an integration test rather than being refactored to a fake sink — the whole point of these tests is to pin the real fork-side sink. |

**No gray-zone left un-refactored.** Every remaining STAY test has an
unavoidable dependency on a fork-side surface that is out of scope for
migration (routers/attribution/providers/stdlib/CLI/coverage manifest/
telemetry-concrete-sink/diagnostics/about/`_load_bundled_widgets`) or
on `openbb_core` directly.

---

## Counts (final)

Derived directly from the E2 filter-repo list (§ below) and `ls` of the
unit test directory. If these disagree, the E2 list wins and the counts
here get updated — do not adjust ad-hoc.

| Bucket | Count |
|---|---:|
| MOVE (pyne_compiler-side, per E2 list) | **24** |
| STAY (openbb-fork-side integration) | **58** |
| **Total unit test files (excludes `__init__.py`)** | **82** = 81 pre-existing + 1 new `test_telemetry_module_globals.py` |

MOVE + STAY = 24 + 58 = 82. On disk: `ls .../tests/unit/*.py | wc -l` = 83, minus `__init__.py` = 82. ✅

---

## E2 `git filter-repo --path` list (MOVE only)

To be fed to E2's filter-repo invocation (relative to repo root):

```
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_builtin_signatures.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_codegen.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_codegen_allowlist.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_compile_cache.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_compiled_module_shape.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_error_classes.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_error_model.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_error_split.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_executor_core.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_executor_deprecation_shim.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_grammar_strategy.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_ir.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_lexer.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_limits.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_parser.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_pynecore_bridge.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_restricted.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_security_context_collection.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_security_hook_monkey_patch.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_strategy_types.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_type_checker.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_type_checker_strategy.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_types.py
openbb_platform/extensions/pine/openbb_pine/tests/unit/test_v5_migration.py
```

Plus the conformance harness (`openbb_platform/extensions/pine/openbb_pine/tests/conformance/`),
which is spec-only pynecore-side.

---

## Surprises / notes

1. **`test_telemetry_injection.py` reclassified STAY.** The spec's
   §6.E0.6 list didn't explicitly name it. It imports
   `openbb_pine.telemetry.OpenBBTelemetrySink` at ~10 sites to verify
   the concrete fork-side implementer satisfies the Protocol — that IS
   fork-side coupling by the rule, and refactoring it to a fake sink
   would defeat the test's purpose (pinning the shipped sink). STAY.
2. **`test_error_model.py` refactor was cheap.** 76 lines removed
   (extracted class) + ~30-line rewrite (integration tests use local
   `_CountingSink` instead of `OpenBBTelemetrySink`); baseline tests
   remain green.
3. **`test_prefetch_security.py`** — asserts absence of FMP-provider
   strings by AST/regex, but imports only `_data_provider_stub`,
   `secondary_cache`, `security_dispatcher`, and `compiler_errors`. On
   strict rule reading its imports are pynecore-side. Kept STAY per the
   spec's explicit enumeration (§6.E0.6 lists it in the STAY set) —
   the string-literal assertions couple it to fork-side provider names.
4. **Seven `test_stdlib_math_*` files** in the tree (abs/max/min/pow/round/
   sqrt/sum), matching the spec's "7 files" note exactly.
5. **29 `test_stdlib_ta_*` files** on disk (adx, atr, barssince, bb, cci,
   change, crossover, crossunder, cum, ema, highest, linreg, lowest,
   macd, median, mfi, mom, obv, percentile_linear_interpolation, rma,
   roc, rsi, sar, sma, stdev, stoch, tr, vwap, wma).
