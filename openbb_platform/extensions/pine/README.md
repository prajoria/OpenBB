# openbb-extension-pine

**Run existing Pine Script indicators inside OpenBB, against your own OHLCV data or an FMP subscription — no TradingView account required, no third-party SaaS calls, no API keys beyond what you already have.**

> *Pine Script™ is a trademark of TradingView, Inc. This project is an independent, clean-room implementation providing Pine language compatibility inside the Python + OpenBB ecosystems. We are not affiliated with, endorsed by, or sponsored by TradingView or PyneSys LLC. Portions of the runtime are vendored from PyneCore™ (Apache-2.0, © PYNESYS LLC). PyneCore™ and PyneComp™ are trademarks of PYNESYS LLC. **Powered by PyneSys (https://pynesys.io).***

---

## What it does

- **Compile Pine v5 or v6 source** to Python via a clean-room compiler (lexer + parser + type-checker + codegen; no PyneComp or TradingView source ever viewed).
- **Execute** the compiled `@pyne` module through the vendored PyneCore runtime against OHLCV from:
  - **Your own DataFrame** (`records=[...]` — no FMP key needed)
  - **Your FMP subscription** (`provider="fmp"` or `"fmp_cached"`)
- Return results as a standard OpenBB `OBBject` — a `pandas.DataFrame` of per-bar plot values plus structured extras (alerts, cache-hit status, exec time, provider used).

**36 stdlib builtins ship in the M1 release** — `ta.sma`, `ta.ema`, `ta.rsi`, `ta.macd`, `ta.bb`, `ta.atr`, `ta.stoch`, `ta.cci`, `ta.adx`, `ta.mfi`, `ta.obv`, `ta.vwap`, `ta.crossover`, `ta.crossunder`, `ta.highest`, `ta.lowest`, `ta.stdev`, `ta.change`, `ta.mom`, `ta.roc`, `ta.tr`, `ta.sar`, `ta.linreg`, `ta.median`, `ta.percentile_linear_interpolation`, `ta.cum`, `ta.barssince`, `ta.wma`, `ta.rma`, plus `math.sum`, `math.abs`, `math.max`, `math.min`, `math.round`, `math.pow`, `math.sqrt`. Anything else raises `PineUnsupportedBuiltinError` with a tracking URL — file the request and we'll add it (each new builtin is one bead's worth of work).

---

## Install

```bash
pip install openbb-extension-pine
```

Or, from source (development):

```bash
git clone https://github.com/prajoria/OpenBB.git
cd OpenBB
pip install -e openbb_platform/extensions/pine
```

**FMP setup** (only if you want provider-mode; BYO-data mode needs nothing):

Set your FMP API key in `~/.openbb_platform/user_settings.json`:

```json
{"credentials": {"fmp_api_key": "YOUR_KEY_HERE"}}
```

**First-run check** — always run this after installing:

```bash
openbb-pine doctor
```

Sample healthy output:

```
[OK] Python 3.11+: Python 3.12.13
[OK] openbb-core installed: openbb-core 1.6.10 installed
[OK] openbb-fmp installed (required): openbb-fmp installed
[OK] openbb-fmp-cached installed (recommended): openbb-fmp-cached installed
[OK] FMP API key present: FMP API key present
[OK] FMP /api/v3/profile/AAPL reachable: HTTP 200
[OK] PyneCore importable: pynecore importable
[OK] Compile cache writable: writable: ~/.openbb/pine_cache
[OK] PyneSys attribution surfaces present (4/4): attribution constants intact
All checks passed.
```

If the FMP reachability check fails with HTTP 401, your FMP subscription plan may not include the `/api/v3/profile` endpoint. BYO-data mode still works — see example 1 below.

---

## Quickstart

### 1. Bring-your-own OHLCV (no FMP key needed) — the primary path

