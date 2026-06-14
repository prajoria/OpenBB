# techtrade #72 — pandas-ta-classic adapter + IndicatorPanel builder

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) tracking. TDD throughout.

**Goal:** Build `engine/indicators.py` — the pure pandas-ta-classic → `IndicatorPanel` adapter that turns a symbol's OHLCV history into the five indicator families (trend / momentum / volatility / volume / candles) per PRD §11 default set, deterministically, with a DI-seam live wrapper and golden-value unit tests.

**Architecture:** A pure core `build_indicator_panel(symbol, as_of, ohlcv_rows, *, config)` converts OHLCV rows (dict or attribute) → a lowercase pandas DataFrame → `df.ta.*` (all with `talib=False` for native, cross-machine-stable math) → an `IndicatorPanel`. Each family computes the **as_of (last) bar** value; non-finite warm-up values are omitted so the panel only carries populated indicators. A thin live wrapper `build_panel_for_symbol` adds a `_default_ohlcv_fetcher` DI seam (lazy `openbb`, `fmp_cached` only) so unit tests stay offline and an integration test exercises the real path. Indicator *values* are `float`; periods are a frozen `IndicatorConfig` with PRD defaults (overridable). Determinism rests on fixed periods + the #71-guarded submodule pin + `talib=False`.

