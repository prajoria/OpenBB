# 13 — Hardware Acceleration & Scalability Tiers

**Related:** [#41](https://github.com/prajoria/OpenBB/issues/41) (vectorized engine), [#45](https://github.com/prajoria/OpenBB/issues/45) (validation), [#48](https://github.com/prajoria/OpenBB/issues/48) (adapters), [#49](https://github.com/prajoria/OpenBB/issues/49) (NFRs)

The engine must run on anything from a **CPU-only laptop** to a **high-end GPU workstation**
without code changes. GPU is an **optional accelerator**, never a requirement: every operation
has a correct CPU path, and the GPU path must produce numerically equivalent results (within
floating-point tolerance) so the reconciliation gate (component 04) still holds.

---

## 1. Hardware tiers

| Tier | Reference spec | Default execution |
|---|---|---|
| **T0 — minimal** | 2–4 cores, 8 GB RAM, no GPU | single-process NumPy + Numba (CPU) |
| **T1 — CPU workstation** | 8–16 cores, 32 GB RAM, no GPU | multi-core sweeps (joblib/`prange`) |
| **T2 — GPU workstation** | 8+ cores, **64 GB RAM**, **RTX 3090 (24 GB VRAM)** | GPU-accelerated vectorized math + factor pipeline |

- The codebase **auto-detects** the tier at runtime (see §4) and selects the fastest *available*
  path; users can pin a tier via config for reproducibility.
- T2 is the design's documented **reference GPU machine** (RTX 3090, 24 GB VRAM, 64 GB system
  RAM); NFR GPU targets (component 12) are quoted against it.

---

## 2. What runs where

| Workload | T0/T1 (CPU) | T2 (GPU) |
|---|---|---|
| Vectorized `(T,S)` returns/PnL math (component 04) | NumPy `float64` | **CuPy** drop-in (`xp = cupy`) |
| Numba sequential kernels (drawdown, lot matching) | `@njit` CPU | `@cuda.jit` where parallelizable, else CPU |
| Parameter sweep (component 04) | `joblib`/`prange` over cores | batched on-device: many combos as one big array axis |
| Pipeline / factor compute (component 05) | pandas/Numba | optional **spectre** GPU factor engine (component 11) |
| CPCV / bootstrap (component 45) | multi-core | GPU batch of fold paths |
| Event-driven engine (component 05) | CPU (zipline) | CPU (unchanged — inherently sequential) |
| Analytics/validation stats (07/08) | CPU | CPU (cheap; not worth transfer) |

- **Array abstraction:** the vectorized core uses an injected array module `xp` (`numpy` or
  `cupy`) so the same kernel source runs on either device. A thin `compute/backend.py` resolves
  `xp` and provides `asnumpy()` / `asarray()` transfer helpers.
- **Event-driven stays CPU:** zipline's event loop does not vectorize; GPU offers no benefit, so
  T2 keeps it on CPU. GPU only accelerates the research/sweep/factor paths.

---

## 3. GPU memory model (RTX 3090, 24 GB VRAM)

- A `(T, S)` `float64` matrix for 10y daily × 500 symbols ≈ **10 MB** — thousands fit in 24 GB,
  so **sweeps are batched on-device**: stack `K` parameter combos into a `(K, T, S)` tensor and
  evaluate in one kernel launch, bounded by VRAM.
- **Batch sizing:** `K_max = floor(usable_VRAM / per_combo_bytes)` with a safety headroom
  (default 80 % of free VRAM); the sweep driver chunks the grid into VRAM-sized batches and
  streams results back to host. This keeps a 24 GB card saturated without OOM.
- **Precision:** default `float64` for parity with the CPU/event path; an opt-in `float32` mode
  (`config.gpu_precision="float32"`) ~doubles throughput and VRAM capacity for exploratory
  sweeps, but is **excluded from the reconciliation gate** (documented tolerance trade-off).
- **Host RAM (64 GB):** large bundles and full sweep result frames stay in host memory; only the
  active batch is resident on the GPU. Spilling/chunking triggers when a result set exceeds a
  configurable host-RAM cap.
- **Fallback:** any CUDA error (no device, OOM, driver mismatch) logs a warning and transparently
  falls back to the CPU path — runs never fail solely due to GPU issues.

---

## 4. Configuration & detection

Extends `BacktestConfig` (component 02) — all optional, CPU-safe defaults:

```python
class ComputeConfig(Data):
    device: Literal["auto", "cpu", "gpu"] = "auto"      # auto = use GPU if present
    n_jobs: int = -1                                     # CPU sweep parallelism (-1 = all cores)
    gpu_precision: Literal["float64", "float32"] = "float64"
    gpu_vram_headroom: float = 0.2                       # fraction of VRAM kept free
    host_ram_cap_gb: float | None = None                 # None = no explicit cap
```

- **Auto-detect:** `compute/backend.py` probes for a CUDA device via the optional `cupy`
  import-guard (component 11 pattern). Present + healthy ⇒ T2; else fall back to T1/T0 by core
  count. Detection result is logged once and recorded in `BacktestResult.run_metadata`.
- **Reproducibility:** pinning `device="cpu"` (or `gpu_precision="float64"`) yields
  deterministic, machine-independent results; `device="auto"` is for speed, not for golden tests.
- **Optional extras:** GPU support ships as `pip install openbb-backtest[gpu]` (cupy, optionally
  spectre) — **non-vendored**, behind the same import guard as other optional engines
  (component 11). CPU install pulls **zero** GPU dependencies.

---

## 5. NFR targets by tier (feeds component 12)

| Metric | T0 minimal | T1 CPU workstation | T2 GPU (RTX 3090) |
|---|---|---|---|
| Sweep throughput (combos/min) | ≥ 2k | ≥ 10k | ≥ 100k (batched, float32 exploratory) |
| 10y × 500-sym single vectorized run | < 5 s | < 2 s | < 1 s |
| Determinism | byte-identical | byte-identical | byte-identical at `float64` |
| Memory ceiling | 8 GB host | 32 GB host | 24 GB VRAM / 64 GB host |

- Benchmarks run on the documented reference machines; the nightly `benchmark` CI job
  (component 12) records per-tier numbers and alerts on regression. GPU benchmarks run only where
  a CUDA runner is available and are **skipped (not failed)** on CPU-only CI.

---

## Acceptance mapping

| Criterion | Satisfied by |
|---|---|
| Runs CPU-only with no GPU deps | §2/§4 (CPU defaults, optional `[gpu]` extra) |
| Scales to high-end GPU (RTX 3090) | §2/§3 (CuPy backend, on-device batched sweeps) |
| Numerical parity CPU↔GPU | §3 (float64 default, reconciliation gate) |
| Graceful GPU-absent / OOM fallback | §3/§4 |
| Config surface for device/precision | §4 (`ComputeConfig`) |
| Tiered NFR targets | §5 |
