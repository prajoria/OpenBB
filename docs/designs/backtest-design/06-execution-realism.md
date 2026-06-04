# 06 — Execution Realism Model

**GitHub:** [#43](https://github.com/prajoria/OpenBB/issues/43) · **Depends on:** [#39](https://github.com/prajoria/OpenBB/issues/39)
**Beads:** OpenBB-d49, OpenBB-2qt, OpenBB-urr

Pluggable execution components (`engine/execution.py`) implementing the `Broker` Protocol
(component 02). **Both engines call the same `Broker`** — this is what makes the
reconciliation gate (component 04/05) meaningful and prevents same-bar look-ahead.

---

## 1. Commission + slippage catalog

```python
class Commission:
    """Implements Broker.commission()."""
    @staticmethod
    def of(model: CommissionModel) -> "Commission": ...

    def cost(self, qty: Decimal, price: Decimal) -> Decimal:
        # per_share: |qty| * value
        # flat:      value
        # percent:   |qty * price| * value
        # tiered:    step function by monthly volume
        # then max(cost, min_per_trade)
        ...

class Slippage:
    """Implements Broker.slippage()."""
    def cost(self, qty: Decimal, price: Decimal, bar: Bar) -> Decimal:
        # fixed_bps:    price * value/1e4 * sign(qty)
        # volume_share: price * impact_coef * (|qty| / bar.volume)   (price impact)
        # spread:       price * (bar.spread_bps/1e4) / 2
        ...
```

| Model | Options | Default |
|---|---|---|
| Commission | per-share, flat, percent, tiered | flat `0` (Fidelity-like zero-commission equities) |
| Slippage | fixed_bps, volume_share, spread | fixed_bps `0` (conservative; user opts into impact) |

All money math is `Decimal`. Slippage always **worsens** the fill (buys fill higher, sells
lower) — never improves it.

---

## 2. Fill logic + order types

```python
class FillModel:
    kind: Literal["next_bar_open", "vwap", "limit"] = "next_bar_open"
    limit_timeout_bars: int = 1

    def fill(self, orders: pd.DataFrame, bar_t: Bar, bar_t1: Bar) -> list[Trade]:
        # next_bar_open (default): order placed on bar t fills at bar t+1 OPEN
        # vwap:  fills at bar t+1 vwap (approx (h+l+2c)/4 if no vwap field)
        # limit: fills only if t+1 trades through the limit within timeout, else cancel
        ...
```

- **Look-ahead prevention:** in the event-driven engine, orders submitted on bar *t* fill at
  bar *t+1* by construction. The vectorized engine enforces the identical rule via mandatory
  `signal.shift(1)` before PnL, validated by the reconciliation gate.
- **Partial fills:** `volume_share` slippage can cap fill quantity at a configurable fraction
  of `bar.volume` (default 10%); unfilled remainder rolls to the next bar or cancels per order
  TIF.

---

## 3. Borrow/short costs + constraints

```python
class ShortModel:
    borrow_fee_bps_annual: Decimal = Decimal("0")
    require_locate: bool = False
    hard_to_borrow: set[str] = set()        # symbols that cannot be shorted

class Constraints:
    espp_lockup: dict[str, date]            # symbol -> earliest sellable date
    tax_lot_method: Literal["fifo", "lifo", "specific_id"] = "fifo"
    restricted: set[str] = set()            # cannot trade at all
    max_position_pct: float = 1.0           # cap per-symbol weight
```

- **Borrow cost** accrues daily on short market value at `borrow_fee_bps_annual / 252`.
- **ESPP lockup / restricted list:** orders violating a constraint are rejected by the broker
  before fill and logged (no silent drop); the engine records a `rejected_orders` count.
- **Tax-lot accounting** selects lots per method on sells; relevant for the personal-portfolio
  seeded backtests (privacy rules: lot detail never leaves local context).
- **Constraints are enforced in `Broker.fill`** so both engines honor them identically.

---

## 4. Defaults summary

| Component | Default | Rationale |
|---|---|---|
| Commission | flat `0` | matches zero-commission equities |
| Slippage | fixed_bps `0` | conservative; explicit opt-in to impact |
| Fill | next_bar_open | structurally prevents same-bar look-ahead |
| Short | disabled (no borrow, no locate) | long-only unless enabled |
| Tax lot | FIFO | simplest correct default |

---

## Acceptance mapping (#43)

| Acceptance criterion | Satisfied by |
|---|---|
| Broker/fill interface | §2 (`FillModel`), implements `Broker` from component 02 |
| Commission + slippage model catalog | §1 |
| Configuration surface | §1–§3 model classes + component 02 CommissionModel/SlippageModel |
| Defaults documented | §4 |
| Look-ahead prevention | §2 (next-bar-open + shift(1) parity) |
| Borrow/short + portfolio constraints | §3 |
