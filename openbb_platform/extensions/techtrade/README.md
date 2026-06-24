# openbb-techtrade

Segment-aware technical-indicator trading engine for the OpenBB Platform.

*Outputs are paper / research — not investment advice.*

Maps the 11 GICS sectors to symbol universes, ranks top movers per sector, computes a
`pandas-ta-classic` indicator panel per symbol, fuses indicators via weighted confluence
voting into an explainable signal, builds risk-based trade plans with paper-filled
recommendations, exports a multi-sheet Excel workbook, validates plan robustness via
`openbb-backtest`, and (optionally) tunes per-segment indicator periods.

## Pipeline

```
                                                            ┌─→ obb.techtrade.export ──→ .xlsx (6 sheets)
                                                            │   (paper-filled plans)
segments → movers → indicator panel → signal → rule/sizing → orders → paper fills → recommendation
   #69       #70         #72/#73         #74        #76         #77       #78           #80
                                                            │
                                                            └─→ obb.techtrade.validate ──→ ValidationReport
                                                                (requires [validation])      verdict ∈ {robust, fragile, overfit}
                                                                                              #82
```

`obb.techtrade.tune(segment, ...)` (#83) is the optional period-tuner that proposes new
indicator periods per segment and writes them to `~/.openbb_platform/techtrade_tuned.json`
when they pass `validate`'s `verdict == "robust"` gate; subsequent `scan` / `plan` /
`signals` calls auto-load tuned periods transparently.

## Install

```powershell
# Core install (Windows / PowerShell — the canonical dev environment):
.\.venv_win\Scripts\python.exe -m pip install openbb-techtrade
```

```bash
# Core install (macOS / Linux):
python -m pip install openbb-techtrade
```

Soft-dep matrix (mirrors `[tool.poetry.extras]` in `pyproject.toml`):

| Extra | Install command | What it lights up |
|---|---|---|
| *(none)* | `pip install openbb-techtrade` | All commands except `validate` and `tune` (both raise `TechtradeDependencyError` with a pip-install hint when their extra is absent). |
| `[xlsxwriter]` | `pip install 'openbb-techtrade[xlsxwriter]'` | Lets `obb.techtrade.export(..., engine="xlsxwriter")` use the alternative Excel engine. The default `openpyxl` engine ships with the bare install. |
| `[validation]` | `pip install 'openbb-techtrade[validation]'` | Installs `openbb-backtest`; lights up `obb.techtrade.validate(plan, method="wfo")`. |
| `[tuneta]` | `pip install 'openbb-techtrade[tuneta]'` | Installs `tuneta`; lights up `obb.techtrade.tune(segment, ...)`. |

After a fresh checkout, fetch the pinned indicator submodule and editable-install the
extension into the dev venv:

```powershell
git submodule update --init openbb_platform/extensions/techtrade/external/pandas-ta-classic
.\.venv_win\Scripts\python.exe -m pip install -e openbb_platform/extensions/techtrade/external/pandas-ta-classic
```

Configure `~/.openbb_platform/user_settings.json` with `fmp_cached_api_key` (this fork
uses `fmp_cached` exclusively — never raw `fmp`, never `yfinance`):

```json
{
  "credentials": {
    "fmp_api_key": "YOUR_FMP_KEY",
    "fmp_cached_api_key": "YOUR_FMP_KEY"
  }
}
```

## Quickstart

```python
from openbb import obb

# 1. Scan all 11 GICS sectors for ranked, paper-filled trade plans:
plans = obb.techtrade.scan(metric="pct_change", top_n=5).results

# 2. Export the top plans to a 6-sheet Excel workbook:
path = obb.techtrade.export(plans=plans).results
print(f"workbook written to: {path}")
```

This snippet mirrors the live-path body of `openbb_techtrade/examples/scan_to_excel.py::main()`
(the example takes optional test seams the inline snippet omits); the smoke test in
`tests/unit/test_examples_smoke.py` guards the example's signatures + return shapes against
drift, which covers the kwarg names (`metric=`, `top_n=`, `plans=`) you see here.
See `openbb_techtrade/examples/` for the full runnable scripts:

- [`openbb_techtrade/examples/scan_to_excel.py`](./openbb_techtrade/examples/scan_to_excel.py) — headline `scan → export`
- [`openbb_techtrade/examples/plan_one_symbol.py`](./openbb_techtrade/examples/plan_one_symbol.py) — `plan → orders → simulate`
- [`openbb_techtrade/examples/validate_a_plan.py`](./openbb_techtrade/examples/validate_a_plan.py) — `plan → validate`
  (requires `[validation]`)

## Commands

`obb.techtrade.about()` → smoke probe; returns `{extension_name, extension_version}`.

`obb.techtrade.segments()` → list the 11 GICS sectors and their universe-source configs.

```python
sectors = obb.techtrade.segments().results
print(len(sectors), "sectors")
```

`obb.techtrade.movers(segment="Information Technology", metric="pct_change", top_n=10)` →
ranked top movers within one segment; returns `list[MoverList]`.

`obb.techtrade.signals(symbols=["MSFT"], preset="trend_follow")` → per-symbol confluence
score + vote attribution; returns `list[MoverSignal]`. Three presets ship: `trend_follow`
(default), `mean_revert`, `breakout`.

`obb.techtrade.plan(symbols=["MSFT"], preset="trend_follow", risk=0.01)` → complete
single-symbol plan with levels, sizing, broker-ready orders, and an inline
`Recommendation`; returns `list[TradePlan]`.

`obb.techtrade.scan(metric="pct_change", top_n=5, preset="trend_follow", risk=0.01)` →
cross-segment scan; runs `plan` across all 11 sectors and ranks the top plans by
conviction; returns `list[TradePlan]`. This is the daily morning-flow command.

`obb.techtrade.orders(plan=plan)` → materializes a single plan's order legs; returns
`list[Order]`. Idempotent round-trip.

`obb.techtrade.simulate(orders=orders, bars=...)` → paper-fills the order legs against
a forward bar window; returns `list[Fill]`. No look-ahead — bar-`t` signals fill at `t+1`
with slippage + commission.

`obb.techtrade.export(plans=plans, path=..., engine="openpyxl")` → writes a 6-sheet
Excel workbook (Recommendations / Levels / Reasoning / Orders / Fills / Summary) with
conditional formatting and the "research / paper — not investment advice" disclaimer on
the Recommendations sheet; returns the workbook path (`str`). Default `path` is
`Analysis/exports/techtrade_<date>.xlsx`. The `engine="xlsxwriter"` variant requires
the `[xlsxwriter]` extra.

`obb.techtrade.validate(plan=plan, method="wfo", horizon_years=5)` → robustness gate;
runs the techtrade confluence strategy over WFO (or `method="cpcv"`) folds, computes
PBO + Deflated Sharpe + OOS Sharpe, returns a `ValidationReport` with `verdict ∈ {robust,
fragile, overfit}`. Requires `pip install 'openbb-techtrade[validation]'`.

`obb.techtrade.tune(segment="Information Technology")` → per-segment indicator-period
tuner; runs `tuneta` against the pooled sector universe, validates the candidate via
`validate(...)`, persists only `verdict == "robust"` configs to
`~/.openbb_platform/techtrade_tuned.json`. Subsequent `scan` / `plan` / `signals` calls
auto-load the tuned periods transparently. Returns a `TuningReport` (with `persisted:
bool`, `reason: str`, and the candidate config). Requires `pip install
'openbb-techtrade[tuneta]'`.

## Roadmap

- `narrator` (#84) — deterministic per-sector briefing on top of the tune/scan output;
  not yet implemented.
- `MCP tool exposure` (#85) — surfacing the live `obb.techtrade.*` commands as MCP tools
  for external LLM clients; not yet implemented.
- `streaming / intraday` (#87) — O(1) streaming-indicator path and hourly/minute bars;
  not yet implemented.

## For Contributors

The sections below are for people changing techtrade, not using it.

### Vendored indicator engine (`external/pandas-ta-classic`)

The indicator engine is powered by the first-party MIT fork
[`prajoria/pandas-ta-classic`](https://github.com/prajoria/pandas-ta-classic), vendored
as a **commit-pinned git submodule** at `external/pandas-ta-classic` and editable-installed
into the dev venv.

- **Pinned commit:** `cfda99036ba64a4983e5871d42d1865743b7c6a9`
- **Bump policy:** advance the pin only via a reviewed PR (never auto-track `main`).

Smoke-tested by `tests/unit/test_pandas_ta_classic_smoke.py` (`import pandas_ta_classic`,
`df.ta.rsi()`, and a candlestick pattern on sample OHLCV).

### Testing & determinism

- Unit tests are fully offline — never touch `fmp_cached`. Run them with:

  ```powershell
  .\.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit -v
  ```

- Integration tests live under `tests/integration/` and are gated by
  `pytest.mark.integration` + skipif markers for any required soft-deps. Run them with:

  ```powershell
  .\.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/integration -v -m integration
  ```

- Golden-file tests (`tests/golden/`) lock content-level invariants: per-indicator panel
  values, confluence scores, the Excel workbook structure, no-look-ahead fill discipline.

- The drift-guard smoke (`tests/unit/test_examples_smoke.py`) keeps the examples and the
  README in sync — if you change an example's `main()` signature, the smoke fails until
  the README's Quickstart snippet matches.

### Bumping near the ~200 LOC threshold

This README is currently near ~200 lines. When the next user-facing surface (narrator
#84 or MCP #85) ships, split this README into a thinner `README.md` + a
`docs/quickstart.md` and move the *For Contributors* section to a new `CONTRIBUTING.md`
(per the design doc, [docs/designs/quant_trading/86-readme-usage-examples.md](../../../docs/designs/quant_trading/86-readme-usage-examples.md), Q-D / Q-E).
