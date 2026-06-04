# 04 — Vectorized In-House Engine (NumPy/Numba)

**GitHub:** [#41](https://github.com/prajoria/OpenBB/issues/41) · **Depends on:** [#39](https://github.com/prajoria/OpenBB/issues/39), [#40](https://github.com/prajoria/OpenBB/issues/40), [#43](https://github.com/prajoria/OpenBB/issues/43)
**Beads:** OpenBB-wzl, OpenBB-5bt, OpenBB-3rr

The high-throughput research engine (`engine/vectorized.py`). Implements the `Engine`
Protocol. Primary use: fast parameter sweeps. Source of *truth* remains the event-driven
engine (component 05); this path must reconcile against it within tolerance.

---

## 1. Signal → position → PnL pipeline

All series are aligned to the bundle's session index `T` and symbol axis `S`, giving
matrices of shape `(T, S)`.

```
weights_t   = strategy.generate(...)            # (T, S) target weights, per session
weights_lag = shift(weights_t, 1)               # MANDATORY 1-bar lag (no same-bar fill)
returns     = close.pct_change()                # (T, S) simple returns (adj close)
costs       = turnover(weights_lag) * cost_bps  # commission+slippage via Broker (component 06)
port_ret    = (weights_lag * returns).sum(axis=1) - costs
equity      = initial_cash * (1 + port_ret).cumprod()
```

- **Mandatory lag:** `weights.shift(1)` is applied unconditionally inside the engine, not the
  strategy, so a strategy cannot accidentally peek. A guard asserts no NaN-free row of
  `weights_t` is used at its own session.
- **Turnover & costs** are computed from weight deltas and routed through the same `Broker`
  (`Commission`/`Slippage`) as the event engine, so cost assumptions match exactly.
- **Long/short:** negative weights allowed; gross/net exposure tracked per session for the
  `EquityPoint.exposure` field.

---

## 2. Numba hot paths + portfolio accounting

Vectorized NumPy handles the matrix math; **Numba `@njit`** kernels accelerate the inherently
sequential parts:

| Kernel | Why Numba |
|---|---|
| `_running_drawdown(equity)` | sequential max-so-far; slow in pure pandas |
| `_apply_constraints(weights, max_pos, restricted)` | per-cell clamp + renormalize across S |
| `_tax_lot_pnl(trades, method)` | lot matching loop (FIFO/LIFO/specific-ID) |
| `_volume_cap_fills(orders, volume, cap)` | partial-fill loop |

- **Memory model:** matrices are `float64` `(T, S)`; for a 10y daily / 500-symbol run that is
  `~2520 x 500 x 8B ≈ 10 MB` per matrix — trivially in-memory. Sweeps reuse the returns matrix
  across all parameter combos (computed once).
- **GPU acceleration (optional):** the matrix math uses an injected array module `xp` so the
  identical kernel source runs on NumPy (CPU) or CuPy (GPU); on a GPU machine sweeps are batched
  on-device as a `(K, T, S)` tensor. CPU is always correct and is the default. See
  [13-hardware-acceleration.md](./13-hardware-acceleration.md).
- **Multi-asset:** broadcasting over the `S` axis; ragged histories (delisted symbols) handled
  with NaN masks so absent symbols contribute zero weight/return.
- **Determinism:** no RNG in the core path; any stochastic strategy receives a seeded generator
  from `BacktestConfig.seed`.

---

## 3. Sweep API + reconciliation + benchmarks

```python
def sweep(strategy_factory, param_grid: dict[str, list], config) -> SweepResult:
    # 1. compute returns matrix ONCE
    # 2. for each param combo (itertools.product), rebuild weights, reuse returns
    # 3. parallelize combos across CPU cores (numba prange / joblib)
    # 4. return per-combo PerformanceMetrics + best combo
```

- **Reconciliation gate** (`engine/reconcile.py`): runs a single baseline config through both
  engines and asserts `max|equity_vec - equity_evt| <= reconcile_tolerance` (default `1e-6`).
  A failure flags a look-ahead or cost-model divergence. This is the automatic correctness
  check that lets the fast engine be trusted.
- **Performance targets (NFR):** ≥10k parameter combos/min on a single mid-range CPU; returns
  matrix computed once and shared; kernels JIT-warmed on first call (warm-up excluded from
  benchmark timing). On the GPU tier this rises to ≥100k combos/min via on-device batching
  (see [13-hardware-acceleration.md](./13-hardware-acceleration.md)).
- **`engine="auto"` policy:** use vectorized only when the strategy is provably stateless
  (pure function of current weights); otherwise defer to the event engine. Default of record is
  event-driven (correctness first).

---

## Acceptance mapping (#41)

| Acceptance criterion | Satisfied by |
|---|---|
| Engine class/loop design | §1 (implements `Engine` Protocol) |
| Vectorized accounting math | §1 (weights×returns − costs → equity) |
| Numba kernels identified | §2 table |
| Benchmarks/targets defined | §3 (≥10k combos/min) |
| Look-ahead safety | §1 mandatory shift(1) + §3 reconciliation gate |
| Cost parity with event engine | §1 (shared Broker) |
