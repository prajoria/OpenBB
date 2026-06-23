# Proposal: Unified Quant Analysis Module for the OpenBB Platform

**Status:** Draft / Proposal
**Author:** Quant working group
**Companion document:** [`docs/Tools/Quant-Strategies-Guide.md`](../Tools/Quant-Strategies-Guide.md)
**Target component:** OpenBB Platform extension (`openbb-quant`)
**Date:** 2026-06-02

---

## 1. Summary

The [Comprehensive Quant Strategies & Algorithms Guide](../Tools/Quant-Strategies-Guide.md)
surveys ~453 quant repositories and shows that the open-source quant landscape is
**broad but fragmented**: every capability (volatility, portfolio optimization,
backtesting, factor research, options pricing) lives in its own library with its own
API conventions, data shapes, and idioms. OpenBB already ships several adjacent
extensions (`quantitative`, `technical`, `derivatives`, `portfolio`, `econometrics`,
`famafrench`), but there is **no single, consistent surface** for end-to-end quant
strategy work — sourcing data, generating signals, sizing positions, backtesting, and
evaluating performance — all through one idiomatic `obb.*` namespace.

This proposal defines a new first-party extension, **`openbb-quant`**, that unifies the
best-of-breed techniques identified in the guide into a **single, consistent strategy
framework** plus a curated **collection of reference strategies**, exposed through the
standard OpenBB Router / `OBBject` / `Data` conventions so they compose with the rest
of the platform exactly like every other command.

**Design goal in one sentence:** *Give users one consistent way to define, run, size,
backtest, and evaluate a quant strategy in OpenBB — using the same command grammar,
data models, and provider plumbing as the rest of the platform.*

---

## 2. Goals and non-goals

### Goals
- **G1 — One unified namespace.** A single `obb.quant.*` tree covering signals,
  sizing, backtest, optimize, risk, and evaluate.
- **G2 — Consistent OpenBB code style.** `Router`, `@router.command`,
  `OBBject[Model]`, `list[Data]` + `target` inputs, `APIEx`/`PythonEx` examples,
  lazy imports, sub-router composition — identical to the existing `quantitative`
  extension.
- **G3 — A unified strategy abstraction.** One `Strategy` protocol so any strategy
  (momentum, mean-reversion, factor, vol-targeting, custom) is invoked the same way.
- **G4 — A curated strategy collection.** A small, high-quality set of reference
  strategies drawn from the guide's §18 shortlist, usable out of the box.
- **G5 — Composability.** Outputs of one command (signals, weights, returns) are
  valid inputs to the next, all as `Data`/`OBBject` so they round-trip through the
  REST API, Python, and the CLI unchanged.
- **G6 — Permissive dependencies only.** Depend on or re-implement only the
  permissively-licensed sources flagged in the guide (§19). No restricted code.

### Non-goals
- **NG1 — Not a broker / live execution engine.** Order routing stays out of scope
  (trading bots remain external; see guide §15).
- **NG2 — Not a new data provider.** Reuse existing OpenBB providers (`fmp`,
  `fmp_cached`, `yfinance`, etc.) for prices/fundamentals.
- **NG3 — Not a re-implementation of restricted libraries.** `rateslib`, full
  `mlfinlab`, `gs-quant` are study-only (guide §19); re-implement from public papers.
- **NG4 — No GPU/deep-RL training pipeline in v1.** ML/RL (guide §9) is a later phase.

---

## 3. Where this fits among existing extensions

| Existing extension | Keep / relationship to `openbb-quant` |
|---|---|
| `quantitative` | Keep. Low-level stats (normality, unit-root, rolling, performance metrics). `openbb-quant` *consumes* these, does not duplicate them. |
| `technical` | Keep. Indicator computation (RSI, MACD…). `openbb-quant` signal layer wraps these as strategy primitives. |
| `derivatives` | Keep. Options chains/pricing. `openbb-quant` references for options-based strategies, not duplicated. |
| `portfolio` | Keep. Holdings/attribution. `openbb-quant.optimize` produces weights that `portfolio` can ingest. |
| `econometrics` / `famafrench` | Keep. Regression + factor data. `openbb-quant.factor` builds on these. |

`openbb-quant` is an **orchestration and strategy layer** on top of these — it adds the
missing "strategy → sizing → backtest → evaluation" workflow, not new low-level math
that already exists elsewhere.

---

## 4. Proposed extension layout

Mirrors the on-disk shape of the existing `quantitative` extension (sub-router per
domain, lazy imports, `models.py`, `helpers.py`, `py.typed`):

