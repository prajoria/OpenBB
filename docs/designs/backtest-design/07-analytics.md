# 07 — Performance Analytics & Reporting

**GitHub:** [#44](https://github.com/prajoria/OpenBB/issues/44) · **Depends on:** [#41](https://github.com/prajoria/OpenBB/issues/41), [#42](https://github.com/prajoria/OpenBB/issues/42)
**Beads:** OpenBB-95d, OpenBB-u11

The analytics layer (`analytics/`) turns an equity curve / returns series into
`PerformanceMetrics` and full tear sheets. All libraries are Apache-2.0 (core-eligible).

---

## 1. Metric catalog → `PerformanceMetrics`

`analytics/metrics.py` wraps `empyrical-reloaded`. Each `PerformanceMetrics` field maps to a
canonical primitive (annualization uses the config calendar's sessions/year):

| Field | Source | Notes |
|---|---|---|
| `cagr` | `empyrical.annual_return` | geometric |
| `sharpe` | `empyrical.sharpe_ratio` | rf from config (default 0) |
| `sortino` | `empyrical.sortino_ratio` | downside dev |
| `calmar` | `empyrical.calmar_ratio` | CAGR / |MDD| |
| `max_drawdown` | `empyrical.max_drawdown` | negative fraction |
| `volatility` | `empyrical.annual_volatility` | annualized |
| `var_95` | `empyrical.value_at_risk(cutoff=0.05)` | historical |
| `cvar_95` | `empyrical.conditional_value_at_risk(cutoff=0.05)` | expected shortfall |
| `win_rate` | in-house from `trades` | wins / total round-trips |
| `profit_factor` | in-house from `trades` | gross profit / gross loss |
| `turnover` | in-house from weight deltas | annualized |
| `beta` | `empyrical.beta` vs benchmark | None if no benchmark |
| `alpha` | `empyrical.alpha` vs benchmark | annualized |

```python
def compute_metrics(returns: pd.Series, benchmark: pd.Series | None,
                    trades: list[Trade], sessions_per_year: int) -> PerformanceMetrics:
    ...
```

- Inputs come from either engine's `BacktestResult.equity_curve` (→ returns) so metrics are
  engine-agnostic.
- `ffn` provides supplementary stat helpers where empyrical lacks a primitive.

---

## 2. Tear sheets + export

```python
class TearSheet(Data):
    metrics: PerformanceMetrics
    rolling_sharpe: list[float]
    drawdown_periods: list[DrawdownPeriod]
    monthly_returns: list[MonthlyReturn]
    html_path: str | None            # saved artifact
    benchmark_relative: BenchmarkStats | None
```

- **pyfolio-reloaded** produces the full institutional tear sheet (returns, rolling stats,
  drawdown periods, exposure, round-trip analysis) → structured into `TearSheet`.
- **quantstats** produces a one-call HTML report for quick sharing.
- **Artifacts** (HTML/PNG) save under `Analysis/exports/` (existing export convention); the
  `Data` model carries only the path, never embeds large blobs.
- **Benchmark-relative:** alpha, beta, information ratio vs `SPY`/sector ETF (reuses the
  Phase-6 peer-relative concept). `BenchmarkStats` holds these.
- **Privacy:** tear sheets emitted outward use normalized returns only — no dollar amounts,
  account numbers, or lot detail (fork privacy rule).

---

## 3. Integration points

- Called by `obb.backtest.tearsheet(returns, benchmark=...)` (component 09) and automatically
  attached to `BacktestResult.metrics` on every `run`.
- Factor diagnostics (Alphalens IC/quantile/decay) live in the pipeline path (component 05/09
  `factor_eval`), not here; this component is portfolio/return analytics.

---

## Acceptance mapping (#44)

| Acceptance criterion | Satisfied by |
|---|---|
| Metric catalog mapped to PerformanceMetrics | §1 table |
| Reporting/tearsheet spec | §2 (`TearSheet` model) |
| Export formats | §2 (HTML/PNG under Analysis/exports) |
| Library selection justified | §1/§2 (empyrical/pyfolio/quantstats/ffn — all Apache/MIT) |
| Benchmark-relative metrics | §2 (`BenchmarkStats`) |
