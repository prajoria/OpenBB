# openbb-techtrade

Segment-aware technical-indicator trading engine for the OpenBB Platform.

Maps GICS sectors to universes, ranks top movers, computes a `pandas-ta-classic`
indicator panel, fuses indicators via weighted confluence voting into an explainable
signal, builds risk-based trade plans with paper-filled recommendations, exports a
multi-sheet Excel workbook, and (optionally) validates robustness via `openbb-backtest`.

Status: **scaffold** (issue #65). See `docs/Specs/TechnicalTrading-Engine-PRD.md` for the
full functional spec and `docs/superpowers/plans/` for the delivery roadmap.

Public surface (incremental): `obb.techtrade.segments / movers / signals / plan / scan /
orders / simulate / export / validate / tune`.

## Vendored indicator engine (`external/pandas-ta-classic`)

The indicator engine is powered by the first-party MIT fork
[`prajoria/pandas-ta-classic`](https://github.com/prajoria/pandas-ta-classic),
vendored as a **commit-pinned git submodule** at
`external/pandas-ta-classic` and editable-installed into the dev venv.

- **Pinned commit:** `cfda99036ba64a4983e5871d42d1865743b7c6a9`
- **Bump policy:** advance the pin only via a reviewed PR (never auto-track `main`).

First-time / fresh-checkout setup:

```bash
# Fetch the pinned submodule contents
git submodule update --init openbb_platform/extensions/techtrade/external/pandas-ta-classic

# Editable install into the dev venv (.venv_win on Windows)
.venv_win\Scripts\python.exe -m pip install -e openbb_platform/extensions/techtrade/external/pandas-ta-classic
```

Smoke-tested by `tests/unit/test_pandas_ta_classic_smoke.py` (`import pandas_ta_classic`,
`df.ta.rsi()`, and a candlestick pattern on sample OHLCV).
