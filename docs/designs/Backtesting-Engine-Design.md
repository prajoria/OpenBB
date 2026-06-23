# OpenBB Backtesting Engine — Detailed Design

**Status:** Design complete (all components #38–#49 designed)
**Parent epic:** [#25](https://github.com/prajoria/OpenBB/issues/25)
**Source PRD:** [Backtesting-Engine-PRD.md](../Specs/Backtesting-Engine-PRD.md)
**Scope:** Technical design for the `openbb-backtest` first-party extension.

This document is the index for the per-component design. Each section corresponds to a
GitHub feature issue and lives in [`backtest-design/`](./backtest-design/).

| # | Component | GitHub | Design file |
|---|-----------|--------|-------------|
| 1 | Scaffolding & package layout | [#38](https://github.com/prajoria/OpenBB/issues/38) | [01-scaffolding.md](./backtest-design/01-scaffolding.md) |
| 2 | Core data models & interfaces | [#39](https://github.com/prajoria/OpenBB/issues/39) | [02-data-models.md](./backtest-design/02-data-models.md) |
| 3 | fmp_cached data bundle | [#40](https://github.com/prajoria/OpenBB/issues/40) | [03-data-bundle.md](./backtest-design/03-data-bundle.md) |
| 4 | Vectorized engine (NumPy/Numba) | [#41](https://github.com/prajoria/OpenBB/issues/41) | [04-vectorized-engine.md](./backtest-design/04-vectorized-engine.md) |
| 5 | Event-driven engine (zipline) | [#42](https://github.com/prajoria/OpenBB/issues/42) | [05-event-driven-engine.md](./backtest-design/05-event-driven-engine.md) |
| 6 | Execution realism model | [#43](https://github.com/prajoria/OpenBB/issues/43) | [06-execution-realism.md](./backtest-design/06-execution-realism.md) |
| 7 | Performance analytics & reporting | [#44](https://github.com/prajoria/OpenBB/issues/44) | [07-analytics.md](./backtest-design/07-analytics.md) |
| 8 | Anti-overfitting validation | [#45](https://github.com/prajoria/OpenBB/issues/45) | [08-validation.md](./backtest-design/08-validation.md) |
| 9 | obb.backtest.* router & API | [#46](https://github.com/prajoria/OpenBB/issues/46) | [09-api-surface.md](./backtest-design/09-api-surface.md) |
| 10 | Strategy library | [#47](https://github.com/prajoria/OpenBB/issues/47) | [10-strategy-library.md](./backtest-design/10-strategy-library.md) |
| 11 | Optional non-vendored adapters | [#48](https://github.com/prajoria/OpenBB/issues/48) | [11-adapters.md](./backtest-design/11-adapters.md) |
| 12 | Testing, CI & NFRs | [#49](https://github.com/prajoria/OpenBB/issues/49) | [12-testing-nfr.md](./backtest-design/12-testing-nfr.md) |
| 13 | Hardware acceleration & scalability tiers | (cross-cutting) | [13-hardware-acceleration.md](./backtest-design/13-hardware-acceleration.md) |

## Dependency order (implementation sequence)

```
01 scaffolding
  └─ 02 data models
       ├─ 03 data bundle ─┐
       ├─ 06 execution  ──┤
       ├─ 11 adapters     │
       ├─ 04 vectorized ◄─┤ (needs 02,03,06)
       └─ 05 event-driven ◄ (needs 02,03,06)
            ├─ 07 analytics
            ├─ 08 validation
            ├─ 10 strategy library
            └─ 09 API surface (needs 04,05,07,08)
                 └─ 12 testing & NFRs
```

> **13 hardware acceleration** is cross-cutting: it tiers the CPU-only → GPU
> execution paths for 04 (vectorized), 05 (factor pipeline), 08 (validation),
> 11 (optional `[gpu]` extras), and 12 (per-tier NFR targets).

## Conventions used in all design files

- **License rule:** every dependency AGPL-3.0-compatible; never vendor Commons-Clause source.
- **Money:** `Decimal` everywhere; **paths:** `pathlib`; **logging:** stdlib `logging`, no `print`, no emoji.
- **Determinism:** seeded RNG, frozen calendars, point-in-time data.
- **Privacy:** no PII / dollar / lot leakage to external surfaces.
- **Hardware portability:** correct on CPU-only machines; GPU is an optional
  accelerator with numerically equivalent results (see component 13).
- Each design file ends with an **Acceptance mapping** back to its GitHub issue.