```
openbb_platform/extensions/quant/
├── openbb_quant/
│   ├── __init__.py
│   ├── quant_router.py          # top-level Router; includes sub-routers
│   ├── models.py                # Pydantic Data models (Signal, Weights, BacktestResult…)
│   ├── helpers.py               # shared df<->Data plumbing, return calc, alignment
│   ├── strategy.py              # Strategy protocol + registry
│   ├── py.typed
│   ├── signals/                 # signal generation (momentum, mean-rev, factor, vol)
│   │   ├── __init__.py
│   │   └── signals_router.py
│   ├── sizing/                  # position sizing (vol-target, Kelly, equal/inverse-vol)
│   │   ├── __init__.py
│   │   └── sizing_router.py
│   ├── optimize/                # portfolio optimization (MV, HRP, risk-parity, CVaR)
│   │   ├── __init__.py
│   │   └── optimize_router.py
│   ├── backtest/                # vectorized backtest + anti-overfit validation
│   │   ├── __init__.py
│   │   └── backtest_router.py
│   ├── risk/                    # VaR/CVaR, drawdown, exposure
│   │   ├── __init__.py
│   │   └── risk_router.py
│   ├── evaluate/                # tear-sheet metrics, IC/factor eval, PBO/DSR
│   │   ├── __init__.py
│   │   └── evaluate_router.py
│   └── strategies/              # the curated reference-strategy collection
│       ├── __init__.py
│       └── library.py
├── tests/
├── README.md
└── pyproject.toml               # entry point: openbb_core_extension
```

`pyproject.toml` registers the extension exactly like `quantitative` does:

```toml
[tool.poetry.plugins."openbb_core_extension"]
quant = "openbb_quant.quant_router:router"
```

So everything appears under `obb.quant.*` after `openbb.build()`.

---

## 5. The unified strategy abstraction

The core of "a single unified strategy or collection of strategies usable in a
consistent fashion" is one protocol every strategy implements, plus a registry so
strategies are addressable by name through a normal OpenBB command.

```python
# openbb_quant/strategy.py
from typing import Protocol, runtime_checkable
import pandas as pd


@runtime_checkable
class Strategy(Protocol):
    """Unified contract every OpenBB quant strategy implements.

    A strategy maps a panel of market data to a panel of target signals/weights.
    Keeping the contract this small is what lets every strategy — built-in or
    user-supplied — run through the exact same `obb.quant.backtest.run` command.
    """

    name: str

    def generate(self, prices: pd.DataFrame, **params) -> pd.DataFrame:
        """Return signals or target weights indexed like ``prices``.

        Parameters
        ----------
        prices : pd.DataFrame
            Wide price panel (index=date, columns=symbol).
        **params :
            Strategy-specific hyperparameters (lookbacks, thresholds…).

        Returns
        -------
        pd.DataFrame
            Target weights/signals, same index, columns ⊆ ``prices.columns``.
        """
        ...


_REGISTRY: dict[str, "Strategy"] = {}


def register(strategy: "Strategy") -> "Strategy":
    """Register a strategy so it is addressable by ``strategy.name``."""
    _REGISTRY[strategy.name] = strategy
    return strategy


def get_strategy(name: str) -> "Strategy":
    """Look up a registered strategy by name."""
    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown strategy '{name}'. Available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]


def available_strategies() -> list[str]:
    """List registered strategy names (powers ``obb.quant.strategies.list``)."""
    return sorted(_REGISTRY)
```

Because every strategy honors the same `generate()` contract, the backtest, sizing,
and evaluation commands never special-case a particular strategy — the abstraction is
what makes the whole module "consistent."

---

## 6. Data models (`models.py`)

All inputs/outputs are `Data` subclasses so they serialize across REST/Python/CLI
identically to the rest of the platform:

```python
# openbb_quant/models.py
from openbb_core.provider.abstract.data import Data
from pydantic import Field


class StrategySignal(Data):
    """A dated, per-symbol target signal or weight produced by a strategy."""

    date: str = Field(description="Observation date (ISO 8601).")
    symbol: str = Field(description="Ticker symbol.")
    signal: float = Field(description="Target signal/weight for the symbol.")


class PortfolioWeights(Data):
    """Optimized target weights for a set of assets."""

    symbol: str = Field(description="Ticker symbol.")
    weight: float = Field(description="Target portfolio weight (fraction of NAV).")


class BacktestResult(Data):
    """Per-period backtest output: returns, equity curve, turnover."""

    date: str = Field(description="Period date (ISO 8601).")
    strategy_return: float = Field(description="Period return of the strategy.")
    equity: float = Field(description="Cumulative equity (starting at 1.0).")
    turnover: float = Field(description="Fraction of book traded this period.")


class StrategyMetrics(Data):
    """Headline evaluation metrics for a backtest or live track record."""

    cagr: float = Field(description="Compound annual growth rate.")
    volatility: float = Field(description="Annualized volatility.")
    sharpe: float = Field(description="Annualized Sharpe ratio.")
    sortino: float = Field(description="Annualized Sortino ratio.")
    max_drawdown: float = Field(description="Maximum peak-to-trough drawdown.")
    calmar: float = Field(description="CAGR / |max drawdown|.")
    deflated_sharpe: float = Field(
        default=0.0,
        description="Deflated Sharpe ratio (overfitting-adjusted; López de Prado).",
    )
```

