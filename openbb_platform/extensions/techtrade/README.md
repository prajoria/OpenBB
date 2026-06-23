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

## Testing & determinism

The engine is deterministic and the test suite is fully offline (no API key, no
network). Run the unit + golden tests locally with:

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests -m "not integration" -q
```

- **Golden fixtures** live under `tests/golden/fixtures/`. A reusable helper,
  `openbb_techtrade.testing.assert_matches_golden`, locks deterministic engine
  outputs against committed JSON within a tight float tolerance. Regenerate a
  fixture only after a *reviewed* behavioral change by setting
  `TECHTRADE_REGEN_GOLDEN=1` — never blindly.
- **Lint + type gates** (ruff line-length 122 + mypy) run in CI via
  `general-linting.yml`; the unit suite — including the golden locks and the
  submodule-pin drift guard — runs via `test-unit-platform.yml`. No techtrade-
  specific workflow YAML is added; the harness rides the existing platform CI.
- **Submodule-pin discipline (§19):** `tests/unit/test_submodule_pin.py` fails CI
  if the vendored `pandas-ta-classic` pin drifts from the recorded commit. Bumping
  the submodule requires updating `EXPECTED_PIN` in that test and the pin in this
  README together, in the same reviewed PR.
