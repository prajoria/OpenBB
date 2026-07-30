# portfolio_utils

Portfolio-adjacent ad-hoc utilities — brokerage import, ETF/13F ingest, quant-strategy scraper.

Rehomed from the top-level `Tools/` directory in [gh-1628](https://github.com/prajoria/OpenBB/issues/1628). Nothing about the scripts themselves changed; only the package location, the import path in tests, and the sys.path bootstrap in the tests moved.

## Install

```bash
pip install -e openbb_platform/tools/portfolio_utils
```

## Scripts (flat modules under `portfolio_utils/`)

| Script | Purpose |
|---|---|
| `build_sp500_constituents.py` | Build S&P 500 constituent snapshot |
| `enrich_cusip_figi.py` | CUSIP → FIGI enrichment via OpenFIGI |
| `export_basket_weight_comparison.py` | Compare basket weights vs benchmark |
| `fetch_position_history.py` | Collect brokerage position history |
| `ingest_sec_13f.py` | 13F filings ingest |
| `load_espp_plan.py` | ESPP plan calculator |
| `make_venv_portable.py` | Venv portable-fication helper |
| `mortgage_amortization.py` | Mortgage amortization schedule |
| `parse_fidelity_positions.py` | Parse Fidelity Positions CSV |
| `populate_cusip_map.py` | Build CUSIP map |
| `populate_market_holidays.py` | Populate market holidays table |
| `portfolio_stats.py` | Portfolio statistics summary |
| `refresh_etf_holdings_cache.py` | Refresh ETF holdings cache |
| `share_cost_basis.py` | Cost-basis helpers |

## Sub-package

- `portfolio_utils/quant_scraper/` — TOML-configured quant strategy scraper (see [`quant_scraper/config.toml`](portfolio_utils/quant_scraper/config.toml)).

## Scheduler wrappers

`scheduler/` holds two PowerShell wrappers that operators run via Windows Task Scheduler:

- `run_fetch_position_history.ps1`
- `run_refresh_etf_holdings_cache.ps1`

Both wrappers hard-code the tool path. **After moving to `portfolio_utils/`, an operator that already had these registered under `Tools/` must update the scheduled task to the new path.**

## Docs

Per-tool specs, design docs, and run logs live under `docs_orig/` (verbatim carryover from `Tools/docs/`).

## Tests

```bash
.venv_portfolio/Scripts/python.exe -m pytest openbb_platform/tools/portfolio_utils/tests -v
```
