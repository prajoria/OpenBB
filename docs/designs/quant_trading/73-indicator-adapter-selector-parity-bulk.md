# 73 — OpenBB `technical` Adapter + Reuse-First Selector + Parity Oracle + Bulk Strategy

**GitHub:** [#73](https://github.com/prajoria/OpenBB/issues/73) · **Phase:** P2 · **Sprint:** 2 · **Size:** L
**Depends on:** [#72](https://github.com/prajoria/OpenBB/issues/72) (pandas-ta-classic → IndicatorPanel adapter, **CLOSED**)
**Source PRD:** [`docs/Specs/TechnicalTrading-Engine-PRD.md`](../../Specs/TechnicalTrading-Engine-PRD.md) §8, §11, §19
**Scope:** Add the OpenBB `technical`-extension adapter, a single reuse-first **selector**, a
**parity oracle** test, and a bulk multiprocessing **Strategy** path to the `openbb-techtrade`
indicator engine.

> **Repo note:** code and docs live in the same `OpenBBTechnical` checkout. Implementation:
> [`../../../openbb_platform/extensions/techtrade/`](../../../openbb_platform/extensions/techtrade/).
> This design doc lives under `docs/designs/quant_trading/` (one doc per issue).

---

## What this is

This issue builds the **indicator layer** of techtrade: the part that turns raw OHLCV price bars
into a panel of named technical-indicator readings (RSI, MACD, ADX, ATR, Bollinger %B, …) that
every later stage votes on. It is foundational — nothing downstream (confluence voting, signals,
sizing, orders) can run until there is one trustworthy `IndicatorPanel` to read from.

Four ideas in the title, in plain terms:

- **Adapter** — OpenBB ships a maintained `technical` extension that already computes many of these
  indicators. Rather than re-derive them, this issue adds a thin wrapper (`technical_adapter.py`)
  that calls `technical`'s functions and converts their output into techtrade's `IndicatorPanel`
  shape. *Reuse the library that is already there.*
- **Reuse-first selector** — some indicators are best taken from `technical`, others only exist in
  the older `pandas-ta-classic` path. The **selector** is the single source of truth that decides,
  per indicator, *which* engine produces it (`SOURCE_TABLE`). Centralizing that decision in one
  module kills the "same indicator computed two different ways" duplication risk (PRD §19).
- **Parity oracle** — a test that computes the *same* indicator both ways (classic vs `technical`,
  and optionally `tulipy`) and asserts they agree within a tolerance. This is how we prove the
  adapter is faithful and that swapping engines did not silently change the numbers.
- **Bulk strategy** — a multiprocessing path (`bulk.py`) that runs the *same* selector across a pool
  of symbols in parallel, so screening hundreds of movers stays fast. Critically, bulk output is
  **identical** to single-symbol output (PRD §11 parity) — it is the same computation, just
  parallelized.

The defining posture (locked in §0, **D1**) is that `openbb-technical` is a **hard dependency**:
it is *authoritative* for the indicators it covers, so techtrade pulls it in unconditionally and
regenerates the #72 golden fixture for the covered keys. (Contrast [#82](./82-backtest-bridge-validate.md),
where `openbb-backtest` is deliberately a *soft/optional* dependency — validation is opt-in, but
indicators are not.) The output of this step — an authoritative, parity-checked `IndicatorPanel`
per symbol — is the input that the [#74 confluence engine](./74-confluence-voting-score.md) collapses
into a single directional score.

---

## 0. Key decisions (locked in brainstorming)

| # | Decision | Choice | Consequence |
|---|---|---|---|
| D1 | `openbb-technical` dependency posture | **Hard dependency (Option B)** — `technical` is **authoritative** for the indicators it covers | Pulls `pandas-ta-openbb` + scikit-learn into techtrade; #72 golden fixture is **regenerated** for covered keys |
| D2 | Covered set routed to `technical` | **Full overlap** — `macd_hist, adx, ema_fast, ema_slow, rsi, stoch_k, stoch_d, bb_pctb, atr, kc_upper, kc_lower` | `obv_slope, cmf, candles.*`, and derived `ema_cross` stay on `pandas-ta-classic` |
| D3 | Bulk path | **Symbol-pool** multiprocessing; each worker runs the **same** hybrid selector | Bulk output is identical to single-symbol (PRD §11 parity discipline), just parallelized |
| D4 | Parity oracle tolerance | **Relative 1e-3 + 1e-6 absolute floor**; `tulipy` optional third leg via `importorskip` | Tolerates Wilder/EMA seeding differences without masking real divergence |

---

## 1. Module layout (new + changed)

```
openbb_platform/extensions/techtrade/openbb_techtrade/engine/
├── indicators.py          # CHANGED — refactor family computes into per-indicator,
│                          #   individually-callable classic functions the selector reuses;
│                          #   build_indicator_panel() kept as the classic-only path.
├── technical_adapter.py   # NEW — pure wrappers over openbb_technical router functions:
│                          #   OHLCV frame -> list[Data] (synthetic date index) -> OBBject
│                          #   -> float(s) on the as_of (last) bar. No network.
├── selector.py            # NEW — the single reuse-first source-of-truth:
│                          #   SOURCE_TABLE {indicator_key -> "technical"|"classic"} and
│                          #   build_indicator_panel_hybrid(): covered keys <- technical_adapter,
│                          #   the rest <- classic. Authoritative panel builder for P3+.
└── bulk.py                # NEW — build_panels_bulk(symbols, ...): spawn-pool maps each symbol
                           #   through the SAME hybrid selector -> dict[str, IndicatorPanel].

openbb_platform/extensions/techtrade/tests/
├── unit/
│   ├── test_technical_adapter.py   # NEW — adapter returns finite floats; offline.
│   ├── test_selector.py            # NEW — selector routes each key to the right source.
│   └── test_bulk.py                # NEW — bulk == single-symbol; offline fakes.
└── golden/
    ├── test_indicator_parity.py    # NEW — parity oracle (classic vs technical [vs tulipy]).
    └── fixtures/indicator_panel_synthetic.json   # REGENERATED under review (D1).
```

**Module-boundary rules**
- `selector.py` is the **only** module that decides indicator → source. Nothing else encodes that
  mapping (kills the §19 "indicator duplication" risk).
- `technical_adapter.py` imports `openbb_technical.technical_router` functions **directly** (plain
  functions returning `OBBject[list[Data]]`) — no `obb.technical.*`, so it is unit-testable without
  `openbb.build()`.
- `bulk.py` calls `selector.build_indicator_panel_hybrid` per symbol; it never re-implements compute.
- `selector` and `bulk` depend only on `models`, `indicators`, `technical_adapter`. No cycles.

---

## 2. pyproject change (D1 — hard dependency)

```toml
# openbb_platform/extensions/techtrade/pyproject.toml
[tool.poetry.dependencies]
python = ">=3.10,<3.14"
openbb-core = "^1.6.10"
openbb-technical = "^1.6.2"   # NEW (D1) — reuse-first authoritative source for covered indicators
pandas = "*"
numpy = "*"
```

Install + rebuild (inside `.venv_win`, from repo root):

```powershell
cd openbb_platform; python dev_install.py -e
python -c "import openbb; openbb.build()"
# verify the technical source is importable for the adapter:
python -c "from openbb_technical.technical_router import rsi; print('technical OK')"
```

> `openbb-technical` wraps `pandas-ta-openbb` (a *different* fork than `pandas-ta-classic`). That is
> exactly why the parity oracle (§5) exists: "the same" indicator must not silently diverge between
> the two libraries.

---

## 3. `technical_adapter.py` — sourcing covered indicators from `technical`

The `technical` router functions expect `data: list[Data]` with a `date` index and emit columns
prefixed by the target (e.g. `close_RSI_14`). The engine's working frame is bare lowercase OHLCV
with no dates. The adapter bridges both ends and extracts the **as_of (last) bar** float.

```python
# technical_adapter.py  (pure; openbb_technical imported lazily inside functions)
from __future__ import annotations
from datetime import date, timedelta

def _ohlcv_to_dated_records(df, as_of: date) -> list[dict]:
    """Attach a synthetic *ascending* date index ending at as_of.

    All covered indicators (rsi/macd/ema/adx/stoch/bbands/atr/kc) are *bar-order*
    based, never calendar-anchored, so synthetic monotonic dates do not change
    their values. (Calendar-anchored indicators such as vwap are NOT in the
    covered set and are never routed here — enforced by selector.SOURCE_TABLE.)
    """
    n = len(df)
    dates = [(as_of - timedelta(days=(n - 1 - i))).isoformat() for i in range(n)]
    return [
        {"date": dates[i], "open": float(df["open"].iloc[i]),
         "high": float(df["high"].iloc[i]), "low": float(df["low"].iloc[i]),
         "close": float(df["close"].iloc[i]), "volume": float(df["volume"].iloc[i])}
        for i in range(n)
    ]

def _last_finite_by_suffix(obbject, suffix: str) -> float | None:
    """Last-bar value of the result column whose name ENDS WITH suffix.

    technical prefixes columns with the target (e.g. 'close_RSI_14'), so match by
    suffix ('RSI_14') rather than prefix. Returns None when missing / non-finite.
    """
    rows = obbject.results
    if not rows:
        return None
    last = rows[-1]
    record = last if isinstance(last, dict) else last.model_dump()
    for name, value in record.items():
        if str(name).endswith(suffix) and value is not None:
            f = float(value)
            return f if (f == f and abs(f) != float("inf")) else None
    return None
```

Per-indicator wrappers (one per covered key family) call the matching router function and pull the
as_of value(s). Examples — **periods are pinned to `IndicatorConfig` so technical and classic agree
on lookbacks**:

| Panel key(s) | `technical` fn + call | Output column suffix matched |
|---|---|---|
| `macd_hist` | `macd(data, fast, slow, signal)` | `MACDh_12_26_9` |
| `adx` | `adx(data, length)` | `ADX_14` |
| `ema_fast`, `ema_slow` | `ema(data, length=20)` / `ema(data, length=50)` | `EMA_20` / `EMA_50` |
| `rsi` | `rsi(data, length)` | `RSI_14` |
| `stoch_k`, `stoch_d` | `stoch(data, fast_k_period=14, slow_d_period=3, slow_k_period=3)` | `STOCHk_14_3_3` / `STOCHd_14_3_3` |
| `bb_pctb` | `bbands(data, length, std)` | `BBP_20_2.0` |
| `atr` | `atr(data, length)` | `ATRr_14` (match by `ATR` substring; mamode suffix tolerated) |
| `kc_upper`, `kc_lower` | `kc(data, length, scalar)` | `KCUe_20_2.0` / `KCLe_20_2.0` |

> **Column-name robustness:** match by **suffix/substring**, never exact name — the numeric-suffix
> formatting (`_2` vs `_2.0`) and mamode letters differ between the libraries, mirroring the
> prefix-matching discipline already used in `indicators.py::_col`.

> **⚠ Divergent `technical` defaults — every covered param MUST be passed explicitly.** Several
> `technical` router functions default to *different* parameters than techtrade's `IndicatorConfig`,
> so relying on their defaults would break parity for the same indicator:
>
> | `technical` fn | its default | `IndicatorConfig` value the adapter must pass |
> |---|---|---|
> | `kc` | `scalar=20`, `mamode="ema"` | `scalar=kc_scalar (2.0)`, `length=kc_length (20)` |
> | `bbands` | `length=50`, `mamode="sma"` | `length=bb_length (20)`, `std=bb_std (2.0)`, `mamode="sma"` |
> | `ema`/`rsi`/`adx`/`atr`/`macd`/`stoch` | standard | the matching `IndicatorConfig` lengths |
>
> The adapter pins `length`/`std`/`scalar`/`mamode` from `IndicatorConfig` on **every** call so the
> technical leg and the classic leg compute the *identical* parameterization. `mamode` is pinned to
> the classic side's mode (`bbands`→`sma`, `kc`→`ema`) so the emitted column suffixes (`BBP_*`,
> `KCUe_*`/`KCLe_*`) and the values both align. A unit test in `test_technical_adapter.py` asserts the
> adapter never invokes a covered fn with a library default that differs from `IndicatorConfig`.

**`ema_cross`** stays **derived** in the selector (`ema_fast - ema_slow`) — present only when both
EMAs are finite, exactly as #72 defines it.

---

## 4. `selector.py` — the reuse-first single source of truth (D2)

```python
# selector.py
SOURCE_TABLE: dict[str, str] = {
    # family, key            -> source
    "trend.macd_hist":  "technical",
    "trend.adx":        "technical",
    "trend.ema_fast":   "technical",
    "trend.ema_slow":   "technical",
    "trend.ema_cross":  "derived",      # ema_fast - ema_slow (no second compute)
    "momentum.rsi":     "technical",
    "momentum.stoch_k": "technical",
    "momentum.stoch_d": "technical",
    "volatility.bb_pctb":"technical",
    "volatility.atr":   "technical",
    "volatility.kc_upper":"technical",
    "volatility.kc_lower":"technical",
    "volume.obv_slope": "classic",
    "volume.cmf":       "classic",
    "candles.*":        "classic",
}

def build_indicator_panel_hybrid(symbol, as_of, ohlcv_rows, *, config=DEFAULT_CONFIG) -> IndicatorPanel:
    """Authoritative panel: covered indicators from technical, the rest from classic.

    Builds the frame once, computes the technical-sourced covered keys via
    technical_adapter, the classic-sourced keys via the (refactored) per-indicator
    classic functions, derives ema_cross, and assembles one IndicatorPanel. Yields
    exactly ONE value per indicator (no duplication) — the §19 mitigation.
    """
```

**Guarantees**
- **One value per indicator** — `SOURCE_TABLE` assigns each key exactly one source; the assembler
  reads from one place only.
- **Selector is total** — a unit test asserts every key the classic panel can emit appears in
  `SOURCE_TABLE` (no silently unrouted indicator).
- `build_indicator_panel_hybrid` becomes the panel builder consumed by P3 confluence (#74); the
  classic-only `build_indicator_panel` (#72) is retained for the parity oracle's classic leg.

---

## 5. `tests/golden/test_indicator_parity.py` — the parity oracle (D4)

Locks "the same indicator never diverges between sources" within tolerance, over a fixed seeded
synthetic OHLCV frame with a full 260-bar warmup.

```python
REL_TOL = 1e-3      # 0.1% relative — absorbs Wilder/EMA seeding differences
ABS_FLOOR = 1e-6    # absolute floor so near-zero values (e.g. macd_hist) don't explode rel error

def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(REL_TOL * max(abs(a), abs(b)), ABS_FLOOR)
```

- **Leg 1 vs Leg 2 (required):** for each covered key, compare `classic` value
  (`build_indicator_panel`) vs `technical` value (`technical_adapter`) via `_close`.
- **Leg 3 (optional):** `tulipy = pytest.importorskip("tulipy")` — when installed, cross-check
  `rsi/atr/adx/macd` against tulipy too; **skipped cleanly when absent** (it is not in the venv now).
- Carries the `golden` marker; deterministic (seeded RNG, fixed periods, submodule pin).

> **#72 golden regeneration (consequence of D1):** because `technical` (not `classic`) now supplies
> covered values in the authoritative panel, `indicator_panel_synthetic.json` shifts for those keys.
> Regenerate **once, under review** with `TECHTRADE_REGEN_GOLDEN=1`, and record the change in the PR
> body. The parity oracle is what justifies that the regenerated values are still "the same"
> indicator within tolerance.

---

## 6. `bulk.py` — symbol-pool Strategy path (D3)

```python
# bulk.py
def build_panels_bulk(symbols, *, as_of=None, calendar="XNYS",
                      ohlcv_fetcher=None, lookback=260, config=DEFAULT_CONFIG,
                      max_workers=None) -> dict[str, IndicatorPanel]:
    """Parallel per-symbol panels via a spawn process pool.

    Each worker runs the SAME build_indicator_panel_hybrid (selector), so the bulk
    result for a symbol is identical to its single-symbol panel — only parallelized
    (PRD §11 feature-parity discipline). Uses multiprocessing.get_context('spawn')
    for Windows/3.12 safety (PRD §19). The ohlcv_fetcher seam is injectable so unit
    tests run fully offline; the live default is the fmp_cached fetcher from #72.
    """
```

- **Pool model:** `get_context("spawn").Pool` (Windows/3.12-safe, per §19), worker fn at module top
  level so it is picklable; `as_of` resolved **once** in the parent and passed in (no per-worker
  look-ahead drift).
- **Parity by construction:** a unit test asserts `build_panels_bulk([A,B])[A] ==
  build_indicator_panel_hybrid(A, …)` for offline-fixture symbols.
- `df.ta.strategy()` (pandas-ta-classic's own multiprocessing) is intentionally **not** used: it
  would parallelize only the classic-sourced indicators and split the compute path; symbol-pool keeps
  one unified hybrid path (D3 rationale).

---

## 7. Determinism, performance & error handling

- **Determinism:** fixed `IndicatorConfig` periods, commit-pinned `pandas-ta-classic` submodule,
  `talib=False` on classic calls; technical periods pinned to the same config. Synthetic dates in the
  adapter are order-only and do not perturb values.
- **Short history:** non-finite warm-up values are omitted (key absent), unchanged from #72; the
  hybrid panel simply carries fewer keys for a short series rather than raising.
- **Missing `technical` at runtime:** D1 makes it a hard dep, so absence is an install error, not a
  silent fallback — surfaced at import of `technical_adapter`.
- **NFR (§17):** symbol-pool keeps bulk throughput ≈ `single_symbol_cost × n / cores`; spawn import
  cost is amortized across a segment's symbols.

---

## 8. Testing plan

| Test | Kind | Asserts |
|---|---|---|
| `test_technical_adapter.py` | unit (offline) | each covered wrapper returns a finite float on a seeded frame; suffix-matching picks the right column |
| `test_selector.py` | unit (offline) | `SOURCE_TABLE` is total over classic keys; each key routed once; `ema_cross` derived; hybrid panel populates all five families |
| `test_bulk.py` | unit (offline) | `bulk[sym] == hybrid(sym)` for fixture symbols; spawn-safe; deterministic |
| `test_indicator_parity.py` | golden | classic vs technical within `_close` for the shared set; optional tulipy leg `importorskip` |
| `indicator_panel_synthetic.json` | golden (regen) | regenerated authoritative panel locks under review |

Run:
```powershell
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests -m "not integration" -v
```

---

## Acceptance mapping (#73)

| Acceptance criterion (issue) | Satisfied by |
|---|---|
| Adapter sources rsi/macd/bbands/atr/adx/stoch/ema/… from OpenBB `technical` where covered | §2 (hard dep), §3 (`technical_adapter.py`, covered-set table) |
| Single **selector** decides source per indicator (reuse-first) | §4 (`selector.py`, `SOURCE_TABLE`, totality test) |
| Selector yields **one value per indicator** (no duplication) | §4 guarantees + `test_selector.py` |
| **Parity oracle** test: pandas-ta-classic vs technical (+ optional tulipy) within tolerance | §5 (`test_indicator_parity.py`, rel 1e-3 + abs floor, importorskip tulipy) |
| Parity test passes within tolerance for the shared set | §5 leg 1↔2; §0 D4 |
| Bulk **Strategy** path (multiprocessing) for many symbols | §6 (`bulk.py`, spawn symbol-pool) |
| Bulk path produces panels for a multi-symbol batch | §6 + `test_bulk.py` |
| (PRD §11) same definitions in batch & single — no silent divergence | §6 parity-by-construction (each worker runs the hybrid selector) |
| (PRD §19) indicator-duplication risk mitigated | §4 single source-of-truth + §5 oracle |
