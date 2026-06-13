# 12 — Testing Strategy & Non-Functional Requirements

**GitHub:** [#49](https://github.com/prajoria/OpenBB/issues/49) · **Depends on:** [#46](https://github.com/prajoria/OpenBB/issues/46)
**Beads:** OpenBB-gpb, OpenBB-cex

The quality gate for the whole engine: what we test, how we keep it deterministic, the
performance bars it must clear, and the CI that enforces all of it.

---

## 1. Test taxonomy & fixtures

| Tier | Marker | Scope | Data |
|---|---|---|---|
| Unit | (none) | models, validators, cost models, metric math, splitters | synthetic in-memory |
| Integration | `integration` | full `run` on both engines, sweep, validate, router | small frozen bundle |
| Golden | `golden` | reference strategies produce known equity curves | committed fixtures |

- **Fixtures** (`tests/conftest.py`): a tiny deterministic OHLCV panel (e.g. 5 symbols × 252
  sessions) committed as parquet so integration tests need **no live API and no MySQL**; an
  `fmp_cached` stub feeds the bundle from this fixture.
- **Golden tests:** each reference strategy (component 10) runs against the frozen bundle; its
  equity curve / key metrics are stored and compared within tolerance — catches silent
  behavior regressions.
- **Cross-engine parity test:** the reconciliation gate (component 04) is asserted in CI —
  vectorized vs event-driven equity curves agree within `1e-6` on a shared deterministic case.
- **License-guard test:** asserts (a) no vectorbt/pybroker/backtrader source is vendored in the
  tree, and (b) those imports are lazy (component 11) — a hard CI failure if violated.

---

## 2. Non-functional requirements

| NFR | Target |
|---|---|
| Vectorized throughput | ≥ 10,000 param combos / minute (T1 CPU); ≥ 100k on T2 GPU — see [13-hardware-acceleration.md](./13-hardware-acceleration.md) |
| Single event-driven backtest | 10y daily, 500-symbol universe < ~60s |
| Determinism | identical inputs+seed ⇒ byte-identical `BacktestResult` (CPU / GPU float64) |
| Memory | sweep stays within a configurable cap (host RAM / VRAM); chunk when exceeded |
| Look-ahead safety | enforced structurally (shift(1)/next-bar) + asserted by a leakage test |
| Privacy | no raw positions/dollars in any outward artifact (asserted in router tests) |

- **Hardware tiers (T0 CPU-only → T2 RTX 3090 / 64 GB):** per-tier targets and the
  CPU↔GPU parity requirement are specified in component 13; GPU benchmarks are skipped
  (not failed) on CPU-only CI runners.

- **Determinism/repro:** a single `seed` in `BacktestConfig` threads through any stochastic
  step (bootstrap, CPCV combination order); NumPy/Numba RNG seeded centrally; floating-point
  reductions use stable ordering.
- Decimal for money, pathlib for paths, `logging` (no `print`), no emoji — repo conventions
  asserted by Ruff in CI.

---

## 3. CI jobs

| Job | Runs | Gate |
|---|---|---|
| `lint` | Ruff (line-length 122, py310) | must pass |
| `unit` | `pytest -m "not integration and not golden"` | must pass, fast |
| `integration` | `pytest -m integration` (frozen bundle, no network) | must pass |
| `golden` | `pytest -m golden` | must pass within tolerance |
| `parity` | reconciliation 1e-6 test | must pass |
| `license-guard` | vendoring + lazy-import assertions | must pass |
| `benchmark` (nightly) | throughput vs NFR targets | regression alert |
- Coverage target ≥ 85% on the core (non-adapter) packages.
- Benchmarks run nightly (not per-PR) to avoid flaky timing gates while still tracking drift.

---

## Acceptance mapping (#49)

| Acceptance criterion | Satisfied by |
|---|---|
| Test taxonomy + fixtures | §1 |
| Golden/reference tests | §1 |
| Cross-engine parity | §1 (reconciliation in CI) |
| License-guard test | §1 |
| NFR targets | §2 table |
| Determinism/reproducibility | §2 (seed policy) |
| CI enforcement | §3 |