```python
from openbb import obb

# Real Pine v6 indicator source (paste from anywhere, no edits needed)
src = """//@version=6
indicator("BB", overlay=true)
length = input.int(20)
mult   = input.float(2.0)
basis  = ta.sma(close, length)
dev    = mult * ta.stdev(close, length)
plot(basis)
plot(basis + dev)
plot(basis - dev)
"""

# Your own OHLCV bars — any source (CSV, Parquet, KDB, custom API, etc.)
records = [
    {"date": "2024-01-02T00:00:00Z", "open": 184.1, "high": 186.4,
     "low": 183.9, "close": 185.6, "volume": 52341900},
    {"date": "2024-01-03T00:00:00Z", "open": 185.6, "high": 187.0,
     "low": 184.2, "close": 186.8, "volume": 48200100},
    # ... more bars (>= `length` for the SMA to warm up)
]

result = obb.pine.run_byo(
    source=src,
    records=records,
    symbol="AAPL",
)

# result.results — pandas.DataFrame indexed by date, one column per plot()
print(result.results.head())

# result.extra — D2 §6.1 metadata
print(result.extra["attribution"])       # "Powered by PyneSys (https://pynesys.io)"
print(result.extra["bars_consumed"])     # 2
print(result.extra["compile_cache_hit"]) # True on 2nd call with same source
print(result.extra["provider_used"])     # "byo"
```

### 2. Use your FMP subscription (provider mode)

```python
from openbb import obb

result = obb.pine.run(
    source=open("my_indicator.pine").read(),
    provider="fmp_cached",           # or "fmp" for live
    symbol="AAPL",
    interval="1d",
    start="2024-01-01",
    end="2024-12-31",
)

print(result.results.tail(20))
```

**FMP plan gotcha**: some plans don't include `/api/v3/profile/AAPL`. The doctor CLI catches this — if it flags a HTTP 401 there, expect provider mode to fail similarly. Fall back to BYO-data mode (example 1) or upgrade your FMP plan.

### 3. Direct API (sub-facade control)

For programmatic use where you want to inspect the compiled Python source, hold onto the `CompiledModule`, or feed a `pandas.DataFrame` directly (skipping the records→DataFrame conversion):

```python
import pandas as pd
from openbb_pine.compiler import compile_pine
from openbb_pine.runtime.executor import run_compiled

src = open("my_indicator.pine").read()

# Compile once (cached under ~/.openbb/pine_cache/<sha[:2]>/<sha>.py)
compiled = compile_pine(src, target_version=6)

print(f"Emitted Python:\n{compiled.source}")
print(f"Builtins used: {sorted(compiled.builtins_used)}")
print(f"Cache: {compiled.cache_status}, sha[:16]: {compiled.sha[:16]}")

# Execute against your own DataFrame (tz-aware DatetimeIndex required)
df = pd.read_parquet("aapl_1d.parquet")  # or any source
result = run_compiled(compiled, provider_or_data=df, symbol="AAPL")

print(result.results)
```

### 4. Pine v5 scripts run unedited

Just paste them — the C7 auto-migration shim rewrites `study(` → `indicator(`, `iff(...)` → ternary, `security(` → `request.security(`, and a handful of other common v5→v6 differences before the compiler sees the source.

```python
v5_src = """//@version=5
study("v5 script")
plot(ta.sma(close, 20))
"""
result = obb.pine.run_byo(source=v5_src, records=records, symbol="X")
# Works — v5 detected, migrated, compiled, run.
```

If your v5 source uses a construct C7 doesn't rewrite yet (rare), you'll get `PineUnsupportedFeatureError` with the specific construct named and a GitHub tracking-URL to file it.

---

## What the returned OBBject carries

`obb.pine.run(...)` and `obb.pine.run_byo(...)` return a bare `OBBject`:

| Field | Type | Meaning |
|---|---|---|
| `.results` | `pd.DataFrame` | Timestamp-indexed, one column per `plot()` in the compiled script (column name = `title=` arg, or `plot_N` if unnamed) |
| `.extra["alerts"]` | `list[{bar_index, ts, message}]` | Every `alert()` call the script fired |
| `.extra["orders"]` | `list` | `[]` for indicators; populated by strategies (M2) |
| `.extra["attribution"]` | `str` | Always `"Powered by PyneSys (https://pynesys.io)"` — PyneCore §4(d) compliance |
| `.extra["compile_cache_hit"]` | `bool` | Was the compilation served from `~/.openbb/pine_cache`? |
| `.extra["exec_ms"]` | `int` | Wall-clock ms from start of `ScriptRunner.run_iter()` to end (compile time excluded) |
| `.extra["provider_used"]` | `str` | `"fmp"`, `"fmp_cached"`, or `"byo"` |
| `.extra["bars_consumed"]` | `int` | Number of OHLCV bars the runtime processed |

---

## Command surface