**Tech Stack:** Python 3.12, pandas, numpy, pandas-ta-classic (vendored submodule, editable top-level import `pandas_ta_classic`), `openbb_techtrade.testing` golden harness (#71), pytest.

---

## Empirically-verified API (probed against the pinned submodule, talib=False)

| Indicator | Call | Result kind | Selector |
|---|---|---|---|
| MACD hist | `df.ta.macd(fast, slow, signal, talib=False)` | DataFrame | col prefix `MACDh` |
| ADX | `df.ta.adx(length, talib=False)` | DataFrame | col prefix `ADX_` |
| EMA fast/slow | `df.ta.ema(length, talib=False)` | Series | use Series |
| RSI | `df.ta.rsi(length, talib=False)` | Series | use Series |
| Stoch k/d | `df.ta.stoch(k, d, smooth_k, talib=False)` | DataFrame | col prefixes `STOCHk` / `STOCHd` |
| Bollinger %B | `df.ta.bbands(length, std, talib=False)` | DataFrame | col prefix `BBP_` |
| ATR | `df.ta.atr(length, talib=False)` | Series | use Series |
| Keltner up/low | `df.ta.kc(length, scalar, talib=False)` | DataFrame | col prefixes `KCUe` / `KCLe` |
| OBV | `df.ta.obv(talib=False)` | Series | use Series |
| OBV slope | `df.ta.slope(close=<obv series>, length, talib=False)` | Series | use Series |
| CMF | `df.ta.cmf(length, talib=False)` | Series | use Series |
| Candles | `df.ta.cdl_pattern(name="all")` | 62-col DataFrame | last-bar nonzero → sign |

Column suffix int/float formatting (e.g. `_2` vs `_2.0`) varies, so **DataFrame columns are selected by prefix**, never by exact name. Candle values are TA-Lib style (`±100`, `±80`, `0`); normalise to `int` sign `-1/0/1`.

Canonical panel keys:
- **trend**: `macd_hist`, `adx`, `ema_fast`, `ema_slow`, `ema_cross` (= ema_fast − ema_slow)
- **momentum**: `rsi`, `stoch_k`, `stoch_d`
- **volatility**: `bb_pctb`, `atr`, `kc_upper`, `kc_lower`
- **volume**: `obv_slope`, `cmf`
- **candles**: `{pattern_name: sign}` for patterns that fired on the as_of bar

---

## Task 1: Pure indicator adapter (`engine/indicators.py`)

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators.py`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_indicators.py`

**Design contract:**
- `@dataclass(frozen=True) IndicatorConfig` with PRD-default periods (all int except `bb_std`, `kc_scalar` float). `DEFAULT_CONFIG = IndicatorConfig()`.
- `_get(row, key)` — dict-or-attribute reader (same idea as movers.py).
- `ohlcv_to_frame(rows) -> pd.DataFrame` — builds float columns `open/high/low/close/volume` (Decimal→float), preserving input order. Raises `ValueError` on empty input.
- `_col(df, prefix) -> str | None` — first column whose name starts with `prefix`.
- `_last_finite(series) -> float | None` — the last non-NaN value as float, else None.
- `_sign(x) -> int` — `1` if `x > 0`, `-1` if `x < 0`, else `0`.
- `_compute_trend/_momentum/_volatility/_volume(df, config) -> dict[str, float]` — each computes its indicators, stores only finite as_of-bar values (omit None).
- `_compute_candles(df) -> dict[str, int]` — `cdl_pattern("all")`, last bar, nonzero → `_sign`.
- `build_indicator_panel(symbol, as_of, ohlcv_rows, *, config=DEFAULT_CONFIG) -> IndicatorPanel` — pure, no network; assembles all five families.

- [ ] **Step 1: Write failing tests** `tests/unit/test_indicators.py`

```python
"""Unit tests for the pandas-ta-classic IndicatorPanel adapter (issue #72, PRD §11).

Fully offline and deterministic: a fixed synthetic OHLCV frame (seeded numpy) is
fed straight into the pure ``build_indicator_panel`` -- no network, no API key. The
last bar is forced into a textbook doji so the candles family is non-empty. Covers
the five families populating, float typing, candle-sign normalisation, the
dict/attribute row readers, graceful degradation on too-few bars, and determinism.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("pandas_ta_classic")

from openbb_techtrade.engine.indicators import (
    DEFAULT_CONFIG,
    IndicatorConfig,
    build_indicator_panel,
    ohlcv_to_frame,
)
from openbb_techtrade.models import IndicatorPanel

_AS_OF = date(2024, 1, 12)


def _synthetic_rows(n: int = 220) -> list[dict]:
    """Deterministic OHLCV rows; last bar forced to a textbook doji."""
    rng = np.random.default_rng(20240112)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.6, n))
    low = close - np.abs(rng.normal(0, 0.6, n))
    open_ = close + rng.normal(0, 0.4, n)
    vol = rng.integers(1_000, 8_000, n).astype(float)
    rows = [
        {
            "open": float(open_[i]),
            "high": float(high[i]),
            "low": float(low[i]),
            "close": float(close[i]),
            "volume": float(vol[i]),
        }
        for i in range(n)
    ]
    mid = rows[-2]["close"]
    rows[-1] = {"open": mid, "high": mid + 2.0, "low": mid - 2.0, "close": mid, "volume": rows[-1]["volume"]}
    return rows


def test_panel_populates_all_five_families():
    panel = build_indicator_panel("TEST", _AS_OF, _synthetic_rows())
    assert isinstance(panel, IndicatorPanel)
    assert panel.symbol == "TEST"
    assert panel.as_of == _AS_OF
    assert {"macd_hist", "adx", "ema_fast", "ema_slow", "ema_cross"} <= set(panel.trend)
    assert {"rsi", "stoch_k", "stoch_d"} <= set(panel.momentum)
    assert {"bb_pctb", "atr", "kc_upper", "kc_lower"} <= set(panel.volatility)
    assert {"obv_slope", "cmf"} <= set(panel.volume)
    assert panel.candles  # doji forced -> non-empty


def test_indicator_values_are_float():
    panel = build_indicator_panel("TEST", _AS_OF, _synthetic_rows())
    for family in (panel.trend, panel.momentum, panel.volatility, panel.volume):
        for value in family.values():
            assert isinstance(value, float)


def test_ema_cross_is_fast_minus_slow():
    panel = build_indicator_panel("TEST", _AS_OF, _synthetic_rows())
    assert panel.trend["ema_cross"] == pytest.approx(
        panel.trend["ema_fast"] - panel.trend["ema_slow"]
    )


def test_candle_signals_are_unit_ints():
    panel = build_indicator_panel("TEST", _AS_OF, _synthetic_rows())
    assert all(isinstance(v, int) and v in (-1, 0, 1) for v in panel.candles.values())
    assert all(v != 0 for v in panel.candles.values())  # only fired patterns kept


def test_accepts_attribute_rows():
    rows = [SimpleNamespace(**r) for r in _synthetic_rows()]
    panel = build_indicator_panel("TEST", _AS_OF, rows)
    assert panel.trend and panel.momentum


def test_accepts_decimal_volume():
    rows = _synthetic_rows()
    for r in rows:
        r["volume"] = Decimal(str(int(r["volume"])))
    panel = build_indicator_panel("TEST", _AS_OF, rows)
    assert "obv_slope" in panel.volume


def test_too_few_bars_degrades_without_raising():
    panel = build_indicator_panel("TEST", _AS_OF, _synthetic_rows(3))
    assert isinstance(panel, IndicatorPanel)
    # Long-period indicators cannot warm up; their keys are simply absent.
    assert "ema_slow" not in panel.trend


def test_empty_rows_raises_value_error():
    with pytest.raises(ValueError):
        build_indicator_panel("TEST", _AS_OF, [])


def test_panel_is_deterministic():
    rows = _synthetic_rows()
    a = build_indicator_panel("TEST", _AS_OF, rows).model_dump()
    b = build_indicator_panel("TEST", _AS_OF, rows).model_dump()
    assert a == b


def test_ohlcv_to_frame_lowercases_and_orders():
    frame = ohlcv_to_frame(_synthetic_rows(5))
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert len(frame) == 5


def test_default_config_matches_prd_periods():
    assert (DEFAULT_CONFIG.macd_fast, DEFAULT_CONFIG.macd_slow, DEFAULT_CONFIG.macd_signal) == (12, 26, 9)
    assert DEFAULT_CONFIG.ema_fast == 20 and DEFAULT_CONFIG.ema_slow == 50
    assert DEFAULT_CONFIG.rsi_length == 14 and DEFAULT_CONFIG.bb_length == 20
    assert isinstance(IndicatorConfig(), IndicatorConfig)
```

- [ ] **Step 2: Run, verify fail** — `… -m pytest tests/unit/test_indicators.py -q` → ImportError / fail.

- [ ] **Step 3: Implement `engine/indicators.py`** (full module; `talib=False` everywhere; prefix column selection; omit-on-non-finite). Module docstring must state: pure adapter, PRD §11 default set, determinism via fixed periods + pinned submodule + `talib=False`, DI-seam live wrapper, float values. Lazy-import `pandas_ta_classic` and `pandas` **inside** functions (keep module import light, mirror movers.py).

- [ ] **Step 4: Run tests, verify pass.**

- [ ] **Step 5: Ruff clean** — `…\.venv_win\Scripts\python.exe -m ruff check openbb_techtrade/engine/indicators.py tests/unit/test_indicators.py` (root ruff.toml, line-length 122).

---

## Task 2: Live DI-seam wrapper + integration test

**Files:**
- Modify: `openbb_techtrade/engine/indicators.py` (append `_default_ohlcv_fetcher`, `build_panel_for_symbol`)
- Test: `tests/unit/test_indicators.py` (add wrapper-with-fake-fetcher unit test)
- Create: `tests/integration/test_indicators_integration.py`

**Contract:**
- `_default_ohlcv_fetcher(symbol, as_of, *, lookback=260, calendar="XNYS") -> list` — lazy `from openbb import obb`; `obb.equity.price.historical(symbol, start_date, end_date=as_of, provider="fmp_cached")`; returns last `lookback` rows of `.results`. (`start_date` ≈ `as_of − 2*lookback` calendar days to cover non-trading days.)
- `build_panel_for_symbol(symbol, *, as_of=None, calendar="XNYS", ohlcv_fetcher=None, lookback=260, config=DEFAULT_CONFIG) -> IndicatorPanel` — snaps the session via `resolve_session` (import from `engine.movers`), calls the (injectable) fetcher, then `build_indicator_panel`. Default fetcher is the live one.

- [ ] **Step 1: Add failing unit test** (fake fetcher, offline):

```python
def test_build_panel_for_symbol_uses_injected_fetcher():
    from openbb_techtrade.engine.indicators import build_panel_for_symbol

    rows = _synthetic_rows()
    captured = {}

    def fake_fetcher(symbol, as_of, **kwargs):
        captured["symbol"] = symbol
        return rows

    panel = build_panel_for_symbol("ABC", as_of="2024-01-13", ohlcv_fetcher=fake_fetcher)
    assert captured["symbol"] == "ABC"
    assert panel.symbol == "ABC"
    assert panel.as_of == date(2024, 1, 12)  # Saturday snapped back to Friday
    assert panel.trend and panel.momentum and panel.volatility and panel.volume
```

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement the wrapper + default fetcher.**
- [ ] **Step 4: Run, verify pass.**

- [ ] **Step 5: Create integration test** `tests/integration/test_indicators_integration.py`:

```python
"""Integration test for the IndicatorPanel builder against live fmp_cached (#72).

Runs the real OHLCV fetcher (obb.equity.price.historical via fmp_cached) end to end
for a liquid symbol and asserts the four numeric families populate. Marked
``integration``; skips cleanly when credentials are missing or the source is
unreachable, so the default unit suite stays hermetic.
"""

from __future__ import annotations

from datetime import date

import pytest

from openbb_techtrade.engine.indicators import build_panel_for_symbol
from openbb_techtrade.models import IndicatorPanel

pytestmark = pytest.mark.integration


def test_indicator_panel_msft_live():
    try:
        panel = build_panel_for_symbol("MSFT")
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on creds / network
        pytest.skip(f"Live indicator panel unavailable for MSFT: {exc}")

    assert isinstance(panel, IndicatorPanel)
    assert panel.symbol == "MSFT"
    assert isinstance(panel.as_of, date)
    assert panel.trend and panel.momentum and panel.volatility and panel.volume
    assert isinstance(panel.candles, dict)  # may be empty if no pattern fires
```

- [ ] **Step 6: Run unit suite + ruff** (integration auto-skips without creds).

---

## Task 3: Golden-value lock + family-key documentation

**Files:**
- Create: `tests/golden/test_indicators_golden.py`
- Create: `tests/golden/fixtures/indicator_panel_synthetic.json` (via regen)

- [ ] **Step 1: Write golden test** `tests/golden/test_indicators_golden.py`:

```python
"""Golden-value regression lock for the IndicatorPanel builder (#72, #71 harness).

Builds the panel over a fixed seeded synthetic OHLCV frame (last bar forced to a
doji so the candles family is non-empty) and locks the full panel against a
committed golden JSON within DEFAULT_TOL. Carries the ``golden`` marker. Regenerate
intentionally after a *reviewed* change with TECHTRADE_REGEN_GOLDEN=1 -- never blindly.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pandas_ta_classic")

from openbb_techtrade.engine.indicators import build_indicator_panel
from openbb_techtrade.testing import assert_matches_golden

pytestmark = pytest.mark.golden

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_AS_OF = date(2024, 1, 12)


def _rows(n: int = 220) -> list[dict]:
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


def _snapshot():
    return build_indicator_panel("SYNTH", _AS_OF, _rows()).model_dump()


def test_indicator_panel_matches_golden():
    assert_matches_golden("indicator_panel_synthetic", _snapshot(), fixture_dir=_FIXTURE_DIR)


def test_indicator_panel_is_deterministic():
    assert _snapshot() == _snapshot()
```

- [ ] **Step 2: Generate the golden** — run with `TECHTRADE_REGEN_GOLDEN=1`, then **inspect** the JSON: all five families present, candles non-empty, values plausible. Commit the fixture.
- [ ] **Step 3: Re-run without regen** — golden test passes (locks).
- [ ] **Step 4: Full gate** — `… -m pytest tests/ -m "not integration" -q` (all techtrade unit+golden green) and `… -m ruff check` on the new/changed files.

---

## Done-when
- `engine/indicators.py` builds an `IndicatorPanel` with all five families from OHLCV (pure), `talib=False`, deterministic.
- Live DI-seam wrapper + integration test (skips offline).
- Golden fixture committed and locked via the #71 harness.
- Unit suite `-m "not integration"` green; ruff clean on changed files.
- Single commit staging only #72 files (engine/indicators.py, the three test files, the golden fixture). Noise files (`reference.json`, `package/__init__.py`, `agents/tests/test_config.py`) stay unstaged.

## Self-review notes
- Spec §11 default set fully covered (macd, adx, ema-cross, rsi, stoch, bbands %B, atr, kc, obv-slope, cmf, cdl_pattern all).
- §9.3 model already exists (no model change); keys match the model docstring examples (macd_hist, adx, ema_fast/slow, rsi, stoch_k/d, bb_pctb, atr, kc_upper, obv_slope, cmf, candle flags).
- Reuse-first OpenBB-technical selector is the **separate #73** issue — #72 is the pandas-ta-classic path only.
- Float/Decimal discipline: indicator values float; volume coerced Decimal→float only inside the frame.
- No new workflow YAML (rides #71 CI); golden uses the committed `openbb_techtrade.testing` harness.
