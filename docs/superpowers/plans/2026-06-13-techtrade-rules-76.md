# techtrade #76 — EntryExitRule levels + risk-based position sizing (ATR stop / R-target / time-stop)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) tracking. TDD throughout (write failing test → run red → minimal implement → run green → ruff → commit). **Read the locked cross-plan contract first:** `docs/superpowers/plans/2026-06-13-techtrade-pipeline-contract.md` (§1 house rules, §3 "#76 — engine/rules.py", §5 #76 commit manifest). The contract wins over anything here — if they disagree, fix this plan.

**Goal:** Build `engine/rules.py` — the pure, deterministic level-and-size kernel that turns a `MoverSignal` + an entry price + ATR(14) into the four numbers a trade needs: **stop**, **target**, **risk-per-share**, and a risk-budget-honoring **share quantity**. This is the math heart of PRD §13: ATR stop, R-multiple target, and risk-based sizing `qty = floor(risk_budget / (atr_stop_mult · ATR))`. It encodes the **Q6** decision (abstract notional sizing inputs — `account_size: Decimal` + `risk_per_trade: float`, default `Decimal("100000")` / `0.01` — **no personal dollar amounts**). #76 produces *levels and size only*; order legs (#77), paper fills (#78), and the time-stop bar count enforcement (#78 broker loop) consume these outputs downstream. The `max_holding_bars` time stop is *carried by the rule* and surfaced by #77/#78; #76 does not simulate bars.