---

## 7. Command surface (the unified API)

Every command follows the house style observed in `quantitative_router.py`:
`@router.command(methods=["POST"], examples=[PythonEx(...), APIEx(...)])`, returning
`OBBject[Model]`, lazy imports inside the function body.

### 7.1 Top-level router

```python
# openbb_quant/quant_router.py
from openbb_core.app.router import Router

from openbb_quant.backtest.backtest_router import router as backtest_router
from openbb_quant.evaluate.evaluate_router import router as evaluate_router
from openbb_quant.optimize.optimize_router import router as optimize_router
from openbb_quant.risk.risk_router import router as risk_router
from openbb_quant.signals.signals_router import router as signals_router
from openbb_quant.sizing.sizing_router import router as sizing_router

router = Router(prefix="", description="Unified quant strategy framework for OpenBB.")
router.include_router(signals_router)
router.include_router(sizing_router)
router.include_router(optimize_router)
router.include_router(backtest_router)
router.include_router(risk_router)
router.include_router(evaluate_router)
```

### 7.2 Resulting command tree

| Command | Purpose | Backing source (guide §) |
|---|---|---|
| `obb.quant.strategies.list()` | List registered strategies in the collection | this spec §8 |
| `obb.quant.signals.momentum(data, ...)` | Cross-sectional / time-series momentum | §10 `101_formulaic_alphas`, §5 |
| `obb.quant.signals.mean_reversion(data, ...)` | Z-score / Bollinger reversion | §5, §10 |
| `obb.quant.signals.factor(data, factors=...)` | Factor-tilt signals | §10 `alphalens-reloaded`, `famafrench` |
| `obb.quant.signals.volatility_target(data, ...)` | Vol-target overlay signal | §7 `arch`, §11 |
| `obb.quant.sizing.kelly(data, ...)` | Kelly / fractional-Kelly sizing | §11 |
| `obb.quant.sizing.inverse_vol(data, ...)` | Inverse-vol / equal-risk sizing | §4 `Riskfolio-Lib` |
| `obb.quant.optimize.mean_variance(data, ...)` | Markowitz / max-Sharpe | §4 `PyPortfolioOpt` |
| `obb.quant.optimize.hrp(data, ...)` | Hierarchical risk parity | §4 `Riskfolio-Lib`/`skfolio` |
| `obb.quant.optimize.cvar(data, ...)` | CVaR / entropy-pooling optimization | §4 `fortitudo.tech` |
| `obb.quant.backtest.run(data, strategy=...)` | Vectorized backtest of any strategy | §3 `vectorbt`/`pybroker` |
| `obb.quant.risk.var(data, ...)` | Historical / parametric VaR & CVaR | §11 |
| `obb.quant.risk.drawdown(data)` | Drawdown series & stats | §12 `empyrical-reloaded` |
| `obb.quant.evaluate.metrics(data)` | Sharpe/Sortino/Calmar/CAGR tear-sheet | §12 `quantstats`/`empyrical` |
| `obb.quant.evaluate.factor_ic(data, ...)` | Information coefficient / factor decile eval | §10 `alphalens-reloaded` |
| `obb.quant.evaluate.overfit(data, ...)` | PBO / Deflated Sharpe anti-overfit checks | §3 `backtester-mcp` |

### 7.3 Representative command (house-style reference)

