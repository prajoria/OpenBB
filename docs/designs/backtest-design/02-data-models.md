# 02 — Core Data Models & Interface Contracts

**GitHub:** [#39](https://github.com/prajoria/OpenBB/issues/39) · **Depends on:** [#38](https://github.com/prajoria/OpenBB/issues/38)
**Beads:** OpenBB-bfk, OpenBB-cft, OpenBB-i8a

The canonical Pydantic `Data` models and `Protocol` interfaces shared by every other
component. `models.py` and `interfaces.py` are leaf modules (no intra-package imports).

---

## 1. Data models (`models.py`)

All inherit `openbb_core.provider.abstract.data.Data`. Money is `Decimal`; ratios are
`float`. Field descriptions omitted here for brevity but required in code.

```python
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional
from pydantic import Field, field_validator, model_validator
from openbb_core.provider.abstract.data import Data

EngineName = Literal["vectorized", "event", "auto"]
Frequency  = Literal["daily", "hourly", "minute"]
Side       = Literal["buy", "sell"]
Verdict    = Literal["robust", "fragile", "overfit"]


class CommissionModel(Data):
    kind: Literal["per_share", "flat", "percent", "tiered"] = "flat"
    value: Decimal = Decimal("0")
    min_per_trade: Decimal = Decimal("0")


class SlippageModel(Data):
    kind: Literal["fixed_bps", "volume_share", "spread"] = "fixed_bps"
    value: Decimal = Decimal("0")            # bps or share-of-volume coefficient


class BacktestConfig(Data):
    strategy: str
    universe: list[str]
    start: date
    end: date
    engine: EngineName = "auto"
    initial_cash: Decimal = Decimal("100000")
    frequency: Frequency = "daily"
    calendar: str = "XNYS"
    commission: CommissionModel = Field(default_factory=CommissionModel)
    slippage: SlippageModel = Field(default_factory=SlippageModel)
    benchmark: Optional[str] = "SPY"
    seed: int = 0
    compute: ComputeConfig = Field(default_factory=ComputeConfig)  # device/precision (component 13)

    @model_validator(mode="after")
    def _check_dates(self) -> "BacktestConfig":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if not self.universe:
            raise ValueError("universe must be non-empty")
        return self


class Trade(Data):
    timestamp: datetime
    symbol: str
    side: Side
    quantity: Decimal
    price: Decimal
    commission: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")


class EquityPoint(Data):
    date: datetime
    equity: Decimal
    cash: Decimal
    exposure: float                          # net exposure fraction [-1..1+]


class PositionSnapshot(Data):
    date: datetime
    symbol: str
    quantity: Decimal
    market_value: Decimal
    weight: float


class PerformanceMetrics(Data):
    cagr: float; sharpe: float; sortino: float; calmar: float
    max_drawdown: float; volatility: float
    var_95: float; cvar_95: float
    win_rate: float; profit_factor: float; turnover: float
    beta: Optional[float] = None
    alpha: Optional[float] = None


class BacktestResult(Data):
    equity_curve: list[EquityPoint]
    trades: list[Trade]
    positions: list[PositionSnapshot]
    metrics: PerformanceMetrics
    engine_used: str
    config: BacktestConfig


class ValidationReport(Data):
    method: Literal["wfo", "cpcv"]
    in_sample: PerformanceMetrics
    out_of_sample: PerformanceMetrics
    pbo: float                               # [0,1]
    deflated_sharpe: float
    n_trials: int
    verdict: Verdict

    @field_validator("pbo")
    @classmethod
    def _pbo_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("pbo must be in [0,1]")
        return v
```

Auxiliary result models referenced by the API surface (component 09): `SweepResult`,
`FactorPanel`, `FactorReport`, `TearSheet`, `ReconcileReport` — defined alongside but
omitted here; each is a `Data` subclass with the same Decimal/float discipline.

---

## 2. Interface contracts (`interfaces.py`)

```python
from typing import Protocol, runtime_checkable
import pandas as pd
from openbb_backtest.models import BacktestConfig, BacktestResult, Trade


@runtime_checkable
class Strategy(Protocol):
    """Runs identically in both engines. MUST only use data up to the current bar."""
    id: str
    def generate(self, data: "MarketData") -> pd.DataFrame:
        """Return per-symbol target weights or signals indexed by symbol.
        Columns: ['weight'] (target) OR ['signal'] in {-1,0,1}."""
        ...


@runtime_checkable
class DataFeed(Protocol):
    """Point-in-time market data access; never returns future bars."""
    def history(self, symbols: list[str], end: pd.Timestamp, lookback: int) -> pd.DataFrame: ...
    def sessions(self, start, end) -> pd.DatetimeIndex: ...


@runtime_checkable
class Broker(Protocol):
    """Applies execution realism: turns target orders into filled Trades."""
    def fill(self, orders: pd.DataFrame, bar: "Bar") -> list[Trade]: ...
    def commission(self, qty, price) -> "Decimal": ...
    def slippage(self, qty, price, bar) -> "Decimal": ...


@runtime_checkable
class Engine(Protocol):
    """Both vectorized and event-driven engines implement this."""
    name: str
    def run(self, strategy: Strategy, config: BacktestConfig,
            feed: DataFeed, broker: Broker) -> BacktestResult: ...
```

**Design rationale**

- `Strategy.generate` returns a DataFrame (not engine-specific objects) so the same
  strategy feeds both the vectorized matrix path and the event-driven loop.
- `Broker` is the single seam where execution realism (component 06) is injected; both
  engines call it identically, which is what makes the reconciliation gate meaningful.
- `Engine` is a Protocol, so optional adapters (component 11) satisfy it without inheriting
  any base class — keeping optional deps out of the core import graph.

---

## 3. Serialization & OBBject round-trip rules

- Every model is a `Data` subclass → automatically wrapped in `OBBject[Model]` by the
  router and serializable to JSON for REST/CLI.
- **Decimal** fields serialize to JSON numbers via Pydantic's `Decimal` support; the REST
  layer uses string encoding for Decimal to avoid float drift (configured in model
  `model_config = ConfigDict(ser_json_inf_nan='constants')` + Decimal-as-str on the API).
- **datetime/date** serialize as ISO-8601; the bundle stores tz-aware UTC timestamps and
  the calendar layer localizes for display only.
- Round-trip invariant (tested in component 12): `Model(**m.model_dump()) == m` for every
  result model, ensuring Python ↔ REST ↔ CLI equivalence.

---

## Acceptance mapping (#39)

| Acceptance criterion | Satisfied by |
|---|---|
| All models defined (fields, types, validators, defaults) | §1 |
| Engine/strategy/broker protocols specified | §2 |
| Serialization rules documented | §3 |
| Decimal-for-money discipline | §1 (CommissionModel, Trade, EquityPoint, etc.) |
| No-cycle leaf-module guarantee | §0 intro (models/interfaces import nothing intra-package) |
