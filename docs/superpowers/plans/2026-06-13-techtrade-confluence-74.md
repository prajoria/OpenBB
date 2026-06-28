# techtrade #74 — weighted confluence voting → composite score + IndicatorVote attribution

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) tracking. TDD throughout (write failing test → run red → implement → run green → ruff → commit). **Read the locked cross-plan contract first:** `docs/superpowers/plans/2026-06-13-techtrade-pipeline-contract.md` (§3 "#74 — engine/confluence.py" and §5 commit manifest). The contract wins over anything here — if they disagree, fix this plan.

**Goal:** Build `engine/confluence.py` — the pure weighted-confluence engine that turns a #72/#73 `IndicatorPanel` into a composite `score ∈ [-1,+1]` plus a **full `IndicatorVote` attribution list** (every indicator's family / name / vote / weight) so the engine can always answer *"why long?"*, exactly per PRD §12 and the §20 Q4 weight decision.

**Architecture:** A pure, network-free module. Family voters (`trend_votes` / `momentum_votes` / `volatility_votes` + an internal volume voter) each map a panel's indicator readings to a directional `vote ∈ [-1,+1]`. `composite_score` combines the three additive families as `raw = Σ_family ( w_family · mean_indicator(vote_i) )`, then applies `volume_confirmation` as a **multiplier** (not an additive term, per Q4): `score = clip(raw · vc, -1, +1)`. Thin pure helpers (`direction_for`, `conviction_for`, `build_signal`) bucket the score and assemble the frozen `MoverSignal`. Determinism rests on fixed `ConfluenceWeights` + closed-form vote formulas; no randomness, no I/O. This module **produces the existing `MoverSignal`/`IndicatorVote` models unchanged** (frozen in `models.py`).

