# 05 — Event-Driven Engine (zipline-reloaded + Pipeline)

**GitHub:** [#42](https://github.com/prajoria/OpenBB/issues/42) · **Depends on:** [#39](https://github.com/prajoria/OpenBB/issues/39), [#40](https://github.com/prajoria/OpenBB/issues/40), [#43](https://github.com/prajoria/OpenBB/issues/43)
**Beads:** OpenBB-3e8, OpenBB-5wj, OpenBB-dqe

The **source-of-truth** engine (`engine/event_driven.py`). Wraps `zipline-reloaded`
(Apache-2.0) behind the `Engine` Protocol. Look-ahead-free by construction; provides the
cross-sectional Pipeline.

---

## 1. Sim wrapper + Strategy/Broker adapter

```python
class EventDrivenEngine:           # implements interfaces.Engine
    name = "event"

    def run(self, strategy, config, feed, broker) -> BacktestResult:
        from zipline import run_algorithm           # lazy import (heavy)
        perf = run_algorithm(
            start=ts(config.start), end=ts(config.end),
            initialize=self._make_initialize(strategy, broker, config),
            handle_data=self._make_handle_data(strategy),
            capital_base=float(config.initial_cash),
            data_frequency=_freq(config.frequency),
            bundle=config_bundle_name(config),       # registered in §3
            trading_calendar=get_calendar(config.calendar),
        )
        return self._normalize(perf, config)         # §3
```

**Adapter mapping**

| Our abstraction | zipline hook |
|---|---|
| `Strategy.generate` → target weights | `handle_data`: `order_target_percent` per symbol |
| `Broker.commission` (component 06) | `set_commission(PerShare/PerTrade)` in `initialize` |
| `Broker.slippage` (component 06) | `set_slippage(FixedBasisPoints/VolumeShareSlippage)` |
| Next-bar-open fill | zipline's native t→t+1 fill semantics (already look-ahead-free) |
| Constraints (ESPP/restricted) | order wrapper rejects disallowed orders before submission |

- Our `CommissionModel`/`SlippageModel` are translated to zipline's built-in classes where they
  map 1:1; custom models (tiered, spread) use a thin `zipline.finance` subclass that delegates
  to our `Broker` so **the cost numbers are identical to the vectorized engine**.
- The strategy object is unchanged — `generate()` is called inside `handle_data` with a
  `MarketData` view that only exposes data up to the current bar.

---

## 2. Pipeline API integration

```python
def pipeline(factors: dict[str, Factor], universe, start, end) -> FactorPanel:
    from zipline.pipeline import Pipeline, CustomFactor
    pipe = Pipeline(columns={name: f.to_zipline() for name, f in factors.items()},
                    screen=universe.to_zipline_filter())
    result = run_pipeline(pipe, start, end)       # (date, asset) MultiIndex
    return FactorPanel.from_frame(result)
```

- The existing `Analysis/` Phase-2..5 computations (fundamentals, technicals, valuation, risk)
  become reusable `Factor` nodes (component design references `pipeline/factor.py`), each a
  `CustomFactor` with a declared `window_length` and `inputs`.
- Output feeds `alphalens-reloaded` for IC / quantile-return / decay diagnostics (component 07).
- Pipeline computes **cross-sectionally per session** with built-in lookback windows and NaN
  handling, generalizing single-stock scores to N-stock rankings.

---

## 3. Bundle registration + result normalization

```python
# data/bundle.py — register our fmp_cached bundle with zipline
from zipline.data.bundles import register

@register("fmp_cached", calendar_name="XNYS")
def fmp_cached_ingest(environ, asset_db_writer, minute_bar_writer,
                      daily_bar_writer, adjustment_writer, calendar, ...):
    # stream OHLCV from our columnar bundle (component 03) into zipline writers
    # write splits/dividends into adjustment_writer
    ...
```

- The bundle (component 03) is the single ingest source; we register a zipline bundle that
  **reads our parquet store**, so there is no second download and adjustments stay consistent.
- **Result normalization** maps zipline's `perf` DataFrame into our canonical models:

| zipline `perf` column | → `BacktestResult` |
|---|---|
| `portfolio_value` | `equity_curve[].equity` |
| `ending_cash` | `equity_curve[].cash` |
| `transactions` | `trades[]` (→ `Trade`) |
| `positions` | `positions[]` (→ `PositionSnapshot`) |
| computed from returns | `metrics` (`PerformanceMetrics`, via component 07) |

- `engine_used="event"`; the original `BacktestConfig` is echoed back for reproducibility.

---

## Acceptance mapping (#42)

| Acceptance criterion | Satisfied by |
|---|---|
| Adapter contract | §1 (implements `Engine`; Strategy/Broker mapping table) |
| Pipeline integration | §2 |
| Bundle registration | §3 (`@register("fmp_cached")`) |
| Mapping zipline outputs to canonical models | §3 normalization table |
| Look-ahead-free | §1 (native t→t+1 fill) |
| Cost parity with vectorized engine | §1 (shared `Broker` delegation) |