```python
# openbb_quant/backtest/backtest_router.py
from openbb_core.app.model.example import APIEx, PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from openbb_core.provider.abstract.data import Data

from openbb_quant.models import BacktestResult

router = Router(prefix="/backtest", description="Strategy backtesting.")


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Backtest the built-in momentum strategy on a price panel.",
            code=[
                "prices = obb.equity.price.historical("
                "'AAPL,MSFT,SPY', provider='fmp_cached').results",
                "obb.quant.backtest.run(data=prices, strategy='momentum', "
                "params={'lookback': 126})",
            ],
        ),
        APIEx(
            parameters={
                "data": APIEx.mock_data("timeseries"),
                "strategy": "momentum",
            }
        ),
    ],
)
def run(
    data: list[Data],
    strategy: str = "momentum",
    params: dict | None = None,
    rebalance: str = "M",
    cost_bps: float = 1.0,
) -> OBBject[list[BacktestResult]]:
    """Backtest any registered strategy over a price panel.

    Parameters
    ----------
    data : list[Data]
        Long or wide price history (date, symbol, close).
    strategy : str
        Registered strategy name (see ``obb.quant.strategies.list``).
    params : dict, optional
        Strategy hyperparameters passed to ``Strategy.generate``.
    rebalance : str
        Rebalance frequency (pandas offset alias, e.g. 'M', 'W').
    cost_bps : float
        Round-trip transaction cost in basis points, applied on turnover.

    Returns
    -------
    OBBject[list[BacktestResult]]
        Per-period returns, equity curve, and turnover.
    """
    # pylint: disable=import-outside-toplevel
    from openbb_quant.helpers import to_wide_prices, apply_costs  # noqa
    from openbb_quant.strategy import get_strategy  # noqa

    prices = to_wide_prices(data)
    strat = get_strategy(strategy)
    weights = strat.generate(prices, **(params or {})).asfreq(rebalance, method="ffill")
    gross = (weights.shift(1) * prices.pct_change()).sum(axis=1)
    net = apply_costs(gross, weights, cost_bps)
    equity = (1 + net).cumprod()
    turnover = weights.diff().abs().sum(axis=1).fillna(0.0)

    results = [
        BacktestResult(
            date=str(idx.date()),
            strategy_return=float(net.loc[idx]),
            equity=float(equity.loc[idx]),
            turnover=float(turnover.loc[idx]),
        )
        for idx in net.index
    ]
    return OBBject(results=results)
```

This is intentionally indistinguishable in style from existing OpenBB commands — same
decorator, same `list[Data]` in / `OBBject[Model]` out, same lazy-import block.

---

## 8. The curated strategy collection

Shipped, ready-to-run strategies registered into the unified registry. Each is a thin,
permissively-sourced implementation that satisfies the `Strategy` protocol:

```python
# openbb_quant/strategies/library.py
import pandas as pd
from openbb_quant.strategy import register


@register
class Momentum:
    """Time-series / cross-sectional momentum (guide §10)."""

    name = "momentum"

    def generate(self, prices: pd.DataFrame, lookback: int = 126,
                 top: int | None = None) -> pd.DataFrame:
        scores = prices.pct_change(lookback)
        ranks = scores.rank(axis=1, ascending=False)
        mask = ranks.le(top) if top else scores.gt(0)
        weights = mask.div(mask.sum(axis=1), axis=0).fillna(0.0)
        return weights


@register
class MeanReversion:
    """Z-score mean reversion (guide §5)."""

    name = "mean_reversion"

    def generate(self, prices: pd.DataFrame, lookback: int = 20,
                 z: float = 1.0) -> pd.DataFrame:
        roll = prices.rolling(lookback)
        zscore = (prices - roll.mean()) / roll.std()
        signal = (-zscore).clip(-1, 1).where(zscore.abs() > z, 0.0)
        return signal.div(signal.abs().sum(axis=1), axis=0).fillna(0.0)


@register
class VolatilityTarget:
    """Inverse-vol weighting toward a target portfolio volatility (guide §7/§11)."""

    name = "vol_target"

    def generate(self, prices: pd.DataFrame, lookback: int = 60,
                 target_vol: float = 0.10) -> pd.DataFrame:
        rets = prices.pct_change()
        inv_vol = 1.0 / rets.rolling(lookback).std()
        raw = inv_vol.div(inv_vol.sum(axis=1), axis=0)
        port_vol = (raw.shift(1) * rets).sum(axis=1).rolling(lookback).std()
        scale = (target_vol / (port_vol * (252 ** 0.5))).clip(upper=1.0)
        return raw.mul(scale, axis=0).fillna(0.0)
```

`obb.quant.strategies.list()` enumerates these; users add their own by calling
`register` on any object satisfying the protocol — and it immediately works with
`obb.quant.backtest.run(strategy="my_strategy")`. **That is the unified, consistent
usage the user asked for.**

---

## 9. Dependencies (permissive only)

Per guide §19, depend on permissively-licensed packages or re-implement from public
papers. Proposed optional dependency groups (kept light; heavy libs are lazy-imported):