**Architecture:** A single pure module, `engine/rules.py`, with **four free functions** and no class state. `stop_price` / `target_price` are closed-form level math keyed off `direction` ("long"/"short"/"flat") and the frozen `EntryExitRule`. `position_size` divides a risk budget by per-share risk and floors to whole shares. `apply_rule` is the thin orchestrator that derives direction from `signal.direction`, computes stop → target → qty → risk_per_share, and returns a plain `dict` with keys `{"entry","stop","target","qty","risk_per_share"}`. **No network, no router, no `obb.*` call, no DI seam** (there is no live data here — the entry price and ATR are passed in by #77). Determinism rests on Decimal arithmetic with explicit `Decimal(str(float))` conversion at every float→money boundary, so the unit tests assert exact Decimal values with zero binary-float contamination.

**Tech Stack:** Python 3.10+ (repo targets py310 in `ruff.toml`), **stdlib only** — `decimal` (`Decimal`, `ROUND_DOWN`), `typing` (`Literal`) — plus `openbb_techtrade.models` (`EntryExitRule`, `MoverSignal`) for types. pytest for the unit suite. No pandas, no numpy, no network, no optional deps. (`MoverSignal` is only *constructed* in tests to drive `apply_rule`; the module imports it for the type hint.)

---

## Domain rules locked from PRD §13 (+ §20 Q6, contract §3)

- **Direction sign convention (the rule that everything else hangs off):**
  - **long** → stop **below** entry (`entry − atr_stop_mult·ATR`), target **above** entry (`entry + target_r_multiple·risk_per_share`).
  - **short** → mirrored: stop **above** entry (`entry + atr_stop_mult·ATR`), target **below** entry (`entry − target_r_multiple·risk_per_share`).
  - **flat** → no trade: there is no defensible stop/target for a no-position signal. `stop_price`/`target_price` **raise `ValueError`** on a flat direction (a flat signal must never reach the level math); `apply_rule` handles flat *before* calling them and returns a zero-size dict (see below). Justification: silently returning `entry` as the "stop" would imply `risk_per_share = 0`, which then poisons sizing with a divide-by-zero — far better to make "flat has no levels" an explicit, tested contract and keep the orchestrator the single place that knows flat ⇒ no position.
- **Risk-per-share is the stop distance:** `risk_per_share = |entry − stop| = atr_stop_mult·ATR` (identical for long and short — it is the absolute distance, sign-free). This is the `1R` of the R-multiple system.
- **R-multiple target (§13):** `target = entry ± target_r_multiple · risk_per_share`. With defaults `target_r_multiple = 2.0`, the reward:risk is 2:1.
- **Risk-based sizing (§13, the default sizing mode):** size so the stop-loss equals a fixed risk fraction of a configured notional:
  - `risk_budget = account_size · risk_per_trade`
  - `qty = floor(risk_budget / risk_per_share)` = `floor(risk_budget / (atr_stop_mult·ATR))`
  - returned as a **whole-share `Decimal`** (you cannot buy fractional shares here; floor is the conservative, never-over-risk choice).
- **Q6 sizing inputs (the decision this issue encodes):** sizing is **abstract** — `account_size: Decimal` (default `Decimal("100000")`) and `risk_per_trade: float` (default `0.01`, i.e. 1% of notional per trade). **No personal dollar amounts are emitted**; outward artifacts (the #80 `Recommendation`, the #81 Excel) carry normalized notional, never a real account balance. The defaults are sane placeholders, fully overridable per call.
- **Decimal discipline (contract §1):** every money/quantity value — `entry`, `stop`, `target`, `risk_per_share`, `risk_budget`, `qty` — is a `Decimal`. `atr` is a **float** (an indicator reading from the panel); `atr_stop_mult` / `target_r_multiple` are **floats** (rule fields). All three are converted to `Decimal` via `Decimal(str(x))` **inside** the math so no binary-float noise (e.g. `1.9` → `Decimal("1.9")`, never `Decimal(1.9) = 1.899999…`). `risk_per_trade` is likewise `Decimal(str(risk_per_trade))`.
- **Floor in Decimal space:** do the floor with `Decimal.quantize(Decimal("1"), rounding=ROUND_DOWN)` rather than `math.floor`, so the result *stays a `Decimal`* and never round-trips through a binary float. (`math.floor` returns an `int` and would force a float division — avoid.)
- **Guards:** `position_size` raises `ValueError` if `risk_per_share == 0` (a zero-distance stop has no defined size). This is the divide-by-zero backstop that the flat-direction handling already prevents upstream.
- **Look-ahead note (out of scope here, but recorded):** PRD §13 fills bar-`t` signals at `t+1`. That is #78's job. #76 only computes the price levels and size; it has no concept of bars.

---

## Worked golden (the literal example the unit tests hand-lock)

A concrete **long** trade. Every number below is computed exactly by hand so the unit test asserts the literal `Decimal`:

```python
entry          = Decimal("121.40")
atr            = 1.90            # float (ATR(14) indicator reading)
direction      = "long"
rule           = EntryExitRule()      # atr_stop_mult=2.0, target_r_multiple=2.0, max_holding_bars=20
account_size   = Decimal("100000")
risk_per_trade = 0.01
```

| Step | Computation (exact Decimal arithmetic) | Value |
|---|---|---|
| `atr_stop_mult` → Decimal | `Decimal(str(2.0))` | `Decimal("2.0")` |
| `atr` → Decimal | `Decimal(str(1.90))` | `Decimal("1.9")` |
| stop distance | `Decimal("2.0") · Decimal("1.9")` | `Decimal("3.80")` |
| **stop** (long: `entry − dist`) | `Decimal("121.40") − Decimal("3.80")` | **`Decimal("117.60")`** |
| **risk_per_share** (`\|entry − stop\|`) | `\|121.40 − 117.60\|` | **`Decimal("3.80")`** |
| `target_r_multiple` → Decimal | `Decimal(str(2.0))` | `Decimal("2.0")` |
| target offset | `Decimal("2.0") · Decimal("3.80")` | `Decimal("7.600")` |
| **target** (long: `entry + offset`) | `Decimal("121.40") + Decimal("7.600")` | **`Decimal("129.000")`** |
| `risk_per_trade` → Decimal | `Decimal(str(0.01))` | `Decimal("0.01")` |
| **risk_budget** | `Decimal("100000") · Decimal("0.01")` | `Decimal("1000.00")` |
| raw shares | `Decimal("1000.00") / Decimal("3.80")` | `263.1578947…` |
| **qty** (floor → whole-share Decimal) | `Decimal("263.1578…").quantize(Decimal("1"), ROUND_DOWN)` | **`Decimal("263")`** |

So `apply_rule(long_signal, entry=Decimal("121.40"), atr=1.90)` returns exactly:

```python
{
    "entry": Decimal("121.40"),
    "stop": Decimal("117.60"),
    "target": Decimal("129.000"),
    "qty": Decimal("263"),
    "risk_per_share": Decimal("3.80"),
}
```

**Mirror short check (hand-verified, used in the short test):** same inputs but `direction="short"` →
stop = `121.40 + 3.80 = Decimal("125.20")`; risk_per_share = `Decimal("3.80")`; target = `121.40 − 7.600 = Decimal("113.800")`; qty = `Decimal("263")` (sizing is sign-free — same risk budget, same per-share risk).

**Numeric notes for the test author (so the asserted literals are exact, not approximate):**
- Decimal multiplication preserves summed exponents: `Decimal("2.0")·Decimal("1.9")` has scale 2 → `Decimal("3.80")` (string-equal to `Decimal("3.80")`, **not** `Decimal("3.8")` — assert with `==`, which compares *value* so `Decimal("3.80") == Decimal("3.8")` is `True`; if you want to also pin the scale, that is optional and not required by the contract).
- `Decimal("2.0")·Decimal("3.80")` → `Decimal("7.600")`; `Decimal("121.40")+Decimal("7.600")` → `Decimal("129.000")`. These equal `Decimal("129.00")` / `Decimal("129")` by value. Tests assert by **value** (`==`) per house style — `Decimal("129.000") == Decimal("129")` is `True`.
- The floor: `Decimal("1000.00")/Decimal("3.80")` under the default context is `Decimal("263.1578947368421052631578947")`; `.quantize(Decimal("1"), rounding=ROUND_DOWN)` → `Decimal("263")`.

---

## Task 1: level math — `stop_price` + `target_price` (`engine/rules.py`, part 1)

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/engine/rules.py`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_rules.py`

**Design contract (this task):**
- `stop_price(entry: Decimal, atr: float, direction, rule: EntryExitRule) -> Decimal`
  - `dist = Decimal(str(rule.atr_stop_mult)) * Decimal(str(atr))`
  - `direction == "long"` → `entry - dist`; `direction == "short"` → `entry + dist`; `direction == "flat"` (or anything else) → `raise ValueError`.
  - Returns a `Decimal`.
- `target_price(entry: Decimal, stop: Decimal, direction, rule: EntryExitRule) -> Decimal`
  - `risk = abs(entry - stop)` (a `Decimal`); `offset = Decimal(str(rule.target_r_multiple)) * risk`
  - `direction == "long"` → `entry + offset`; `direction == "short"` → `entry - offset`; `flat`/other → `raise ValueError`.
  - Returns a `Decimal`. (Note `target_price` takes the already-computed `stop` so `risk_per_share` is computed once and reused — `1R` is single-sourced.)
- `direction` is typed `Literal["long", "short", "flat"]`.
- Both functions are pure, deterministic, and never touch a network or `obb.*`.

- [ ] **Step 1: Write the failing level-math tests** — create `openbb_platform/extensions/techtrade/tests/unit/test_rules.py`:

```python
"""Unit tests for the EntryExitRule level + sizing kernel (issue #76, PRD §13, §20 Q6).

Fully offline and deterministic: every assertion pins an exact ``Decimal`` derived
by hand in the plan's "worked golden" table, so any drift in the level math, the
long/short sign convention, the risk-per-share definition, or the risk-based floor
sizing is caught. No network, no API key, no router. The Q6 sizing inputs are
abstract notional (account_size: Decimal + risk_per_trade: float) -- no personal
dollar amounts. Decimal discipline is asserted explicitly (isinstance checks), and
floats (atr / multipliers) are converted via Decimal(str(...)) inside the kernel.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from openbb_techtrade.engine.rules import (
    stop_price,
    target_price,
)
from openbb_techtrade.models import EntryExitRule, MoverSignal

_AS_OF = date(2024, 1, 12)
_ENTRY = Decimal("121.40")
_ATR = 1.90
_RULE = EntryExitRule()  # atr_stop_mult=2.0, target_r_multiple=2.0, max_holding_bars=20


def _signal(direction: str) -> MoverSignal:
    """Build a minimal MoverSignal carrying just the direction the kernel reads."""
    score = {"long": 0.72, "short": -0.72, "flat": 0.05}[direction]
    return MoverSignal(
        symbol="TEST",
        segment="Information Technology",
        as_of=_AS_OF,
        score=score,
        direction=direction,
        votes=[],
        rank_in_segment=1,
    )


def test_stop_price_long_is_below_entry():
    """Assert a long stop sits atr_stop_mult*ATR below entry (121.40 - 3.80 = 117.60)."""
    stop = stop_price(_ENTRY, _ATR, "long", _RULE)
    assert stop == Decimal("117.60")
    assert isinstance(stop, Decimal)


def test_stop_price_short_is_above_entry():
    """Assert a short stop sits atr_stop_mult*ATR above entry (121.40 + 3.80 = 125.20)."""
    stop = stop_price(_ENTRY, _ATR, "short", _RULE)
    assert stop == Decimal("125.20")
    assert isinstance(stop, Decimal)


def test_risk_per_share_equals_atr_stop_mult_times_atr():
    """Assert |entry - stop| == atr_stop_mult * ATR for both directions (= 3.80)."""
    long_stop = stop_price(_ENTRY, _ATR, "long", _RULE)
    short_stop = stop_price(_ENTRY, _ATR, "short", _RULE)
    expected = Decimal(str(_RULE.atr_stop_mult)) * Decimal(str(_ATR))  # Decimal("3.80")
    assert abs(_ENTRY - long_stop) == expected
    assert abs(_ENTRY - short_stop) == expected
    assert expected == Decimal("3.80")


def test_stop_price_flat_raises():
    """Assert a flat direction has no stop and raises ValueError (no position to protect)."""
    with pytest.raises(ValueError):
        stop_price(_ENTRY, _ATR, "flat", _RULE)


def test_target_price_long_is_above_entry():
    """Assert a long target is entry + R*risk (121.40 + 2*3.80 = 129.00)."""
    stop = stop_price(_ENTRY, _ATR, "long", _RULE)
    target = target_price(_ENTRY, stop, "long", _RULE)
    assert target == Decimal("129.00")
    assert isinstance(target, Decimal)


def test_target_price_short_is_below_entry():
    """Assert a short target is entry - R*risk (121.40 - 2*3.80 = 113.80)."""
    stop = stop_price(_ENTRY, _ATR, "short", _RULE)
    target = target_price(_ENTRY, stop, "short", _RULE)
    assert target == Decimal("113.80")
    assert isinstance(target, Decimal)


def test_target_price_flat_raises():
    """Assert a flat direction has no target and raises ValueError."""
    stop = Decimal("117.60")
    with pytest.raises(ValueError):
        target_price(_ENTRY, stop, "flat", _RULE)


def test_target_honors_custom_r_multiple():
    """Assert a 3R rule widens the long target to entry + 3*3.80 = 132.80."""
    rule = EntryExitRule(target_r_multiple=3.0)
    stop = stop_price(_ENTRY, _ATR, "long", rule)
    target = target_price(_ENTRY, stop, "long", rule)
    assert target == Decimal("132.80")
```

- [ ] **Step 2: Run the tests — verify RED** (module does not exist yet):

```bash
cd /i/masterswork/git/OpenBBTechnical/openbb_platform/extensions/techtrade
/i/masterswork/git/OpenBBTechnical/.venv_win/Scripts/python.exe -m pytest tests/unit/test_rules.py -q
```
Expected: collection/import error — `ModuleNotFoundError: No module named 'openbb_techtrade.engine.rules'` (red).

- [ ] **Step 3: Implement `engine/rules.py` part 1** — create `openbb_platform/extensions/techtrade/openbb_techtrade/engine/rules.py`:

```python
"""Pure entry/exit level math + risk-based position sizing (issue #76, PRD §13).

This module turns a confluence ``MoverSignal`` plus an entry price and an ATR(14)
reading into the four numbers a trade needs -- stop, target, risk-per-share, and a
risk-budget-honoring share quantity -- and nothing else. It is deliberately pure:
no network, no ``obb.*`` call, no router, no class state. Order legs (#77), paper
fills (#78), and the time-stop bar count live downstream; #76 only computes levels
and size.

Sign convention (PRD §13): for a ``long`` the stop sits ``atr_stop_mult * ATR``
*below* entry and the target ``target_r_multiple * risk`` *above*; a ``short`` is
mirrored. A ``flat`` signal has no defensible levels, so ``stop_price`` /
``target_price`` raise ``ValueError`` -- :func:`apply_rule` handles flat up front
and returns a zero-size dict.

Decimal discipline (cross-plan contract §1): every money / quantity value
(``entry``, ``stop``, ``target``, ``risk_per_share``, ``risk_budget``, ``qty``) is a
``Decimal``. The ATR and the rule multipliers arrive as ``float`` and are converted
to ``Decimal`` via ``Decimal(str(x))`` *inside* the math, so ``1.9`` becomes
``Decimal("1.9")`` and never the binary-float ``Decimal(1.9)``. The share floor uses
``Decimal.quantize(Decimal("1"), ROUND_DOWN)`` so the quantity stays a ``Decimal``
rather than round-tripping through ``math.floor`` and an ``int``.

Sizing inputs are abstract notional per the §20 Q6 decision -- ``account_size``
(default ``Decimal("100000")``) and ``risk_per_trade`` (default ``0.01``) -- so no
personal dollar amount is ever emitted.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Literal

from openbb_techtrade.models import EntryExitRule, MoverSignal

Direction = Literal["long", "short", "flat"]


def stop_price(entry: Decimal, atr: float, direction: Direction, rule: EntryExitRule) -> Decimal:
    """Compute the protective stop price for a directional entry.

    The stop distance is ``atr_stop_mult * ATR``; a ``long`` stop is that distance
    below entry, a ``short`` stop the same distance above. A ``flat`` direction has
    no position to protect and raises ``ValueError``.

    Parameters
    ----------
    entry : Decimal
        Planned entry price.
    atr : float
        ATR(14) indicator reading (converted to Decimal internally).
    direction : {"long", "short", "flat"}
        Trade direction from the signal.
    rule : EntryExitRule
        Carries ``atr_stop_mult`` (the ATR multiple).

    Returns
    -------
    Decimal
        The stop price.
    """
    dist = Decimal(str(rule.atr_stop_mult)) * Decimal(str(atr))
    if direction == "long":
        return entry - dist
    if direction == "short":
        return entry + dist
    raise ValueError(f"stop_price requires a long/short direction, got {direction!r}")


def target_price(entry: Decimal, stop: Decimal, direction: Direction, rule: EntryExitRule) -> Decimal:
    """Compute the R-multiple profit target from entry, stop, and direction.

    Risk (``1R``) is the absolute stop distance ``abs(entry - stop)``; the target is
    ``target_r_multiple`` of that risk beyond entry -- above for a ``long``, below for
    a ``short``. A ``flat`` direction raises ``ValueError``.

    Parameters
    ----------
    entry : Decimal
        Planned entry price.
    stop : Decimal
        Stop price (from :func:`stop_price`); defines ``1R``.
    direction : {"long", "short", "flat"}
        Trade direction from the signal.
    rule : EntryExitRule
        Carries ``target_r_multiple``.

    Returns
    -------
    Decimal
        The profit-target price.
    """
    risk = abs(entry - stop)
    offset = Decimal(str(rule.target_r_multiple)) * risk
    if direction == "long":
        return entry + offset
    if direction == "short":
        return entry - offset
    raise ValueError(f"target_price requires a long/short direction, got {direction!r}")
```

- [ ] **Step 4: Run the tests — verify GREEN**:

```bash
/i/masterswork/git/OpenBBTechnical/.venv_win/Scripts/python.exe -m pytest tests/unit/test_rules.py -q
```
Expected: all 8 level-math tests pass.

- [ ] **Step 5: Ruff clean** (root `ruff.toml`, line-length 122):

```bash
/i/masterswork/git/OpenBBTechnical/.venv_win/Scripts/python.exe -m ruff check openbb_techtrade/engine/rules.py tests/unit/test_rules.py
```
Expected: `All checks passed!`.

---

## Task 2: sizing + orchestration — `position_size` + `apply_rule` (`engine/rules.py`, part 2)

**Files:**
- Modify: `openbb_techtrade/engine/rules.py` (append `position_size`, `apply_rule`)
- Modify: `tests/unit/test_rules.py` (append the sizing / apply_rule / determinism / edge tests)

**Design contract (this task):**
- `position_size(entry: Decimal, stop: Decimal, *, account_size: Decimal, risk_per_trade: float) -> Decimal`
  - `risk_budget = account_size * Decimal(str(risk_per_trade))`
  - `risk_per_share = abs(entry - stop)`; if `risk_per_share == 0` → `raise ValueError` (divide-by-zero guard).
  - `qty = (risk_budget / risk_per_share).quantize(Decimal("1"), rounding=ROUND_DOWN)` — a whole-share `Decimal`.
  - Returns a `Decimal`. Keyword-only `account_size` / `risk_per_trade` (matches the contract signature exactly).
- `apply_rule(signal: MoverSignal, *, entry: Decimal, atr: float, rule=EntryExitRule(), account_size=Decimal("100000"), risk_per_trade=0.01) -> dict`
  - Derive `direction = signal.direction`.
  - **flat short-circuit:** `direction == "flat"` → return `{"entry": entry, "stop": None, "target": None, "qty": Decimal(0), "risk_per_share": Decimal(0)}` (no levels, no position). Justification: a flat signal carries no trade — emitting `None` levels + `Decimal(0)` size is the honest, downstream-safe representation, and it keeps the divide-by-zero impossible.
  - otherwise: `stop = stop_price(entry, atr, direction, rule)`; `target = target_price(entry, stop, direction, rule)`; `risk_per_share = abs(entry - stop)`; `qty = position_size(entry, stop, account_size=account_size, risk_per_trade=risk_per_trade)`.
  - return `{"entry": entry, "stop": stop, "target": target, "qty": qty, "risk_per_share": risk_per_share}` — dict keys **exactly** `{"entry","stop","target","qty","risk_per_share"}`, all `Decimal` where money (entry/stop/target/qty/risk_per_share); `stop`/`target` are `None` only in the flat case.

- [ ] **Step 1: Append the failing sizing / orchestration tests** to `tests/unit/test_rules.py`:

```python
from openbb_techtrade.engine.rules import (
    apply_rule,
    position_size,
)

_ACCOUNT = Decimal("100000")
_RISK = 0.01


def test_position_size_floors_risk_budget_over_risk_per_share():
    """Assert qty = floor((100000*0.01) / 3.80) = floor(263.157...) = 263, as a Decimal."""
    stop = stop_price(_ENTRY, _ATR, "long", _RULE)  # 117.60 -> risk_per_share 3.80
    qty = position_size(_ENTRY, stop, account_size=_ACCOUNT, risk_per_trade=_RISK)
    assert qty == Decimal("263")
    assert isinstance(qty, Decimal)


def test_position_size_is_sign_free_for_short():
    """Assert sizing is identical for a short (same risk budget, same per-share risk)."""
    short_stop = stop_price(_ENTRY, _ATR, "short", _RULE)  # 125.20 -> risk_per_share 3.80
    qty = position_size(_ENTRY, short_stop, account_size=_ACCOUNT, risk_per_trade=_RISK)
    assert qty == Decimal("263")


def test_position_size_zero_risk_per_share_raises():
    """Assert a zero stop distance (entry == stop) raises ValueError, not ZeroDivisionError."""
    with pytest.raises(ValueError):
        position_size(_ENTRY, _ENTRY, account_size=_ACCOUNT, risk_per_trade=_RISK)


def test_position_size_smaller_risk_per_trade_shrinks_qty():
    """Assert halving risk_per_trade to 0.005 halves the budget -> floor(500/3.80) = 131."""
    stop = stop_price(_ENTRY, _ATR, "long", _RULE)
    qty = position_size(_ENTRY, stop, account_size=_ACCOUNT, risk_per_trade=0.005)
    assert qty == Decimal("131")  # floor(500.00 / 3.80) = floor(131.578...)


def test_position_size_tiny_atr_floors_large_qty():
    """Assert a very small ATR yields a large but exactly floored share count."""
    rule = EntryExitRule()
    stop = stop_price(_ENTRY, 0.05, "long", rule)  # dist = 2.0*0.05 = 0.10 -> rps 0.10
    qty = position_size(_ENTRY, stop, account_size=_ACCOUNT, risk_per_trade=_RISK)
    # risk_budget 1000.00 / 0.10 = 10000 exactly -> Decimal("10000")
    assert qty == Decimal("10000")


def test_apply_rule_long_returns_full_level_and_size_dict():
    """Assert apply_rule reproduces the worked-golden long dict exactly (all Decimal)."""
    result = apply_rule(_signal("long"), entry=_ENTRY, atr=_ATR)
    assert result == {
        "entry": Decimal("121.40"),
        "stop": Decimal("117.60"),
        "target": Decimal("129.00"),
        "qty": Decimal("263"),
        "risk_per_share": Decimal("3.80"),
    }
    assert set(result) == {"entry", "stop", "target", "qty", "risk_per_share"}
    for key in ("entry", "stop", "target", "qty", "risk_per_share"):
        assert isinstance(result[key], Decimal)


def test_apply_rule_short_mirrors_levels():
    """Assert a short plan mirrors stop above / target below entry with identical sizing."""
    result = apply_rule(_signal("short"), entry=_ENTRY, atr=_ATR)
    assert result["stop"] == Decimal("125.20")
    assert result["target"] == Decimal("113.80")
    assert result["risk_per_share"] == Decimal("3.80")
    assert result["qty"] == Decimal("263")


def test_apply_rule_flat_returns_zero_size_no_levels():
    """Assert a flat signal yields entry only, None stop/target, and zero size / zero risk."""
    result = apply_rule(_signal("flat"), entry=_ENTRY, atr=_ATR)
    assert result == {
        "entry": Decimal("121.40"),
        "stop": None,
        "target": None,
        "qty": Decimal(0),
        "risk_per_share": Decimal(0),
    }
    assert isinstance(result["qty"], Decimal)


def test_apply_rule_honors_account_and_risk_overrides():
    """Assert overriding account_size / risk_per_trade re-sizes deterministically."""
    result = apply_rule(
        _signal("long"), entry=_ENTRY, atr=_ATR,
        account_size=Decimal("50000"), risk_per_trade=0.02,
    )
    # risk_budget = 50000 * 0.02 = 1000.00 -> same qty 263 as the golden
    assert result["qty"] == Decimal("263")
    assert result["stop"] == Decimal("117.60")  # levels unchanged by sizing inputs


def test_apply_rule_is_deterministic():
    """Assert two identical calls return equal dicts (pure, no hidden state)."""
    a = apply_rule(_signal("long"), entry=_ENTRY, atr=_ATR)
    b = apply_rule(_signal("long"), entry=_ENTRY, atr=_ATR)
    assert a == b
```

- [ ] **Step 2: Run — verify RED** (the new `position_size` / `apply_rule` symbols don't exist yet):

```bash
/i/masterswork/git/OpenBBTechnical/.venv_win/Scripts/python.exe -m pytest tests/unit/test_rules.py -q
```
Expected: `ImportError: cannot import name 'apply_rule'` (and `position_size`) — red.

- [ ] **Step 3: Implement `engine/rules.py` part 2** — append `position_size` and `apply_rule` to `openbb_techtrade/engine/rules.py`:

```python
def position_size(
    entry: Decimal,
    stop: Decimal,
    *,
    account_size: Decimal,
    risk_per_trade: float,
) -> Decimal:
    """Compute a risk-budget-honoring whole-share position size.

    Sizes the position so the stop-loss equals a fixed risk fraction of notional:
    ``qty = floor((account_size * risk_per_trade) / abs(entry - stop))``. The floor
    is done with ``Decimal.quantize(..., ROUND_DOWN)`` so the result stays a Decimal
    (never over-risking by rounding up). The sizing inputs are abstract notional per
    the §20 Q6 decision -- no personal dollar amount is emitted.

    Parameters
    ----------
    entry : Decimal
        Planned entry price.
    stop : Decimal
        Stop price; ``abs(entry - stop)`` is the per-share risk (``1R``).
    account_size : Decimal
        Abstract notional account size (keyword-only).
    risk_per_trade : float
        Fraction of notional to risk per trade, e.g. 0.01 (keyword-only).

    Returns
    -------
    Decimal
        Whole-share position size.

    Raises
    ------
    ValueError
        If the per-share risk is zero (entry == stop), which has no defined size.
    """
    risk_per_share = abs(entry - stop)
    if risk_per_share == 0:
        raise ValueError("position_size requires a non-zero risk_per_share (entry == stop)")
    risk_budget = account_size * Decimal(str(risk_per_trade))
    qty = risk_budget / risk_per_share
    return qty.quantize(Decimal("1"), rounding=ROUND_DOWN)


def apply_rule(
    signal: MoverSignal,
    *,
    entry: Decimal,
    atr: float,
    rule: EntryExitRule = EntryExitRule(),
    account_size: Decimal = Decimal("100000"),
    risk_per_trade: float = 0.01,
) -> dict:
    """Turn a signal + entry + ATR into the full level/size dict for a trade.

    Orchestrates :func:`stop_price`, :func:`target_price`, and
    :func:`position_size`. A ``flat`` signal carries no trade, so it short-circuits
    to a zero-size, no-levels dict before any level math runs (which keeps the
    divide-by-zero impossible). All money / quantity values are ``Decimal``.

    Parameters
    ----------
    signal : MoverSignal
        Confluence signal; ``signal.direction`` drives the sign convention.
    entry : Decimal
        Planned entry price (keyword-only).
    atr : float
        ATR(14) reading (keyword-only).
    rule : EntryExitRule, optional
        Stop / target rule; defaults to ``EntryExitRule()``.
    account_size : Decimal, optional
        Abstract notional account size (Q6); defaults to ``Decimal("100000")``.
    risk_per_trade : float, optional
        Fraction of notional risked per trade (Q6); defaults to ``0.01``.

    Returns
    -------
    dict
        ``{"entry", "stop", "target", "qty", "risk_per_share"}`` -- all ``Decimal``
        where money; ``stop`` / ``target`` are ``None`` only for a flat signal.
    """
    direction = signal.direction
    if direction == "flat":
        return {
            "entry": entry,
            "stop": None,
            "target": None,
            "qty": Decimal(0),
            "risk_per_share": Decimal(0),
        }
    stop = stop_price(entry, atr, direction, rule)
    target = target_price(entry, stop, direction, rule)
    risk_per_share = abs(entry - stop)
    qty = position_size(entry, stop, account_size=account_size, risk_per_trade=risk_per_trade)
    return {
        "entry": entry,
        "stop": stop,
        "target": target,
        "qty": qty,
        "risk_per_share": risk_per_share,
    }
```

- [ ] **Step 4: Run the full test file — verify GREEN**:

```bash
/i/masterswork/git/OpenBBTechnical/.venv_win/Scripts/python.exe -m pytest tests/unit/test_rules.py -q
```
Expected: all level-math + sizing + apply_rule + determinism + edge tests pass (18 tests).

- [ ] **Step 5: Full unit gate + ruff** (confirm nothing else regressed; the parametrized `EntryExitRule()` default arg is fine — it is frozen/immutable in practice since `apply_rule` never mutates it):

```bash
/i/masterswork/git/OpenBBTechnical/.venv_win/Scripts/python.exe -m pytest tests/ -m "not integration" -q
/i/masterswork/git/OpenBBTechnical/.venv_win/Scripts/python.exe -m ruff check openbb_techtrade/engine/rules.py tests/unit/test_rules.py
```
Expected: techtrade unit + golden suite green; `All checks passed!` from ruff.

> **Note on the `rule=EntryExitRule()` default:** ruff rule `B008` (function-call-in-default) is **not** in this repo's selected set (see `ruff.toml [lint] select`), and the contract §3 signature pins this exact default, so it passes the gate as written. `apply_rule` never mutates `rule`, so the shared default instance is safe.

---

## Commit boundary (one issue = one commit)

This issue is **unit-only** per contract §5 — no router, no golden fixture, no integration test. Stage **exactly** the two #76 files:

```bash
cd /i/masterswork/git/OpenBBTechnical
git status   # confirm only the two files below are new; verify no noise files appear
git add openbb_platform/extensions/techtrade/openbb_techtrade/engine/rules.py \
        openbb_platform/extensions/techtrade/tests/unit/test_rules.py
git commit -m "$(cat <<'EOF'
feat(techtrade): add EntryExitRule level math + risk-based sizing (#76)

engine/rules.py: pure stop_price / target_price / position_size / apply_rule.
ATR stop, R-multiple target, risk-based floor sizing (qty = floor(risk_budget /
(atr_stop_mult*ATR))); Decimal throughout, abstract-notional Q6 sizing inputs.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
git status   # verify the commit succeeded and the noise files are still UNSTAGED
```

- **Leave UNSTAGED** (contract §1 noise list): `openbb_platform/core/openbb/assets/reference.json`, `openbb_platform/core/openbb/package/__init__.py`, `openbb_platform/extensions/agents/tests/test_config.py`. #76 adds **no router and no codegen**, so these must not change — if any appear in `git status`, do **not** include them.
- Commit message ends with the trailer `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`.
- Do not commit until the user has asked you to (follow the active git profile); if uncertain, stop after the green gate and report.

---

## Done-when
- `engine/rules.py` exposes `stop_price`, `target_price`, `position_size`, `apply_rule` — signatures **verbatim** from contract §3 (`apply_rule` returns the dict keyed exactly `{"entry","stop","target","qty","risk_per_share"}`, all `Decimal` where money).
- Given a `MoverSignal` + `entry` + `atr`, `apply_rule` yields a **deterministic** entry/stop/target + size (the worked-golden long dict: stop `117.60`, target `129.00`, qty `263`, risk_per_share `3.80`); the short mirror and flat zero-size cases are pinned too.
- Sizing honors the risk budget (`qty = floor(risk_budget / risk_per_share)`), uses `Decimal` end-to-end (asserted via `isinstance`), and the `risk_per_share == 0` guard raises `ValueError`.
- Sizing inputs reflect the **Q6** decision: abstract `account_size: Decimal` + `risk_per_trade: float` (defaults `Decimal("100000")` / `0.01`), no personal dollar amounts.
- `tests/unit/test_rules.py` is fully offline, deterministic, and green; ruff clean on both files.
- Single commit staging only `engine/rules.py` + `tests/unit/test_rules.py`; the three noise files stay unstaged.

## Self-review notes
- **§13 levels:** ATR stop (`entry ∓ atr_stop_mult·ATR`), R-multiple target (`entry ± target_r_multiple·risk_per_share`), and `risk_per_share = atr_stop_mult·ATR` are each a closed-form, hand-verified, tested branch for long **and** short; the flat case explicitly has no levels.
- **§13 sizing:** `qty = floor((account_size·risk_per_trade) / risk_per_share)` is exact in Decimal space (`quantize(Decimal("1"), ROUND_DOWN)` — never `math.floor`/`int`), honoring the risk budget and never over-sizing; the tiny-ATR and risk-override edge tests prove the floor behaves at the extremes.
- **§20 Q6:** sizing inputs are abstract notional (`account_size: Decimal`, `risk_per_trade: float`) with the locked defaults; no personal dollar amounts are emitted — outward artifacts stay normalized (the #80 `Recommendation` / #81 Excel consume these levels, not an account balance).
- **Decimal discipline (contract §1):** floats (`atr`, `atr_stop_mult`, `target_r_multiple`, `risk_per_trade`) cross into money only via `Decimal(str(x))`, so `1.9` is `Decimal("1.9")` not `Decimal(1.9)`; every emitted price/qty/risk is a `Decimal`, asserted in tests.
- **Purity (contract §1):** no network, no `obb.*`, no router, no DI seam — `rules.py` is a leaf consumed by #77's `engine/orders.py` / `engine/plan.py`. It imports only `decimal`, `typing`, and the frozen `models` types; `models.py` is untouched.
- **Determinism:** no randomness, no I/O, no hidden state; `test_apply_rule_is_deterministic` pins call-to-call equality, and every numeric assertion is a literal `Decimal` from the worked-golden table.
- **Scope discipline:** the `max_holding_bars` time stop is *carried by* `EntryExitRule` and surfaced by #77/#78; #76 computes price levels + size only and never simulates bars (look-ahead handling is #78's contract).
- **No model change:** consumes the frozen `MoverSignal` (reads `.direction`) and `EntryExitRule` (reads `.atr_stop_mult` / `.target_r_multiple`) verbatim; emits a plain `dict` (the typed `Order`/`TradePlan` assembly is #77).
