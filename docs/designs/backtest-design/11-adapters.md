# 11 — Optional External-Engine Adapters

**GitHub:** [#48](https://github.com/prajoria/OpenBB/issues/48) · **Depends on:** [#39](https://github.com/prajoria/OpenBB/issues/39)
**Beads:** OpenBB-wh0, OpenBB-dna

`adapters/` lets power users run their strategy through a **third-party** engine while keeping
our canonical models. The license-sensitive engines (vectorbt, pybroker) are **never vendored** —
they are optional pip extras the user installs themselves.

---

## 1. License posture & import guard

| Engine | License | Distribution |
|---|---|---|
| vectorbt | Commons-Clause (Apache + non-commercial-resale rider) | **non-vendored optional extra** |
| pybroker | Apache-2.0 **+ Commons-Clause** | **non-vendored optional extra** |
| backtrader | GPL-3.0 | optional extra (copyleft — adapter only, no vendoring) |
| spectre | Apache-2.0 | optional extra (GPU factor engine) |
| cupy | MIT | optional `[gpu]` extra — GPU array backend (component 13) |

```python
# adapters/_optional.py
def require(pkg: str):
    try:
        return importlib.import_module(pkg)
    except ImportError as e:
        raise OptionalDependencyError(
            f"{pkg} is an optional extra. Install with: pip install openbb-backtest[{pkg}]. "
            f"Note: review {pkg}'s license before commercial use."
        ) from e
```

- No third-party engine is imported at package top level; everything is lazy via `require()`.
- Absence is graceful: `obb.backtest.run(engine="vectorbt")` without the package raises a clear
  `OptionalDependencyError`, never an opaque `ImportError`, and core features keep working.
- A CI license-guard test (component 12) asserts no Commons-Clause/GPL source is vendored in the
  repo and that these imports stay lazy.

---

## 2. Adapter contracts

```python
class EngineAdapter(Protocol):            # mirrors interfaces.Engine
    def run(self, strategy, config, feed, broker) -> BacktestResult: ...
```

Each adapter does three things:

1. **Translate inputs** — our `Strategy.generate` weights + `BacktestConfig` → the foreign
   engine's signal/order API (e.g. vectorbt `Portfolio.from_signals`, pybroker `Strategy`).
2. **Run** the foreign engine on data sourced from our bundle (component 03) — no second download.
3. **Normalize outputs** — foreign result → canonical `BacktestResult` (equity curve, trades,
   metrics via component 07), so downstream analytics/validation are engine-independent.

| Adapter | Maps weights via | Result source |
|---|---|---|
| `VectorbtAdapter` | `Portfolio.from_orders/from_signals` | `pf.value()`, `pf.trades` |
| `PybrokerAdapter` | `ctx.long/short` in exec fn | `result.portfolio`, `result.trades` |
| `BacktraderAdapter` | `Cerebro` + sizer strategy | analyzer outputs |
| `SpectreAdapter` | GPU factor pipeline | factor panel → component 05/07 |

- Cost models (component 06) are passed through where the foreign engine supports custom
  commission/slippage; otherwise the adapter documents the divergence (no silent mismatch).
- Adapters are **opt-in convenience**, not the source of truth — the event-driven engine
  (component 05) remains canonical for correctness claims.

---

## Acceptance mapping (#48)

| Acceptance criterion | Satisfied by |
|---|---|
| Optional engines non-vendored | §1 (extras + import guard) |
| Graceful absence | §1 (`OptionalDependencyError`) |
| License compliance | §1 table + CI guard |
| Adapter contract to canonical models | §2 (`EngineAdapter`, normalization) |
| Bundle reuse (no re-download) | §2 step 2 |