```
GET   obb.pine.about()                       # Extension metadata + doctor status
POST  obb.pine.run(source, provider, ...)    # Provider-mode execution (FMP)
POST  obb.pine.run_byo(source, records, ...) # BYO-records execution
POST  obb.pine.compile(source)               # Lex + parse + return CompiledModule (no execute)
POST  obb.pine.strategies.run(...)           # M1 returns HTTP 501; strategies land at M2
GET   obb.pine.indicators.list()             # Bundled indicator widgets
GET   obb.pine.builtins.coverage()           # BUILTINS_IMPLEMENTED coverage snapshot
GET   obb.pine.health()                      # Extension health for uptime monitors
```

CLI:

```
openbb-pine doctor                      # 9-check health diagnostic
openbb-pine --version                   # Version + attribution banner
```

---

## What's shipping vs deferred

| M1 (this release) | Status |
|---|---|
| 36 Pine builtins (see list above) | ✅ |
| Pine v5 unedited via migration shim | ✅ |
| BYO OHLCV records mode | ✅ |
| FMP + fmp_cached provider mode | ✅ (subject to your FMP plan) |
| Bollinger Bands bundled Workspace widget | ✅ |
| Compile cache (blake2b, on-disk) | ✅ |
| MCP tool registration for bundled indicators | ✅ |
| Security sandbox (T1-T5 per PRD §5.2) | ✅ |
| `openbb-pine doctor` CLI | ✅ |
| **M2 next** — Strategies + `request.security` + more providers | 🚧 |
| **M3 next** — Long-tail builtins + libraries + drawings | 🚧 |

---

## When something fails

Every error subclasses `openbb_pine.errors.PineError` (which subclasses `openbb_core.app.model.abstract.error.OpenBBError`) and carries structured attributes serialized into the REST error envelope per PRD §4.8. Common ones:

- **`PineSyntaxError`** — lexer/parser refusal; carries `line`, `col`, `hint`.
- **`PineTypeError`** — static type-check failure; carries `expected`, `got`, `rule` (PT001-PT008).
- **`PineUnsupportedBuiltinError`** — the script uses a builtin not yet implemented; carries `builtin` (e.g. `"ta.ichimoku"`) + `tracking_url` to file a request.
- **`PineProviderError`** — non-FMP provider requested (only `fmp`/`fmp_cached` supported in v1.x); carries `supported`, `requested`, `tracking_url`.
- **`PineFMPUnreachableError`** — FMP call exhausted the retry budget; carries `provider`, `attempts`, `last_error`.
- **`PineExecTimeoutError`** — script exceeded its wall-clock cap (default 30 s).

All errors also surface via the middleware as JSON with the same fields, so REST callers get the same structured info.

---

## Attribution (required)

This extension vendors PyneCore, which is licensed under Apache 2.0 with a Section 4(d) attribution requirement. **The line "Powered by PyneSys (https://pynesys.io)" appears in four user-visible surfaces** to comply:

1. `/api/v1/pine/health` REST response body (`powered_by` field)
2. Bundled Workspace widget footer (every `pine.*` widget)
3. `obb.pine.about().results.powered_by`
4. `openbb-pine --version` CLI banner (first line)

Do not remove any of these surfaces. A CI test (`test_all_four_pynecore_attribution_surfaces`) asserts they all carry the exact literal string.

---

## License

**openbb-extension-pine** is licensed under **AGPL-3.0-only**. The vendored PyneCore at `third_party/pynecore/` retains its **Apache-2.0** license (submodules are aggregations, not derivative works — FSF guidance).

If you run this extension as a network service and modify it, AGPL §13 requires you to offer the modified source to network users. This aligns with the project's "no vendor lock-in" ethos.

---

## Reporting issues

- **Missing Pine builtin**: file at [GitHub Issues](https://github.com/prajoria/OpenBB/issues) with the `project:pine` + `pine-builtin` labels. Each new builtin is one bead's worth of work (bridge + `.pine` fixture + `.csv` reference).
- **v5 script that doesn't migrate cleanly**: file with the `pine-v5-migration` label + minimal repro.
- **Non-FMP provider needed**: file with the `pine-multi-provider` label; v2.0 unlocks per PRD §13.8 criteria (v1.x wild-corpus coverage ≥ 90 %, install-success rate stable ≥ 95 %, ≥ 3 issues requesting a specific non-FMP provider).

Powered by PyneSys (https://pynesys.io)
