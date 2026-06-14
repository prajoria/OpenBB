# techtrade #73 — OpenBB technical adapter + reuse-first selector + parity oracle + bulk Strategy

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) tracking. TDD throughout. Read the locked cross-plan contract first: `docs/superpowers/plans/2026-06-13-techtrade-pipeline-contract.md`.

**Goal:** Add a **reuse-first selector** so each PRD §11 indicator is sourced from exactly one place — OpenBB's `technical` extension where it covers the indicator, the #72 pandas-ta-classic path otherwise — plus a **parity oracle** test proving the two sources agree within tolerance for the shared set, and a **bulk `Strategy` path** that computes panels for many symbols at once without the Windows multiprocessing fork-bomb.

**Architecture:** Three pieces. (1) `engine/indicators_technical.py` is a thin adapter that builds an `IndicatorPanel` by calling OpenBB-technical commands (passing the PRD §11 periods *explicitly*, because technical's own defaults differ), and degrades gracefully to the #72 classic builder when `openbb_technical` / `pandas_ta` are absent. (2) `engine/selector.py` owns the **one-source-per-indicator** decision via a static `INDICATOR_SOURCE` map and a public `build_panel(...)` that assembles a single panel from the chosen sources (default `source="auto"` = technical-where-covered, classic elsewhere), plus `build_panels_bulk(...)` for multi-symbol batches. (3) A parity oracle unit test (`importorskip("openbb_technical")`) runs only where technical is installed (CI), comparing classic-vs-technical per shared indicator within tolerance; it skips cleanly locally. Determinism rests on the #72 legs (fixed periods, pinned submodule, `talib=False`) plus the explicit period pass-through.

**Tech Stack:** Python 3.12, pandas, numpy, pandas-ta-classic (vendored), optional `openbb_technical` (parity/CI only), `openbb_techtrade.testing` golden harness (#71), pytest.

---

## Empirically-verified facts (probed against this checkout)

- `openbb_technical` / `pandas_ta` / `obb.technical` are **absent locally** → the adapter must wrap every technical call in a try/except seam and the parity test must `importorskip`.
- `technical_router` command **period defaults differ from PRD §11**: `bbands(length=50)`, `adx(length=50)`, `kc(scalar=20)`, `ema(length=50)`. The adapter MUST pass §11 periods explicitly (macd 12/26/9, ema 20 & 50, rsi 14, stoch 14/3/3, bbands 20/2, atr 14, kc 20/2, adx 14) or parity fails.
- `mamode`/`scalar` families *do* align with §11 (bbands sma, atr rma, kc ema, rsi/adx scalar=100).
- **Bulk Strategy fork-bomb fix (critical):** `df.ta` returns a FRESH accessor each property access, so `df.ta.cores = 0` does NOT stick. Bind ONE accessor instance, disable multiprocessing on it, then run a custom `ta.Strategy`:
  ```python
  import pandas_ta_classic as ta
  acc = df.ta                 # bind once
  acc.cores = 0               # disable spawn Pool (Windows fork-bomb guard)
  strat = ta.Strategy(name="techtrade_panel", ta=[
      {"kind": "macd", "fast": 12, "slow": 26, "signal": 9},
      {"kind": "adx", "length": 14}, {"kind": "ema", "length": 20},
      {"kind": "ema", "length": 50}, {"kind": "rsi", "length": 14},
      {"kind": "stoch", "k": 14, "d": 3, "smooth_k": 3},
      {"kind": "bbands", "length": 20, "std": 2.0}, {"kind": "atr", "length": 14},
      {"kind": "kc", "length": 20, "scalar": 2.0}, {"kind": "obv"},
      {"kind": "cmf", "length": 20},
  ])
  acc.strategy(strat)         # appends all indicator columns to df in one pass
  ```
  Probes confirmed this reproduces the #72 per-call values **and** the committed #72 golden to 1e-9 for all 14 panel values + 5 candle patterns. Any script that touches `acc.strategy` must run under `if __name__ == "__main__": mp.freeze_support()`.

**Indicator coverage (which source can serve each §11 key):**

| Panel key | technical command (explicit §11 periods) | classic fallback (#72) |
|---|---|---|
| `macd_hist` | `technical.macd(data, fast=12, slow=26, signal=9)` col `*_MACDh_12_26_9` | `df.ta.macd` |
| `adx` | `technical.adx(data, length=14)` col `ADX_14` | `df.ta.adx` |
| `ema_fast`/`ema_slow` | `technical.ema(data, length=20)` / `length=50` | `df.ta.ema` |
| `rsi` | `technical.rsi(data, length=14)` | `df.ta.rsi` |
| `stoch_k`/`stoch_d` | `technical.stoch(data, fast_k_period=14, slow_d_period=3, slow_k_period=3)` | `df.ta.stoch` |
| `bb_pctb` | `technical.bbands(data, length=20, std=2)` → derive %B from bands | `df.ta.bbands` col `BBP_` |
| `atr` | `technical.atr(data, length=14)` | `df.ta.atr` |
| `kc_upper`/`kc_lower` | `technical.kc(data, length=20, scalar=2)` | `df.ta.kc` |
| `obv_slope` | not covered → **classic** | `df.ta.obv`→`df.ta.slope` |
| `cmf` | not covered → **classic** | `df.ta.cmf` |
| candles | not covered → **classic** | `df.ta.cdl_pattern("all")` |

`INDICATOR_SOURCE` therefore maps the trend/momentum/volatility keys to `"technical"` and `obv_slope`/`cmf`/candles to `"classic"`; in `source="auto"` the technical keys fall back to classic when technical is unavailable (so a no-technical machine yields the exact #72 panel).

---

## Task 1: OpenBB-technical adapter (`engine/indicators_technical.py`)

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators_technical.py`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_indicators_technical.py`

**Design contract:**
- `_obb_technical_available() -> bool` — `True` iff `openbb_technical` (or `obb.technical`) is importable. Lazy; no raise.
- `_to_data_records(df) -> list[dict]` — convert the lowercase OHLCV frame to the `data=[{...}]` row shape technical commands accept, adding a synthetic ascending `date` index column (technical commands need an `index`).
- `technical_panel(symbol, as_of, ohlcv_rows, *, config=DEFAULT_CONFIG) -> IndicatorPanel` — builds the panel using technical commands with **explicit §11 periods** for the covered keys, and fills `obv_slope`/`cmf`/candles from the #72 classic helpers (`_compute_volume`, `_compute_candles` reused via import). If technical is unavailable, delegates wholesale to `build_indicator_panel` (#72) so the result is identical to classic.
- Reuse #72 helpers (`ohlcv_to_frame`, `_last_finite`, `_df_last_finite`, `_sign`) — import, don't re-implement (DRY).

- [ ] **Step 1: Write failing tests** `tests/unit/test_indicators_technical.py`

```python
"""Unit tests for the OpenBB-technical IndicatorPanel adapter (issue #73, PRD §8/§11).

Fully offline. Because openbb_technical is not installed in this checkout, the
adapter must degrade to the #72 pandas-ta-classic builder and return an identical
panel -- these tests lock that graceful-fallback contract plus the availability
probe. A seeded synthetic frame (last bar a doji) drives the build.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

pytest.importorskip("pandas_ta_classic")

from openbb_techtrade.engine.indicators import build_indicator_panel
from openbb_techtrade.engine.indicators_technical import (
    _obb_technical_available,
    technical_panel,
)
from openbb_techtrade.models import IndicatorPanel

_AS_OF = date(2024, 1, 12)


def _rows(n: int = 220) -> list[dict]:
    """Build deterministic OHLCV rows; force the last bar to a doji."""
    rng = np.random.default_rng(20240112)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.6, n))
    low = close - np.abs(rng.normal(0, 0.6, n))
    open_ = close + rng.normal(0, 0.4, n)
    vol = rng.integers(1_000, 8_000, n).astype(float)
    rows = [
        {"open": float(open_[i]), "high": float(high[i]), "low": float(low[i]),
         "close": float(close[i]), "volume": float(vol[i])}
        for i in range(n)
    ]
    mid = rows[-2]["close"]
    rows[-1] = {"open": mid, "high": mid + 2.0, "low": mid - 2.0, "close": mid, "volume": rows[-1]["volume"]}
    return rows


def test_availability_probe_is_bool():
    """Assert the technical-availability probe returns a plain bool, never raises."""
    assert isinstance(_obb_technical_available(), bool)


def test_technical_panel_returns_panel():
    """Assert technical_panel builds a populated IndicatorPanel for the symbol."""
    panel = technical_panel("TEST", _AS_OF, _rows())
    assert isinstance(panel, IndicatorPanel)
    assert panel.symbol == "TEST"
    assert panel.trend and panel.momentum and panel.volatility and panel.volume


def test_falls_back_to_classic_when_technical_absent():
    """Assert that, with technical absent, the panel equals the #72 classic panel."""
    if _obb_technical_available():
        pytest.skip("openbb_technical present; fallback path not exercised here")
    expected = build_indicator_panel("TEST", _AS_OF, _rows())
    assert technical_panel("TEST", _AS_OF, _rows()).model_dump() == expected.model_dump()
```

- [ ] **Step 2: Run, verify fail** — `…\.venv_win\Scripts\python.exe -m pytest tests/unit/test_indicators_technical.py -q` → ImportError (module missing).

- [ ] **Step 3: Implement `engine/indicators_technical.py`.** Module docstring states: OpenBB-technical adapter; passes §11 periods explicitly (technical defaults differ); reuses #72 classic helpers for `obv_slope`/`cmf`/candles and for the whole panel when technical is absent; lazy imports; float values. Use a single `_compute_technical_trend/_momentum/_volatility` block guarded by `_obb_technical_available()`; on any failure or absence, `return build_indicator_panel(symbol, as_of, ohlcv_rows, config=config)`.

- [ ] **Step 4: Run tests, verify pass.**

- [ ] **Step 5: Ruff clean** — `…\.venv_win\Scripts\python.exe -m ruff check openbb_techtrade/engine/indicators_technical.py tests/unit/test_indicators_technical.py`.

---

## Task 2: Reuse-first selector (`engine/selector.py`)

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/engine/selector.py`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_selector.py`

**Design contract:**
- `INDICATOR_SOURCE: dict[str, str]` — every panel key → `"technical"` or `"classic"` (per the coverage table). The audit record proving no indicator is computed twice.
- `build_panel(symbol, as_of, ohlcv_rows, *, config=DEFAULT_CONFIG, source="auto") -> IndicatorPanel` — `source="auto"` → `technical_panel` when available else `build_indicator_panel`; `source="classic"` → always #72; `source="technical"` → force technical adapter. Raises `ValueError` on an unknown `source`.
- `build_panels_bulk(frames, as_of, *, config=DEFAULT_CONFIG, source="auto") -> dict[str, IndicatorPanel]` — `frames: dict[symbol, ohlcv_rows]`; computes a panel per symbol. The bulk classic path binds one accessor with `cores=0` + custom `ta.Strategy` (per the verified snippet) and extracts the same keys; result must equal calling `build_panel` per symbol.

- [ ] **Step 1: Write failing tests** `tests/unit/test_selector.py`

```python
"""Unit tests for the reuse-first indicator source selector (issue #73, PRD §8).

Offline + deterministic. Locks: one source per indicator (no duplication), the
auto/classic/technical routing, ValueError on a bad source, and that the bulk
multi-symbol path returns the same panels as per-symbol build_panel.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

pytest.importorskip("pandas_ta_classic")

from openbb_techtrade.engine.selector import (
    INDICATOR_SOURCE,
    build_panel,
    build_panels_bulk,
)
from openbb_techtrade.models import IndicatorPanel

_AS_OF = date(2024, 1, 12)


def _rows(n: int = 220, seed: int = 20240112) -> list[dict]:
    """Build deterministic OHLCV rows for a given seed."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.6, n))
    low = close - np.abs(rng.normal(0, 0.6, n))
    open_ = close + rng.normal(0, 0.4, n)
    vol = rng.integers(1_000, 8_000, n).astype(float)
    return [
        {"open": float(open_[i]), "high": float(high[i]), "low": float(low[i]),
         "close": float(close[i]), "volume": float(vol[i])}
        for i in range(n)
    ]


def test_source_map_has_no_duplicate_assignment():
    """Assert each indicator key maps to exactly one source string."""
    assert set(INDICATOR_SOURCE.values()) <= {"technical", "classic"}
    assert "obv_slope" in INDICATOR_SOURCE and INDICATOR_SOURCE["obv_slope"] == "classic"


def test_build_panel_auto_returns_panel():
    """Assert auto source yields a populated panel."""
    panel = build_panel("TEST", _AS_OF, _rows(), source="auto")
    assert isinstance(panel, IndicatorPanel)
    assert panel.trend and panel.momentum and panel.volatility and panel.volume


def test_build_panel_classic_matches_72():
    """Assert source='classic' equals the #72 builder exactly."""
    from openbb_techtrade.engine.indicators import build_indicator_panel
    a = build_panel("TEST", _AS_OF, _rows(), source="classic").model_dump()
    b = build_indicator_panel("TEST", _AS_OF, _rows()).model_dump()
    assert a == b


def test_unknown_source_raises():
    """Assert an unknown source string raises ValueError."""
    with pytest.raises(ValueError):
        build_panel("TEST", _AS_OF, _rows(), source="bogus")


def test_bulk_matches_per_symbol():
    """Assert the bulk path equals per-symbol build_panel for each symbol."""
    frames = {"AAA": _rows(seed=1), "BBB": _rows(seed=2)}
    bulk = build_panels_bulk(frames, _AS_OF, source="classic")
    assert set(bulk) == {"AAA", "BBB"}
    for sym, rows in frames.items():
        assert bulk[sym].model_dump() == build_panel(sym, _AS_OF, rows, source="classic").model_dump()
```

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement `engine/selector.py`** (the `INDICATOR_SOURCE` map, `build_panel`, `build_panels_bulk` with the verified single-accessor `cores=0` Strategy snippet for the classic bulk path).
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Ruff clean** on both files.

---

## Task 3: Parity oracle + bulk golden lock

**Files:**
- Create: `tests/unit/test_selector_parity.py` (CI-only via `importorskip`)
- Create: `tests/golden/test_selector_golden.py`
- Create: `tests/golden/fixtures/selector_panel_synthetic.json` (via regen)

- [ ] **Step 1: Write the parity oracle** `tests/unit/test_selector_parity.py`:

```python
"""Parity oracle: pandas-ta-classic vs OpenBB-technical for the shared set (#73, PRD §8).

Runs ONLY where openbb_technical is installed (CI); importorskip skips it cleanly
on a checkout without the technical extension. For each indicator the selector
sources from `technical`, the classic value must agree within tolerance -- proving
"the same" indicator never diverges between sources.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

pytest.importorskip("pandas_ta_classic")
pytest.importorskip("openbb_technical")

from openbb_techtrade.engine.indicators import build_indicator_panel
from openbb_techtrade.engine.indicators_technical import technical_panel

_AS_OF = date(2024, 1, 12)
_TOL = 1e-6


def _rows(n: int = 220) -> list[dict]:
    """Build a deterministic synthetic OHLCV frame."""
    rng = np.random.default_rng(20240112)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.6, n))
    low = close - np.abs(rng.normal(0, 0.6, n))
    open_ = close + rng.normal(0, 0.4, n)
    vol = rng.integers(1_000, 8_000, n).astype(float)
    return [
        {"open": float(open_[i]), "high": float(high[i]), "low": float(low[i]),
         "close": float(close[i]), "volume": float(vol[i])}
        for i in range(n)
    ]


@pytest.mark.parametrize("family", ["trend", "momentum", "volatility"])
def test_classic_technical_parity(family):
    """Assert classic and technical agree within tolerance for shared-set keys."""
    classic = getattr(build_indicator_panel("X", _AS_OF, _rows()), family)
    tech = getattr(technical_panel("X", _AS_OF, _rows()), family)
    shared = set(classic) & set(tech)
    assert shared, f"no shared {family} keys to compare"
    for key in shared:
        assert abs(classic[key] - tech[key]) <= _TOL, f"{family}.{key} diverged"
```

- [ ] **Step 2: Write the bulk golden** `tests/golden/test_selector_golden.py` (locks `build_panels_bulk` over a 2-symbol seeded batch via `assert_matches_golden`, marker `golden`, fixture dir `fixtures/`). Mirror the #72 golden file's structure exactly.

- [ ] **Step 3: Generate the golden** — `TECHTRADE_REGEN_GOLDEN=1 …\.venv_win\Scripts\python.exe -m pytest tests/golden/test_selector_golden.py -q`, then **inspect** the JSON (two symbols, five families, plausible values) and commit it.

- [ ] **Step 4: Re-run without regen** — golden locks.

- [ ] **Step 5: Full gate** — `…\.venv_win\Scripts\python.exe -m pytest tests/ -m "not integration" -q` (parity test auto-skips locally; everything else green) and `…\.venv_win\Scripts\python.exe -m ruff check` on all changed files.

---

## Done-when
- `engine/indicators_technical.py` builds a panel from OpenBB-technical with §11 periods, degrading to the identical #72 panel when technical is absent.
- `engine/selector.py` exposes `INDICATOR_SOURCE` (one source per indicator), `build_panel(source=auto|classic|technical)`, and `build_panels_bulk` (single-accessor `cores=0` Strategy, fork-bomb-safe).
- Parity oracle passes within tolerance where technical is installed; skips cleanly locally.
- Bulk golden committed and locked; `-m "not integration"` suite green; ruff clean on changed files.
- Single commit staging only the #73 files (see contract §5). Noise files stay unstaged.

## Self-review notes
- §8 reuse-first satisfied: `INDICATOR_SOURCE` is the explicit one-source decision; no indicator computed twice in `auto`.
- §11 periods passed explicitly to technical (its defaults differ — bbands/adx 50, kc scalar 20, ema 50), the single most likely parity break.
- Determinism: classic bulk path proven equal to #72 to 1e-9; `cores=0` on a bound accessor avoids the Windows spawn fork-bomb.
- No model change (#73 produces the existing `IndicatorPanel`). DRY: reuses #72 helpers, never re-implements them.
- Parity test is `importorskip`-gated so the default local suite stays hermetic while CI enforces cross-source agreement.
