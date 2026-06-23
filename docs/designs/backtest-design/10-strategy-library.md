# 10 — Strategy Library & Plugin Mechanism

**GitHub:** [#47](https://github.com/prajoria/OpenBB/issues/47) · **Depends on:** [#41](https://github.com/prajoria/OpenBB/issues/41), [#42](https://github.com/prajoria/OpenBB/issues/42)
**Beads:** OpenBB-m3w, OpenBB-3u4

The `strategies/` package: a small set of base templates plus reference strategies that run
**unchanged on both engines** via the `Strategy` Protocol (component 02).

---

## 1. Base templates + lifecycle

```python
class Strategy(Protocol):                 # from interfaces.py (component 02)
    def initialize(self, ctx: StrategyContext) -> None: ...
    def generate(self, data: MarketData) -> dict[str, float]:   # symbol -> target weight
        ...
    def finalize(self, ctx: StrategyContext) -> None: ...
```

Concrete bases reduce boilerplate:

| Base | For |
|---|---|
| `SignalStrategy` | per-asset signal → weight (time-series strategies) |
| `CrossSectionalStrategy` | rank a universe each rebalance (factor strategies) |
| `WeightStrategy` | directly emit a target-weight vector (allocation strategies) |

- `generate()` only ever sees data up to the current bar (`MarketData` is a windowed view);
  the **shift(1)** / next-bar-open discipline lives in the engines, not the strategy, so the
  same code is look-ahead-free in both.
- `StrategyContext` exposes config, calendar, and the `Broker` (for constraints), never raw
  account/lot data.

---

## 2. Plugin mechanism

```python
@register_strategy("momentum_12_1")
class Momentum12_1(CrossSectionalStrategy): ...
```

- A decorator registry (`strategies/registry.py`) maps a string name → class; `obb.backtest.run`
  accepts either a `Strategy` instance or a registered name.
- Third-party strategies register via the same decorator from any importable module; an optional
  entry-point group (`openbb_backtest_strategies`) auto-discovers installed plugins.
- Parameters are passed as a validated `params: dict` (or a strategy-specific `Data` config),
  keeping the sweep API (component 04) able to enumerate them.

---

## 3. Reference catalog

Each ships with a docstring, default params, and a golden smoke-test fixture:

| Strategy | Base | Core logic |
|---|---|---|
| `buy_and_hold` | WeightStrategy | static equal/target weights (baseline benchmark) |
| `momentum_12_1` | CrossSectional | rank by 12-month return skipping last month, long top decile |
| `mean_reversion` | Signal | z-score of price vs MA, fade extremes |
| `factor_tilt` | CrossSectional | tilt by Analysis/ value+quality factor scores (Pipeline) |
| `vol_targeting` | Weight | scale gross exposure to a target annualized vol |
| `risk_parity` | Weight | inverse-vol / HRP allocation across the universe |

- `factor_tilt` and other cross-sectional strategies reuse the Pipeline factors (component 05),
  demonstrating the Analysis/ → backtest bridge.
- `risk_parity` uses HRP (López de Prado) — re-implemented, no restricted deps.
- These double as integration fixtures for component 12 (golden-result tests).

---

## Acceptance mapping (#47)

| Acceptance criterion | Satisfied by |
|---|---|
| Base templates / authoring model | §1 |
| Runs on both engines unchanged | §1 (engine owns look-ahead discipline) |
| Plugin/registration mechanism | §2 |
| Reference strategy set | §3 |
| Factor/Analysis integration example | §3 (`factor_tilt`) |