**Tech Stack:** Python 3.12, stdlib only (`dataclasses`, `statistics`/manual mean, `math`), `openbb_techtrade.models` (`IndicatorPanel`, `IndicatorVote`, `MoverSignal`), `openbb_techtrade.testing` golden harness (#71), pytest. (`engine/indicators.py` is imported only in the one offline end-to-end wiring test, behind `importorskip("pandas_ta_classic")`.)

---

## Domain rules locked from PRD §12 (+ §14.2 conviction, §20 Q4)

- **Q4 weights (the decision this issue encodes):** trend `0.40`, momentum `0.25`, volatility `0.20`, **volume `0.15` as a confirmation *multiplier*, not an additive vote.** The three additive families (trend+momentum+volatility) feed `raw`; volume scales `raw`.
- **Voting (§12.1):**
  - **Trend** — `sign(macd_hist)` **gated by ADX**: `adx > adx_gate (20)` ⇒ full strength, else damped by `adx/adx_gate`. **EMA-cross** adds +1 (golden, `ema_cross > 0`) / −1 (death, `< 0`).
  - **Momentum** — RSI `>55` ⇒ +, `<45` ⇒ −, magnitude scaling toward ±1 at `70/30` (neutral `[45,55]` ⇒ 0). **Stoch K/D cross confirms sign**: `sign(stoch_k − stoch_d)`.
  - **Volatility** — regime-aware **Bollinger %B**: trend regime = breakout-continuation (`%B>1 ⇒ +`); range regime = mean-revert (fade the band). **ATR does NOT vote** (it sets stops in §13). `regime` is a *parameter* (default `"trend"`), not auto-detected here.
  - **Volume** — **confirmation multiplier**: rising OBV / positive CMF amplifies a same-sign score; divergence damps it. NOT an additive family.
- **Composite (§12.2):** `raw = Σ_family ( w_family · mean_indicator(vote_i) )`; `score = clip(raw · volume_confirmation, −1, +1)`.
- **Direction:** `long` if `score ≥ +entry_threshold` (default `0.4`), `short` if `score ≤ −entry_threshold`, else `flat`.
- **Conviction (§14.2):** from `|score|` — `≥0.7` High, `0.4–0.7` Medium, `<0.4` Low.
- **Attribution (§4.3, §12.2):** every `MoverSignal.votes` carries **every** indicator's `IndicatorVote` (incl. the volume votes), so `votes` fully reconcile the score.

---

## Empirically-derived voting math (the design contract — closed-form, hand-verifiable)

All formulas are deterministic and closed-form. `_clip(x,lo,hi)`, `_sign(x)` (returns float `-1.0/0.0/1.0`), and `_mean(xs)` (empty ⇒ `0.0`) are tiny module-local helpers. Missing panel keys ⇒ that vote is simply **omitted** (warm-up safety, mirroring #72's omit-on-non-finite).

| Family (weight) | Vote name | Closed-form vote ∈ [-1,+1] |
|---|---|---|
| **trend** (0.40) | `macd_hist` | `_sign(macd_hist) · gate`, where `gate = 1.0 if (adx is None or adx > adx_gate) else _clip(adx/adx_gate, 0, 1)` |
| **trend** (0.40) | `ema_cross` | `_sign(ema_cross)` (+1 golden / −1 death / 0 flat) |
| **momentum** (0.25) | `rsi` | `+_clip((rsi−55)/15, 0, 1)` if `rsi≥55`; `−_clip((45−rsi)/15, 0, 1)` if `rsi≤45`; else `0.0` (saturates ±1 at 70/30) |
| **momentum** (0.25) | `stoch` | `_sign(stoch_k − stoch_d)` (K/D cross confirms sign) |
| **volatility** (0.20) | `bb_pctb` | trend regime: `_clip(2·(bb_pctb−0.5), −1, 1)`; range regime: `_clip(−2·(bb_pctb−0.5), −1, 1)` |
| **volume** (0.15) | `obv_slope` | `_sign(obv_slope)` |
| **volume** (0.15) | `cmf` | `_sign(cmf)` |

- `volume_confirmation(panel) = 1.0 + DEFAULT_WEIGHTS.volume · _mean(volume_votes)` → with `v ∈ [-1,1]`, range **`[0.85, 1.15]`** ("multiplier in ~[0,1+]", per contract). No volume keys ⇒ `v=0` ⇒ `vc=1.0` (neutral). The amplitude is the **Q4 volume weight 0.15**, expressed as the module constant `DEFAULT_WEIGHTS.volume` (the function takes no `weights` arg per the contract signature; #75 owns preset reweighting).
- `composite_score(panel, *, weights)` re-stamps each returned vote's `.weight` with the `weights.<family>` actually used (so attribution reconciles for any weights), computes `raw = weights.trend·mean_t + weights.momentum·mean_m + weights.volatility·mean_v`, then `score = _clip(raw · volume_confirmation(panel), −1, +1)`, and returns `(score, trend+momentum+volatility+volume votes)`.

### Worked golden (the literal panel the unit + golden tests lock)

A deliberately bullish hand-built panel (every family fires):

```python
IndicatorPanel(
    symbol="GOLD", as_of=date(2024, 1, 12),
    trend={"macd_hist": 0.85, "adx": 28.0, "ema_fast": 121.5, "ema_slow": 117.0, "ema_cross": 4.5},
    momentum={"rsi": 64.0, "stoch_k": 80.0, "stoch_d": 72.0},
    volatility={"bb_pctb": 0.92, "atr": 3.1, "kc_upper": 124.0, "kc_lower": 116.0},
    volume={"obv_slope": 12.0, "cmf": 0.18},
    candles={"cdl_engulfing": 1},
)
```

| Step | Computation | Value |
|---|---|---|
| trend `macd_hist` | `_sign(0.85)·(adx 28>20 ⇒ gate 1.0)` | `+1.0` |
| trend `ema_cross` | `_sign(4.5)` | `+1.0` |
| **mean_trend** | `(1.0 + 1.0)/2` | `1.0` |
| momentum `rsi` | `+clip((64−55)/15,0,1)=clip(0.6,…)` | `0.6` |
| momentum `stoch` | `_sign(80−72)` | `+1.0` |
| **mean_momentum** | `(0.6 + 1.0)/2` | `0.8` |
| volatility `bb_pctb` (trend) | `clip(2·(0.92−0.5),−1,1)=clip(0.84,…)` | `0.84` |
| **mean_volatility** | single vote | `0.84` |
| volume `obv_slope`,`cmf` | `_sign(12.0)=+1`, `_sign(0.18)=+1` ⇒ `v=1.0` | — |
| **volume_confirmation** | `1.0 + 0.15·1.0` | `1.15` |
| **raw** | `0.40·1.0 + 0.25·0.8 + 0.20·0.84 = 0.40 + 0.20 + 0.168` | `0.768` |
| **score** | `clip(0.768 · 1.15, −1, 1) = clip(0.8832, …)` | **`0.8832`** |
| **direction** | `0.8832 ≥ 0.4` | `long` |
| **conviction** | `|0.8832| ≥ 0.7` | `High` |
| **votes len** | 2 trend + 2 momentum + 1 volatility + 2 volume | `7` |

`score = 0.8832` is the golden value reproduced in Task 2's unit test **and** locked in Task 3's fixture.

---

## Task 1: family voters + volume confirmation (`engine/confluence.py`, part 1)

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/engine/confluence.py`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_confluence.py`

**Design contract (this task):**
- `@dataclass(frozen=True) class ConfluenceWeights:` fields `trend: float = 0.40`, `momentum: float = 0.25`, `volatility: float = 0.20`, `volume: float = 0.15`. `DEFAULT_WEIGHTS = ConfluenceWeights()`.
- Module-local helpers: `_clip(x, lo, hi) -> float`, `_sign(x) -> float` (`-1.0/0.0/1.0`), `_mean(xs) -> float` (empty ⇒ `0.0`).
- `trend_votes(panel, *, adx_gate=20.0) -> list[IndicatorVote]` — emits `macd_hist` (ADX-gated) and `ema_cross` votes; each only when its key is present; `weight=DEFAULT_WEIGHTS.trend`, `family="trend"`.
- `momentum_votes(panel) -> list[IndicatorVote]` — emits `rsi` and `stoch` votes (`stoch` only when both `stoch_k` and `stoch_d` present); `weight=DEFAULT_WEIGHTS.momentum`, `family="momentum"`.
- `volatility_votes(panel, *, regime: Literal["trend","range"]="trend") -> list[IndicatorVote]` — emits the `bb_pctb` vote only (ATR never votes); `weight=DEFAULT_WEIGHTS.volatility`, `family="volatility"`.
- `_volume_votes(panel) -> list[IndicatorVote]` — internal; emits `obv_slope` / `cmf` sign votes; `weight=DEFAULT_WEIGHTS.volume`, `family="volume"`.
- `volume_confirmation(panel) -> float` — `1.0 + DEFAULT_WEIGHTS.volume · _mean([v.vote for v in _volume_votes(panel)])`; `1.0` when no volume keys.

- [ ] **Step 1: Write failing tests** `tests/unit/test_confluence.py`

```python
"""Unit tests for the weighted-confluence vote engine (issue #74, PRD §12, §20 Q4).

Fully offline and deterministic: hand-built ``IndicatorPanel`` literals drive every
voter so the closed-form vote math (PRD §12.1) is pinned exactly, with no network,
no API key, and no pandas-ta call. The bullish ``_gold_panel`` is the same literal
the golden fixture locks; ``_flat_panel`` exercises the damped / neutral branches.
Covers the Q4 weights, ADX gating, RSI 70/30 saturation, the stoch K/D cross, the
regime-aware Bollinger %B vote, ATR never voting, and the volume confirmation
multiplier (which is NOT an additive family).
"""

from __future__ import annotations

from datetime import date

import pytest

from openbb_techtrade.engine.confluence import (
    DEFAULT_WEIGHTS,
    ConfluenceWeights,
    momentum_votes,
    trend_votes,
    volatility_votes,
    volume_confirmation,
)
from openbb_techtrade.models import IndicatorPanel, IndicatorVote

_AS_OF = date(2024, 1, 12)


def _gold_panel() -> IndicatorPanel:
    """Build the bullish reference panel (every family fires); golden-locked literal."""
    return IndicatorPanel(
        symbol="GOLD",
        as_of=_AS_OF,
        trend={"macd_hist": 0.85, "adx": 28.0, "ema_fast": 121.5, "ema_slow": 117.0, "ema_cross": 4.5},
        momentum={"rsi": 64.0, "stoch_k": 80.0, "stoch_d": 72.0},
        volatility={"bb_pctb": 0.92, "atr": 3.1, "kc_upper": 124.0, "kc_lower": 116.0},
        volume={"obv_slope": 12.0, "cmf": 0.18},
        candles={"cdl_engulfing": 1},
    )


def _flat_panel() -> IndicatorPanel:
    """Build a weak / mixed panel: damped MACD (ADX<gate), neutral RSI, mid-band %B."""
    return IndicatorPanel(
        symbol="FLAT",
        as_of=_AS_OF,
        trend={"macd_hist": 0.10, "adx": 10.0, "ema_fast": 99.9, "ema_slow": 100.1, "ema_cross": -0.2},
        momentum={"rsi": 50.0, "stoch_k": 50.0, "stoch_d": 50.0},
        volatility={"bb_pctb": 0.50, "atr": 1.0, "kc_upper": 102.0, "kc_lower": 98.0},
        volume={"obv_slope": 0.0, "cmf": 0.0},
        candles={},
    )


def test_default_weights_match_q4():
    """Assert the frozen Q4 weights: trend .40 / momentum .25 / volatility .20 / volume .15."""
    assert (DEFAULT_WEIGHTS.trend, DEFAULT_WEIGHTS.momentum) == (0.40, 0.25)
    assert (DEFAULT_WEIGHTS.volatility, DEFAULT_WEIGHTS.volume) == (0.20, 0.15)
    assert isinstance(ConfluenceWeights(), ConfluenceWeights)


def test_trend_votes_macd_full_strength_when_adx_strong():
    """Assert MACD votes its sign at full strength when ADX exceeds the gate, plus the EMA cross."""
    votes = trend_votes(_gold_panel())
    by_name = {v.name: v for v in votes}
    assert by_name["macd_hist"].vote == pytest.approx(1.0)  # sign(+0.85) * gate(1.0)
    assert by_name["ema_cross"].vote == pytest.approx(1.0)  # golden cross
    assert all(v.family == "trend" and v.weight == pytest.approx(0.40) for v in votes)
    assert all(isinstance(v, IndicatorVote) for v in votes)


def test_trend_macd_damped_when_adx_weak():
    """Assert a weak ADX damps the MACD vote by adx/adx_gate (here 10/20 = 0.5)."""
    macd = {v.name: v for v in trend_votes(_flat_panel())}["macd_hist"]
    assert macd.vote == pytest.approx(0.5)  # sign(+0.10) * clip(10/20, 0, 1)


def test_momentum_rsi_scales_and_stoch_cross_confirms():
    """Assert RSI scales toward +1 by 70 and the stoch K/D cross votes its sign."""
    by_name = {v.name: v for v in momentum_votes(_gold_panel())}
    assert by_name["rsi"].vote == pytest.approx(0.6)  # (64-55)/15
    assert by_name["stoch"].vote == pytest.approx(1.0)  # sign(80-72)
    assert all(v.weight == pytest.approx(0.25) for v in momentum_votes(_gold_panel()))


def test_momentum_rsi_saturates_at_70_30():
    """Assert RSI magnitude saturates at +1 by 70 and -1 by 30, and is neutral in [45,55]."""
    hot = IndicatorPanel(symbol="H", as_of=_AS_OF, momentum={"rsi": 82.0})
    cold = IndicatorPanel(symbol="C", as_of=_AS_OF, momentum={"rsi": 18.0})
    mid = IndicatorPanel(symbol="M", as_of=_AS_OF, momentum={"rsi": 50.0})
    assert {v.name: v.vote for v in momentum_votes(hot)}["rsi"] == pytest.approx(1.0)
    assert {v.name: v.vote for v in momentum_votes(cold)}["rsi"] == pytest.approx(-1.0)
    assert {v.name: v.vote for v in momentum_votes(mid)}["rsi"] == pytest.approx(0.0)


def test_volatility_bbpctb_regime_aware_and_atr_silent():
    """Assert %B votes continuation in a trend regime, flips in a range regime, and ATR never votes."""
    trend_vote = {v.name: v for v in volatility_votes(_gold_panel(), regime="trend")}
    range_vote = {v.name: v for v in volatility_votes(_gold_panel(), regime="range")}
    assert trend_vote["bb_pctb"].vote == pytest.approx(0.84)   # 2*(0.92-0.5)
    assert range_vote["bb_pctb"].vote == pytest.approx(-0.84)  # mean-revert flip
    assert "atr" not in trend_vote  # ATR sets stops (§13), never votes
    assert all(v.family == "volatility" and v.weight == pytest.approx(0.20) for v in trend_vote.values())


def test_volume_confirmation_amplifies_and_damps():
    """Assert volume confirmation is 1 + 0.15*v: 1.15 when OBV/CMF agree, 1.0 when neutral."""
    assert volume_confirmation(_gold_panel()) == pytest.approx(1.15)  # v = +1
    assert volume_confirmation(_flat_panel()) == pytest.approx(1.0)   # v = 0
    bearish = IndicatorPanel(symbol="B", as_of=_AS_OF, volume={"obv_slope": -5.0, "cmf": -0.2})
    assert volume_confirmation(bearish) == pytest.approx(0.85)        # v = -1


def test_voters_omit_missing_keys():
    """Assert voters degrade gracefully: absent panel keys simply drop their vote, no raise."""
    empty = IndicatorPanel(symbol="E", as_of=_AS_OF)
    assert trend_votes(empty) == []
    assert momentum_votes(empty) == []
    assert volatility_votes(empty) == []
    assert volume_confirmation(empty) == pytest.approx(1.0)
```

- [ ] **Step 2: Run, verify fail** — `…\.venv_win\Scripts\python.exe -m pytest tests/unit/test_confluence.py -q` → ImportError (module missing).

- [ ] **Step 3: Implement `engine/confluence.py` (part 1).** Module docstring states: pure weighted-confluence engine (PRD §12); Q4 weights (trend .40 / momentum .25 / volatility .20 / volume .15 as a confirmation multiplier); closed-form deterministic vote math; votes are `float`; missing keys omitted; no I/O. Implement `ConfluenceWeights` / `DEFAULT_WEIGHTS`, the `_clip`/`_sign`/`_mean` helpers, `trend_votes`, `momentum_votes`, `volatility_votes`, `_volume_votes`, and `volume_confirmation` per the math table above. Each public voter has a NumPy-style docstring. Keep `Literal` imported from `typing` for the `regime` arg.

- [ ] **Step 4: Run tests, verify pass.**

- [ ] **Step 5: Ruff clean** — `…\.venv_win\Scripts\python.exe -m ruff check openbb_techtrade/engine/confluence.py tests/unit/test_confluence.py` (root `ruff.toml`, line-length 122).

---

## Task 2: composite score + bucketing + `build_signal` (`engine/confluence.py`, part 2)

**Files:**
- Modify: `openbb_techtrade/engine/confluence.py` (append `composite_score`, `direction_for`, `conviction_for`, `build_signal`)
- Test: `tests/unit/test_confluence.py` (append the composite / golden-score / reconcile / wiring tests)

**Design contract (this task):**
- `composite_score(panel, *, weights=DEFAULT_WEIGHTS) -> tuple[float, list[IndicatorVote]]` — gathers `trend_votes + momentum_votes + volatility_votes + _volume_votes`, **re-stamps** each vote's `.weight` with `weights.<family>` (so the returned attribution reflects the weights actually used), computes `raw = weights.trend·_mean(trend) + weights.momentum·_mean(momentum) + weights.volatility·_mean(volatility)`, then `score = _clip(raw · volume_confirmation(panel), −1.0, 1.0)`. Returns `(score, all_votes)` — volume votes included for full attribution even though they enter as the multiplier.
- `direction_for(score, *, entry_threshold=0.4) -> Literal["long","short","flat"]` — `long` if `score ≥ +t`, `short` if `score ≤ −t`, else `flat`.
- `conviction_for(score) -> Literal["High","Medium","Low"]` — `abs(score) ≥ 0.7 → High`, `≥ 0.4 → Medium`, else `Low`.
- `build_signal(panel, segment, *, weights=DEFAULT_WEIGHTS, entry_threshold=0.4, rank_in_segment=0) -> MoverSignal` — `score, votes = composite_score(...)`; assembles `MoverSignal(symbol=panel.symbol, segment=segment, as_of=panel.as_of, score=score, direction=direction_for(score, entry_threshold=entry_threshold), votes=votes, rank_in_segment=rank_in_segment)`.

- [ ] **Step 1: Append failing tests** to `tests/unit/test_confluence.py`

```python
from openbb_techtrade.engine.confluence import (
    build_signal,
    composite_score,
    conviction_for,
    direction_for,
)
from openbb_techtrade.models import MoverSignal


def test_composite_score_reproduces_golden_value():
    """Assert the hand-derived composite score (0.8832) is reproduced exactly."""
    score, votes = composite_score(_gold_panel())
    assert score == pytest.approx(0.8832)
    assert len(votes) == 7  # 2 trend + 2 momentum + 1 volatility + 2 volume


def test_votes_fully_reconcile_the_score():
    """Assert the returned votes reconstruct the score (sum / weights reconcile, §12.2)."""
    score, votes = composite_score(_gold_panel())

    def _mean_family(family: str) -> float:
        vals = [v.vote for v in votes if v.family == family]
        return sum(vals) / len(vals) if vals else 0.0

    w = {v.family: v.weight for v in votes}  # one weight per family
    raw = w["trend"] * _mean_family("trend") + w["momentum"] * _mean_family("momentum") + \
        w["volatility"] * _mean_family("volatility")
    vc = 1.0 + w["volume"] * _mean_family("volume")
    rebuilt = max(-1.0, min(1.0, raw * vc))
    assert rebuilt == pytest.approx(score)


def test_score_is_clipped_into_unit_interval():
    """Assert an extreme all-aligned panel clips the score into [-1, +1]."""
    strong = IndicatorPanel(
        symbol="S", as_of=_AS_OF,
        trend={"macd_hist": 9.0, "adx": 60.0, "ema_cross": 5.0},
        momentum={"rsi": 95.0, "stoch_k": 99.0, "stoch_d": 10.0},
        volatility={"bb_pctb": 3.0},
        volume={"obv_slope": 9.0, "cmf": 0.9},
    )
    score, _ = composite_score(strong)
    assert -1.0 <= score <= 1.0


def test_direction_buckets():
    """Assert direction bucketing at the default 0.4 entry threshold."""
    assert direction_for(0.55) == "long"
    assert direction_for(-0.55) == "short"
    assert direction_for(0.10) == "flat"
    assert direction_for(0.4) == "long"  # boundary is inclusive
    assert direction_for(0.30, entry_threshold=0.25) == "long"  # custom threshold


def test_conviction_buckets():
    """Assert |score| conviction bucketing: >=0.7 High, >=0.4 Medium, else Low (§14.2)."""
    assert conviction_for(0.80) == "High"
    assert conviction_for(-0.72) == "High"
    assert conviction_for(0.50) == "Medium"
    assert conviction_for(-0.41) == "Medium"
    assert conviction_for(0.20) == "Low"


def test_build_signal_assembles_full_mover_signal():
    """Assert build_signal returns a MoverSignal carrying the score, direction, and full votes."""
    signal = build_signal(_gold_panel(), "Information Technology", rank_in_segment=1)
    assert isinstance(signal, MoverSignal)
    assert signal.symbol == "GOLD"
    assert signal.segment == "Information Technology"
    assert signal.as_of == _AS_OF
    assert signal.score == pytest.approx(0.8832)
    assert signal.direction == "long"
    assert signal.rank_in_segment == 1
    assert len(signal.votes) == 7
    assert {v.family for v in signal.votes} == {"trend", "momentum", "volatility", "volume"}


def test_build_signal_flat_when_score_below_threshold():
    """Assert a weak / mixed panel resolves to a flat, below-threshold signal."""
    signal = build_signal(_flat_panel(), "Financials")
    assert signal.direction == "flat"
    assert abs(signal.score) < 0.4
    assert conviction_for(signal.score) == "Low"


def test_consumes_real_indicator_panel_end_to_end():
    """Assert confluence consumes a #72-built panel (real keys) without raising."""
    pytest.importorskip("pandas_ta_classic")
    import numpy as np

    from openbb_techtrade.engine.indicators import build_indicator_panel

    rng = np.random.default_rng(20240112)
    close = 100.0 + np.cumsum(rng.normal(0.15, 1.0, 220))  # mild uptrend
    high = close + np.abs(rng.normal(0, 0.6, 220))
    low = close - np.abs(rng.normal(0, 0.6, 220))
    open_ = close + rng.normal(0, 0.4, 220)
    vol = rng.integers(1_000, 8_000, 220).astype(float)
    rows = [
        {"open": float(open_[i]), "high": float(high[i]), "low": float(low[i]),
         "close": float(close[i]), "volume": float(vol[i])}
        for i in range(220)
    ]
    panel = build_indicator_panel("REAL", _AS_OF, rows)
    signal = build_signal(panel, "Information Technology", rank_in_segment=3)
    assert -1.0 <= signal.score <= 1.0
    assert signal.direction in {"long", "short", "flat"}
    assert signal.votes  # at least one indicator voted
```

- [ ] **Step 2: Run, verify fail** — composite/build symbols missing → ImportError/fail.

- [ ] **Step 3: Implement part 2** — `composite_score` (gather → re-stamp `.weight` to `weights.<family>` → family means → `raw` → `· volume_confirmation` → clip), `direction_for`, `conviction_for`, `build_signal`. Re-stamping: rebuild each `IndicatorVote(family=v.family, name=v.name, vote=v.vote, weight=getattr(weights, v.family))` so the returned votes always carry the weights used (a no-op under `DEFAULT_WEIGHTS`; correct for presets in #75). Each public function gets a NumPy-style docstring; note in `composite_score`'s docstring that volume enters as the multiplier (`volume_confirmation`), not as an additive family term.

- [ ] **Step 4: Run tests, verify pass** — full `tests/unit/test_confluence.py` green.

- [ ] **Step 5: Ruff clean** on both files.

---

## Task 3: golden-score lock (full vote breakdown)

**Files:**
- Create: `tests/golden/test_confluence_golden.py`
- Create: `tests/golden/fixtures/confluence_signal_golden.json` (via regen)

The golden locks the **entire `MoverSignal`** for `_gold_panel()` — `score` **and** every `IndicatorVote` (family / name / vote / weight) — so any drift in either the score or the attribution breakdown is caught (the §12.2 transparency guarantee, regression-pinned).

- [ ] **Step 1: Write the golden test** `tests/golden/test_confluence_golden.py`:

```python
"""Golden-score regression lock for the confluence engine (#74, #71 harness, PRD §12).

Builds a MoverSignal from a fixed bullish hand-built IndicatorPanel (the same
``_gold_panel`` literal the unit suite hand-derives to score 0.8832) and locks the
full signal -- composite score AND every IndicatorVote (family / name / vote /
weight) -- against a committed golden JSON within DEFAULT_TOL. Carries the
``golden`` marker. Regenerate intentionally after a *reviewed* change with
TECHTRADE_REGEN_GOLDEN=1 -- never blindly.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from openbb_techtrade.engine.confluence import build_signal
from openbb_techtrade.models import IndicatorPanel
from openbb_techtrade.testing import assert_matches_golden

import pytest

pytestmark = pytest.mark.golden

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_AS_OF = date(2024, 1, 12)


def _gold_panel() -> IndicatorPanel:
    """Build the bullish reference panel locked by the golden fixture."""
    return IndicatorPanel(
        symbol="GOLD",
        as_of=_AS_OF,
        trend={"macd_hist": 0.85, "adx": 28.0, "ema_fast": 121.5, "ema_slow": 117.0, "ema_cross": 4.5},
        momentum={"rsi": 64.0, "stoch_k": 80.0, "stoch_d": 72.0},
        volatility={"bb_pctb": 0.92, "atr": 3.1, "kc_upper": 124.0, "kc_lower": 116.0},
        volume={"obv_slope": 12.0, "cmf": 0.18},
        candles={"cdl_engulfing": 1},
    )


def _snapshot() -> dict:
    """Return the JSON-able MoverSignal snapshot for the golden comparison."""
    return build_signal(_gold_panel(), "Information Technology", rank_in_segment=1).model_dump()


def test_confluence_signal_matches_golden():
    """Assert the full MoverSignal (score + votes) matches the committed golden fixture."""
    assert_matches_golden("confluence_signal_golden", _snapshot(), fixture_dir=_FIXTURE_DIR)


def test_confluence_signal_is_deterministic():
    """Assert two builds of the same panel produce an identical signal snapshot."""
    assert _snapshot() == _snapshot()
```

- [ ] **Step 2: Generate the golden** — `TECHTRADE_REGEN_GOLDEN=1 …\.venv_win\Scripts\python.exe -m pytest tests/golden/test_confluence_golden.py -q`, then **inspect** `fixtures/confluence_signal_golden.json` before committing: `score` ≈ `0.8832`; `direction` `"long"`; exactly **7** vote objects; weights read `0.40` (trend ×2), `0.25` (momentum ×2), `0.20` (volatility ×1), `0.15` (volume ×2); votes match the worked table (`macd_hist`=1.0, `ema_cross`=1.0, `rsi`=0.6, `stoch`=1.0, `bb_pctb`=0.84, `obv_slope`=1.0, `cmf`=1.0). Commit only after the numbers check out by hand.

- [ ] **Step 3: Re-run without regen** — `…\.venv_win\Scripts\python.exe -m pytest tests/golden/test_confluence_golden.py -q` → golden locks (passes).

- [ ] **Step 4: Full gate** — `…\.venv_win\Scripts\python.exe -m pytest tests/ -m "not integration" -q` (all techtrade unit + golden green; the end-to-end wiring test auto-skips if `pandas_ta_classic` is unavailable) and `…\.venv_win\Scripts\python.exe -m ruff check openbb_techtrade/engine/confluence.py tests/unit/test_confluence.py tests/golden/test_confluence_golden.py`.

---

## Commit boundary (one issue = one commit)

Stage **exactly** the #74 files (contract §5):

```bash
cd /i/masterswork/git/OpenBBTechnical/openbb_platform/extensions/techtrade
git add openbb_techtrade/engine/confluence.py \
        tests/unit/test_confluence.py \
        tests/golden/test_confluence_golden.py \
        tests/golden/fixtures/confluence_signal_golden.json
```

- **Leave UNSTAGED** (contract §1 noise list): `openbb_platform/core/openbb/assets/reference.json`, `openbb_platform/core/openbb/package/__init__.py`, `openbb_platform/extensions/agents/tests/test_config.py`. (#74 adds no router and no codegen, so these should not change — verify with `git status` before staging; if any appear, do not include them.)
- Commit message ends with the trailer `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`.

---

## Done-when
- `engine/confluence.py` exposes `ConfluenceWeights`/`DEFAULT_WEIGHTS` (Q4 0.40/0.25/0.20/0.15), `trend_votes`/`momentum_votes`/`volatility_votes`/`volume_confirmation`, `composite_score`, `direction_for`, `conviction_for`, `build_signal` — signatures verbatim from contract §3.
- `composite_score(_gold_panel())[0]` reproduces the golden `0.8832`; `build_signal` returns a `MoverSignal` with all **7** `IndicatorVote`s.
- The reconcile test proves `votes` fully explain the score (family means × family weights × volume multiplier ⇒ score).
- Volume is a confirmation **multiplier** (`1 + 0.15·v`), never an additive family; ATR never votes.
- Golden fixture committed and locked via the #71 harness; `-m "not integration"` suite green; ruff clean on changed files.
- Single commit staging only the four #74 files; noise files stay unstaged.

## Self-review notes
- **§12.1 coverage:** trend (ADX-gated MACD + EMA-cross), momentum (RSI 70/30-saturating + stoch K/D cross), volatility (regime-aware Bollinger %B; ATR explicitly silent), volume (confirmation multiplier) — every voting rule is a closed-form, tested branch.
- **§12.2 composite:** `raw = Σ w_family·mean(vote_i)` then `· volume_confirmation`, clipped to `[-1,1]`, reproduced by the hand-derived `0.8832` golden and re-derived from the votes list in `test_votes_fully_reconcile_the_score`.
- **§20 Q4 weights:** trend 0.40 / momentum 0.25 / volatility 0.20 / volume 0.15-as-multiplier, frozen in `ConfluenceWeights`; the `0.15` volume weight manifests as the ±0.15 multiplier amplitude (documented), not an additive term.
- **Attribution reconciles:** `MoverSignal.votes` carries every indicator (incl. volume) with the weight actually used (re-stamped to `weights.<family>`), so the engine can answer "why long?" and the score reconstructs exactly.
- **No model change:** produces the existing frozen `MoverSignal`/`IndicatorVote` (`models.py`) untouched; consumes #72/#73 `IndicatorPanel` keys verbatim.
- **Determinism:** stdlib-only, no randomness, no I/O; missing warm-up keys are omitted (no raise); floats throughout (votes/weights/score are `float`, per the contract Decimal/float discipline).
- **Seam for #75:** `volume_confirmation` uses the Q4 default amplitude (no `weights` arg per contract); preset reweighting of volume is #75's job — #74 locks the Q4 default only.
