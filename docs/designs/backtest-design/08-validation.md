# 08 — Validation & Robustness Framework

**GitHub:** [#45](https://github.com/prajoria/OpenBB/issues/45) · **Depends on:** [#41](https://github.com/prajoria/OpenBB/issues/41), [#42](https://github.com/prajoria/OpenBB/issues/42)
**Beads:** OpenBB-4gu, OpenBB-cgs

The `validation/` package guards against the #1 failure mode of backtesting: **overfitting**.
Every technique is **re-implemented from the public literature** — `mlfinlab` is
Commons-Clause/restricted and is **not** vendored or imported (license rule).

---

## 1. Resampling: WFO + CPCV (purge & embargo)

```python
def walk_forward(config, strategy, *, train, test, step, anchored=False) -> list[Fold]
def cpcv(config, strategy, *, n_groups=6, n_test_groups=2, embargo=0.01) -> list[Fold]
```

- **Walk-forward (WFO):** rolling or anchored train→test windows; the strategy is
  re-fit/re-parameterized only on `train`, evaluated only on the immediately-following `test`.
  Aggregates out-of-sample fold metrics → the only honest performance estimate.
- **CPCV (Combinatorial Purged CV):** partition sessions into `n_groups`, take all
  combinations of `n_test_groups` as test sets, producing many OOS paths.
- **Purge:** drop training observations whose label/holding window overlaps the test window.
- **Embargo:** additionally drop a fraction of training samples immediately after each test
  block to kill serial-correlation leakage (López de Prado, *Advances in Financial ML*, ch. 7).
- Implemented as index-splitters over the calendar; engine-agnostic (drives either engine).

---

## 2. Overfitting statistics + verdict

```python
def pbo(in_sample_perf: np.ndarray, oos_perf: np.ndarray) -> float       # 0..1
def deflated_sharpe(sr, n_trials, skew, kurt, n_obs) -> float            # prob SR>0 real
def min_backtest_length(target_sr, n_trials) -> float                     # years
def probabilistic_sharpe(sr, sr_benchmark, skew, kurt, n_obs) -> float
```

- **PBO (Probability of Backtest Overfitting):** combinatorially split the trials matrix into
  IS/OOS, measure how often the IS-best config underperforms OOS-median; high PBO ⇒ overfit.
- **DSR (Deflated Sharpe Ratio):** deflates the observed Sharpe for the number of trials and
  non-normal moments — directly counters the parameter-sweep multiple-testing problem (the
  sweep count from component 04 feeds `n_trials`).
- **Minimum backtest length** and **PSR** round out the Bailey/López de Prado toolkit.
- All formulas cited inline to public papers; no restricted code reused.

**Verdict thresholds** populate `ValidationReport.verdict`:

| Verdict | Condition (default thresholds) |
|---|---|
| `robust` | PBO < 0.2 **and** DSR > 0.95 **and** OOS Sharpe > 0 |
| `fragile` | 0.2 ≤ PBO < 0.5 **or** DSR in [0.5, 0.95] |
| `overfit` | PBO ≥ 0.5 **or** DSR < 0.5 **or** OOS Sharpe ≤ 0 |

Thresholds are config-overridable; the report records the inputs so the verdict is auditable.

---

## 3. `ValidationReport` population

```python
class ValidationReport(Data):
    method: Literal["wfo", "cpcv"]
    folds: list[FoldResult]
    oos_metrics: PerformanceMetrics       # aggregated OOS (component 07)
    pbo: float
    deflated_sharpe: float
    min_backtest_length_years: float
    verdict: Literal["robust", "fragile", "overfit"]
    thresholds: dict[str, float]
```

- Each fold runs through the normal engine + analytics path, so OOS metrics reuse component 07.
- Surfaced via `obb.backtest.validate(...)` (component 09).

---

## Acceptance mapping (#45)

| Acceptance criterion | Satisfied by |
|---|---|
| WFO + CPCV with purge/embargo | §1 |
| PBO / DSR / min backtest length | §2 |
| Verdict thresholds | §2 table |
| ValidationReport schema | §3 |
| No restricted (mlfinlab) code | §1/§2 (re-implemented from public papers) |