| Group | Packages | Used by |
|---|---|---|
| core (required) | `pandas`, `numpy`, `openbb-core`, `openbb-quantitative` | all |
| optimize | `PyPortfolioOpt` **or** `Riskfolio-Lib`, `cvxpy` | `optimize.*` |
| volatility | `arch` | `signals.volatility_target`, `risk.*` |
| evaluate | `empyrical-reloaded`, `quantstats` | `evaluate.*` |
| factor | `alphalens-reloaded` | `evaluate.factor_ic` |
| backtest (optional) | `vectorbt` **or** `pybroker` | advanced `backtest.*` |

The vectorized backtest in §7.3 is dependency-free (pure pandas) so the **core path
works with zero extra installs**; advanced engines are opt-in extras.

**Explicitly excluded** (study-only, guide §19): `rateslib`, full `mlfinlab`,
`gs-quant`.

---

## 10. Consistency & quality guarantees

- **Code style:** Black + Ruff + MyPy + PyDocStyle (repo pre-commit), matching every
  other extension. Docstrings carry `Parameters`/`Returns` sections.
- **Examples:** every command ships `PythonEx` + `APIEx` so it renders in the API docs
  and the reference site like all OpenBB commands.
- **Provider-agnostic:** commands take `list[Data]` (e.g. output of
  `obb.equity.price.historical`), never a hardcoded provider — composes with any.
- **Round-trips:** all I/O is `Data`/`OBBject`, so REST, Python, and CLI behave
  identically.
- **`py.typed`** shipped for downstream type-checking.

---

## 11. Testing strategy

Mirror the `Analysis/` + extension test conventions:

- **Unit tests** (`-m "not integration"`): pure-pandas math — momentum/mean-reversion
  signal shapes, backtest equity/turnover identities, metric formulas vs known values,
  registry behavior. No network.
- **Integration tests** (`-m integration`): end-to-end against `fmp_cached` —
  `historical → signals → backtest → evaluate` on a fixed symbol set; assert metric
  ranges and `OBBject` serialization.
- **Static:** run through repo pre-commit (Black/Ruff/MyPy/PyDocStyle).

Run with the project venv:
```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/quant -m "not integration" -v
```

---

## 12. Phased delivery plan

| Phase | Scope | Exit criteria |
|---|---|---|
| **P1 — Skeleton** | Extension scaffold, `quant_router`, `Strategy` protocol + registry, `models.py`, pyproject entry point, `obb.quant.strategies.list` | `obb.quant` importable after `openbb.build()`; CI green |
| **P2 — Signals + backtest core** | `signals.*` (momentum, mean_reversion, vol_target) + pure-pandas `backtest.run` + curated collection | Unit tests pass; backtest reproduces hand-computed equity curve |
| **P3 — Evaluate + risk** | `evaluate.metrics`/`factor_ic`/`overfit`, `risk.var`/`drawdown` (empyrical/alphalens) | Metrics match reference libs within tolerance |
| **P4 — Optimize + sizing** | `optimize.*` (MV/HRP/CVaR), `sizing.*` (Kelly/inverse-vol) | Weights sum to 1, match library outputs |
| **P5 — Advanced engines** | Optional `vectorbt`/`pybroker` backend behind `backtest` extra; ML/RL strategies (guide §9) | Opt-in extras documented; core path unaffected |

---

## 13. Open questions

> **Moved.** All open questions for the quant/backtest workstream — including the four
> that previously lived here (extension name, backtest engine default, optimizer
> dependency, strategy params typing) — are now consolidated in a single answer
> location: **[`Backtesting-Engine-PRD.md` §19](./Backtesting-Engine-PRD.md#19-open-questions--decisions-needed)**.
> The four questions formerly listed here are **Q7–Q10** in PRD §19.2; answer them inline
> there after each `**Answer:**` marker so every decision lives in one document.

---

## 14. Why this satisfies the request

- **"A Quant analysis module … in a consistent OpenBB code style"** → §4–§7: a real
  extension using the exact `Router`/`@router.command`/`OBBject`/`Data`/`APIEx` idioms
  of the live `quantitative` extension.
- **"A single unified strategy or collection of strategies"** → §5 `Strategy` protocol
  + registry and §8 the curated collection, all invoked identically.
- **"Used with OpenBB in a consistent fashion"** → §7 every capability under one
  `obb.quant.*` tree; §10 consistency guarantees; provider-agnostic `Data` I/O.
- **Grounded in the survey** → every command maps back to a specific guide section and
  the §18 best-of-breed, permissive sources (§19).
```

