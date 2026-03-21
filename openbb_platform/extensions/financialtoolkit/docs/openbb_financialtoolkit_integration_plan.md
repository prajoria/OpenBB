# OpenBB FinancialToolkit Extension: Supercharged Integration Plan

> **Document version:** 1.0 — 2026-03-07
> **Scope:** Expanding the `openbb_financialtoolkit` extension with full FinanceToolkit capabilities, backed by `fmp_cached` MySQL persistence layer.

---

## 1. Context & Motivation

### What We Are Building

A comprehensive expansion of the `openbb_financialtoolkit` extension that deeply integrates **all** FinanceToolkit capabilities into the OpenBB Platform — going far beyond the current Phase 1–3 implementation. The extension will leverage `fmp_cached` as its primary data backend, taking full advantage of MySQL caching to make expensive analytical computations fast and reproducible.

### Why This Matters

| Problem | Solution |
|---|---|
| Existing extension covers only ~16 commands | Expand to ~70 commands across 8 domains |
| FinanceToolkit's 150+ ratios & 50+ indicators are unexposed | Wrap all major domains (ratios, technicals, performance, economics, fixed income) |
| Each FinanceToolkit call hits FMP API directly (slow, rate-limited) | Bridge via `fmp_cached` — financial statements and prices served from MySQL |
| Redundant API calls for the same symbols/dates | MySQL TTL caching means data fetched once, reused indefinitely |

### Current State (Already Implemented)

- **Extension scaffold:** `openbb_platform/extensions/financialtoolkit/`
- **Domains live:** `models`, `options`, `risk`, `performance`, `discovery`
- **Commands implemented (16):** `altman_z_score`, `piotroski_score`, `dupont`, `wacc`, `intrinsic_value`, `greeks`, `var`, `cvar`, `evar`, `garch`, `sharpe_ratio`, `sortino_ratio`, `information_ratio`, `screen`, `search`, `about`
- **Core adapter:** `adapters/toolkit_factory.py` → `create_toolkit()` creates a FinanceToolkit `Toolkit` instance

### Gap to Fill

- **Ratios:** 50+ financial ratios (profitability, efficiency, liquidity, solvency, valuation)
- **Technicals:** 40+ indicators (momentum, overlap, volatility, breadth)
- **Performance:** 8 additional metrics (alpha, beta, CAPM, Fama-French, etc.)
- **Economics:** 9 macroeconomic indicators (GDP, inflation, confidence indices)
- **Fixed Income:** 4 central bank / bond rate endpoints
- **fmp_cached bridge:** Data injection layer that pre-loads cached financial statements into FinanceToolkit

---

## 2. Architecture

### Data Flow

```
User → obb.financialtoolkit.<domain>.<command>()
         │
         ▼
  financialtoolkit_router.py         ← top-level router (prefix="")
         │
         ▼
  <domain>_router.py                 ← thin: param validation + examples
         │
         ▼
  <domain>_service.py                ← fat: FinanceToolkit call + normalize
         │
         ▼
  adapters/toolkit_factory.py        ← create_toolkit() or create_toolkit_with_cached_data()
         │
         ├─── fmp_cached provider ──→ MySQL database (TTL-backed cache)
         │         ↑                       ↑ IncomeStatement, BalanceSheet,
         │         └── on cache miss       CashFlow, EquityHistorical, KeyMetrics
         │
         ▼
  FinanceToolkit computation engine
         │
         ▼
  common/transform.py                ← DataFrame / Series → list[dict]
         │
         ▼
  OBBject[list[Data]]                ← returned to user
```

### fmp_cached Integration Strategy

The `fmp_cached` provider already persists these data types in MySQL:
- `IncomeStatement` (via `FMPCachedIncomeStatementFetcher`)
- `BalanceSheet` (via `FMPCachedBalanceSheetFetcher`)
- `CashFlowStatement` (via `FMPCachedCashFlowStatementFetcher`)
- `EquityHistorical` (via `FMPCachedEquityHistoricalFetcher`)
- `KeyMetrics` (via `FMPCachedKeyMetricsFetcher`)
- `FinancialRatios` (via `FMPCachedFinancialRatiosFetcher`)

The new `fmp_cached_bridge.py` adapter will:
1. Fetch these datasets via fmp_cached's MySQL-backed fetchers
2. Convert OpenBB data models → pandas DataFrames in FinanceToolkit's expected multi-index format
3. Inject DataFrames directly into a `Toolkit` instance (bypassing FinanceToolkit's own FMP fetch)
4. Fall back to direct FMP API if fmp_cached is not configured

---

## 3. New Domains to Implement

### 3.1 `ratios` — 50+ Financial Ratios

**FinanceToolkit source:** `financetoolkit/ratios/ratios_controller.py` (`Ratios` class)
**OpenBB namespace:** `obb.financialtoolkit.ratios.*`
**Priority: HIGH** ✅

#### Aggregate Commands

| Command | FinanceToolkit Method | Returns |
|---|---|---|
| `collect_all` | `ratios.collect_all_ratios()` | All 50+ ratios in one DataFrame |
| `efficiency` | `ratios.collect_efficiency_ratios()` | Asset turnover, CCC, DSO, DIO, DPO |
| `liquidity` | `ratios.collect_liquidity_ratios()` | Current, quick, cash, working capital |
| `profitability` | `ratios.collect_profitability_ratios()` | Gross/net margin, ROE, ROA, ROIC |
| `solvency` | `ratios.collect_solvency_ratios()` | Debt/equity, interest coverage, FCF yield |
| `valuation` | `ratios.collect_valuation_ratios()` | P/E, P/B, EV/EBITDA, dividend yield |

#### Individual Ratio Commands (single-metric, low-latency)

| Command | FinanceToolkit Method |
|---|---|
| `asset_turnover` | `ratios.get_asset_turnover_ratio()` |
| `inventory_turnover` | `ratios.get_inventory_turnover_ratio()` |
| `cash_conversion_cycle` | `ratios.get_cash_conversion_cycle()` |
| `current_ratio` | `ratios.get_current_ratio()` |
| `quick_ratio` | `ratios.get_quick_ratio()` |
| `gross_margin` | `ratios.get_gross_margin()` |
| `operating_margin` | `ratios.get_operating_margin()` |
| `net_profit_margin` | `ratios.get_net_profit_margin()` |
| `return_on_equity` | `ratios.get_return_on_equity()` |
| `return_on_assets` | `ratios.get_return_on_assets()` |
| `return_on_invested_capital` | `ratios.get_return_on_invested_capital()` |
| `return_on_capital_employed` | `ratios.get_return_on_capital_employed()` |
| `debt_to_equity` | `ratios.get_debt_to_equity_ratio()` |
| `interest_coverage` | `ratios.get_interest_coverage_ratio()` |
| `free_cash_flow_yield` | `ratios.get_free_cash_flow_yield()` |
| `price_to_earnings` | `ratios.get_price_to_earnings_ratio()` |
| `price_to_book` | `ratios.get_price_to_book_ratio()` |
| `ev_to_ebitda` | `ratios.get_ev_to_ebitda_ratio()` |
| `dividend_yield` | `ratios.get_dividend_yield()` |
| `earnings_per_share` | `ratios.get_earnings_per_share()` |

**Files to create:**
```
openbb_financialtoolkit/ratios/
  __init__.py
  ratios_router.py
  ratios_models.py
  ratios_service.py
```

---

### 3.2 `technicals` — 40+ Technical Indicators

**FinanceToolkit source:** `financetoolkit/technicals/technicals_controller.py` (`Technicals` class)
**OpenBB namespace:** `obb.financialtoolkit.technicals.*`
**Priority: HIGH** ✅

#### Aggregate Commands

| Command | FinanceToolkit Method | Returns |
|---|---|---|
| `collect_all` | `technicals.collect_all_indicators()` | All indicators in one call |
| `momentum` | `technicals.collect_momentum_indicators()` | RSI, MACD, Stochastic, Aroon, etc. |
| `overlap` | `technicals.collect_overlap_indicators()` | SMA, EMA, DEMA, Bollinger, TRIX |
| `volatility` | `technicals.collect_volatility_indicators()` | ATR, True Range, Keltner Channels |
| `breadth` | `technicals.collect_breadth_indicators()` | McClellan, OBV, ADL, Chaikin Osc. |

#### Individual Indicator Commands

| Command | FinanceToolkit Method |
|---|---|
| `rsi` | `technicals.get_relative_strength_index()` |
| `macd` | `technicals.get_moving_average_convergence_divergence()` |
| `bollinger_bands` | `technicals.get_bollinger_bands()` |
| `moving_average` | `technicals.get_moving_average()` |
| `ema` | `technicals.get_exponential_moving_average()` |
| `dema` | `technicals.get_double_exponential_moving_average()` |
| `atr` | `technicals.get_average_true_range()` |
| `stochastic` | `technicals.get_stochastic_oscillator()` |
| `ichimoku` | `technicals.get_ichimoku_cloud()` |
| `adx` | `technicals.get_average_directional_index()` |
| `obv` | `technicals.get_on_balance_volume()` |
| `williams_r` | `technicals.get_williams_percent_r()` |
| `cci` | `technicals.get_commodity_channel_index()` |
| `aroon` | `technicals.get_aroon_indicator()` |
| `support_resistance` | `technicals.get_support_resistance_levels()` |
| `mfi` | `technicals.get_money_flow_index()` |

**Files to create:**
```
openbb_financialtoolkit/technicals/
  __init__.py
  technicals_router.py
  technicals_models.py
  technicals_service.py
```

---

### 3.3 `performance` Extensions (extend existing domain)

**FinanceToolkit source:** `financetoolkit/performance/performance_controller.py` (`Performance` class)
**OpenBB namespace:** `obb.financialtoolkit.performance.*`
**Priority: HIGH** ✅

Additional commands (beyond existing `sharpe_ratio`, `sortino_ratio`, `information_ratio`):

| Command | FinanceToolkit Method |
|---|---|
| `beta` | `performance.get_beta()` |
| `alpha` | `performance.get_alpha()` |
| `capm` | `performance.get_capital_asset_pricing_model()` |
| `jensens_alpha` | `performance.get_jensens_alpha()` |
| `treynor_ratio` | `performance.get_treynor_ratio()` |
| `m2_ratio` | `performance.get_m2_ratio()` |
| `tracking_error` | `performance.get_tracking_error()` |
| `compound_growth_rate` | `performance.get_compound_growth_rate()` |
| `fama_french` | `performance.get_fama_and_french_model()` |
| `factor_correlations` | `performance.get_factor_correlations()` |

**Files to modify:**
```
openbb_financialtoolkit/performance/performance_router.py    ← add 10 commands
openbb_financialtoolkit/performance/performance_service.py   ← add 10 methods
openbb_financialtoolkit/performance/performance_models.py    ← add Pydantic models
```

---

### 3.4 `economics` — Macroeconomic Indicators *(Lower Priority)*

**FinanceToolkit source:** `financetoolkit/economics/economics_controller.py`
**OpenBB namespace:** `obb.financialtoolkit.economics.*`

| Command | FinanceToolkit Method |
|---|---|
| `gdp` | `economics.get_gross_domestic_product()` |
| `gdp_deflator` | `economics.get_gross_domestic_product_deflator()` |
| `inflation` | `economics.get_inflation_rate()` |
| `consumer_confidence` | `economics.get_consumer_confidence_index()` |
| `business_confidence` | `economics.get_business_confidence_index()` |
| `government_debt` | `economics.get_government_debt()` |
| `government_deficit` | `economics.get_government_deficit()` |
| `current_account` | `economics.get_current_account_balance()` |
| `exports` | `economics.get_exports()` |
| `imports` | `economics.get_imports()` |

**Files to create:**
```
openbb_financialtoolkit/economics/
  __init__.py
  economics_router.py
  economics_models.py
  economics_service.py
```

---

### 3.5 `fixedincome` — Fixed Income Analytics *(Lower Priority)*

**FinanceToolkit source:** `financetoolkit/fixedincome/fixedincome_controller.py`
**OpenBB namespace:** `obb.financialtoolkit.fixedincome.*`

| Command | FinanceToolkit Method |
|---|---|
| `bond_valuation` | `fixedincome` bond methods |
| `euribor` | Euribor rate methods |
| `fed_funds` | Federal Reserve rate methods |
| `ecb_rates` | ECB rate methods |

**Files to create:**
```
openbb_financialtoolkit/fixedincome/
  __init__.py
  fixedincome_router.py
  fixedincome_models.py
  fixedincome_service.py
```

---

## 4. fmp_cached Deep Integration Bridge

### New File: `adapters/fmp_cached_bridge.py`

This is the critical new component that eliminates redundant FMP API calls by pre-loading data from the MySQL cache.

**Responsibility:**
1. Detect if `fmp_cached` credentials are configured
2. Fetch financial statements and historical price data via `fmp_cached` fetchers
3. Convert OpenBB data models → multi-index pandas DataFrames (FinanceToolkit's expected format)
4. Return a pre-loaded `Toolkit` instance that never calls FMP internally
5. Fallback to direct FMP API if fmp_cached is not available

**Extension to `adapters/toolkit_factory.py`:**

```python
def create_toolkit_with_cached_data(symbols, api_key, credentials=None, **kwargs):
    """
    Create a FinanceToolkit Toolkit instance pre-loaded with fmp_cached data.
    Falls back to direct FMP if fmp_cached credentials are not configured.
    """
    from openbb_financialtoolkit.adapters.fmp_cached_bridge import (
        build_toolkit_from_cache,
    )
    return build_toolkit_from_cache(symbols, api_key, credentials, **kwargs)
```

**Bridge data transformation map:**

| fmp_cached Fetcher | FinanceToolkit Constructor Param |
|---|---|
| `FMPCachedIncomeStatementFetcher` | `income_statement` (DataFrame) |
| `FMPCachedBalanceSheetFetcher` | `balance_sheet_statement` (DataFrame) |
| `FMPCachedCashFlowStatementFetcher` | `cash_flow_statement` (DataFrame) |
| `FMPCachedEquityHistoricalFetcher` | `historical` (dict of DataFrames) |

---

## 5. Complete File Change List

### Files to Create (24 new files)

| # | File Path | Purpose |
|---|---|---|
| 1 | `adapters/fmp_cached_bridge.py` | MySQL cache → FinanceToolkit data injection |
| 2 | `ratios/__init__.py` | Package init |
| 3 | `ratios/ratios_router.py` | 20+ ratio commands |
| 4 | `ratios/ratios_models.py` | Pydantic response models |
| 5 | `ratios/ratios_service.py` | FinanceToolkit wrapper logic |
| 6 | `technicals/__init__.py` | Package init |
| 7 | `technicals/technicals_router.py` | 16+ indicator commands |
| 8 | `technicals/technicals_models.py` | Pydantic response models |
| 9 | `technicals/technicals_service.py` | FinanceToolkit wrapper logic |
| 10 | `economics/__init__.py` | Package init |
| 11 | `economics/economics_router.py` | 9 economics commands |
| 12 | `economics/economics_models.py` | Pydantic response models |
| 13 | `economics/economics_service.py` | FinanceToolkit wrapper logic |
| 14 | `fixedincome/__init__.py` | Package init |
| 15 | `fixedincome/fixedincome_router.py` | 4 fixed income commands |
| 16 | `fixedincome/fixedincome_models.py` | Pydantic response models |
| 17 | `fixedincome/fixedincome_service.py` | FinanceToolkit wrapper logic |
| 18 | `docs/openbb_financialtoolkit_integration_plan.md` | This document |

### Files to Modify (6 existing files)

| # | File Path | Changes |
|---|---|---|
| 1 | `financialtoolkit_router.py` | Include 4 new sub-routers (ratios, technicals, economics, fixedincome) |
| 2 | `adapters/toolkit_factory.py` | Add `create_toolkit_with_cached_data()` function |
| 3 | `performance/performance_router.py` | Add 10 new performance commands |
| 4 | `performance/performance_service.py` | Add 10 new service methods |
| 5 | `performance/performance_models.py` | Add Pydantic models for new responses |
| 6 | `pyproject.toml` | Bump version to `0.2.0` |

### Docs to Update

| File | Update |
|---|---|
| `docs/COMMAND_COVERAGE_MATRIX.md` | Add ~54 new rows for all new commands |
| `docs/USAGE_GUIDE.md` | Add sections for ratios, technicals, extended performance |

---

## 6. Reusable Patterns & Utilities

Every new file should follow the patterns established in the existing codebase:

| Utility | File Location | Use Case |
|---|---|---|
| `create_toolkit()` | `adapters/toolkit_factory.py` | Base Toolkit creation in all services |
| `records_to_data()` | `common/transform.py` | Normalize DataFrame output → OBBject |
| `validate_symbols()` | `common/validators.py` | Symbol input validation in all routers |
| `RiskService` class structure | `risk/risk_service.py` | Template for new service class pattern |
| `risk_router.py` structure | `risk/risk_router.py` | Template for new router file pattern |
| `DomainCapability` model | `risk/risk_models.py` | Reuse for `capabilities()` commands |
| `FinancialToolkitDependencyError` | `exceptions.py` | Dependency guard in all new services |
| `execute_query()` / `execute_many()` | `providers/fmp_cached/openbb_fmp_cached/utils/database.py` | fmp_cached_bridge.py database access |
| `FMPCachedIncomeStatementFetcher` | `providers/fmp_cached/openbb_fmp_cached/models/income_statement.py` | Bridge data fetching |

---

## 7. Standard Command Signature

Every command in every new domain follows this parameter contract for consistency:

```python
def <command_name>(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: Literal["daily", "weekly", "monthly", "quarterly", "yearly"] | None = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    # domain-specific params below...
) -> OBBject[list[Data]]:
```

Each domain also exposes a `capabilities()` command that returns a list of `DomainCapability` objects for discoverability.

---

## 8. Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Router pattern | Thin routers, fat services | Consistent with existing OpenBB extension patterns |
| Data backend | **fmp_cached FIRST** (cache-first, auto-fallback to FMP) | Eliminates redundant API calls; MySQL cache serves all repeated requests |
| Fallback behaviour | Direct FMP if fmp_cached is unconfigured | Zero-config experience preserved |
| Cache toggle | NOT user-configurable per-call (always-on) | Simpler API; cache is always beneficial |
| Output format | All outputs via `common/transform.py` → `OBBject[list[Data]]` | Uniform experience, `.to_df()` always works |
| Domain discovery | `capabilities()` command on every domain | Enables programmatic introspection of available commands |
| Version | Bump to `0.2.0` | Reflects major feature expansion |
| Implementation priority | **Ratios → Technicals → Performance → Economics/Fixed Income** | Highest analytical value first |

---

## 9. Implementation Phases & PR Breakdown

### Phase 4: Ratios Domain *(Highest Priority)*
- **PR-4a:** `ratios` scaffold + `collect_all`, `efficiency`, `liquidity`, `profitability`, `solvency`
- **PR-4b:** `valuation` ratios + all individual single-metric commands + tests

### Phase 5: Technicals Domain *(High Priority)*
- **PR-5a:** `technicals` scaffold + `collect_all`, `momentum`, `overlap`, `volatility`, `breadth`
- **PR-5b:** Individual indicator commands (RSI, MACD, Bollinger, ATR, Stochastic, Ichimoku, ADX, OBV)

### Phase 6: Performance Extensions *(High Priority)*
- **PR-6:** Add `alpha`, `beta`, `capm`, `jensens_alpha`, `treynor_ratio`, `m2_ratio`, `tracking_error`, `compound_growth_rate`, `fama_french`, `factor_correlations`

### Phase 7: fmp_cached Bridge *(Critical Infrastructure)*
- **PR-7:** Implement `fmp_cached_bridge.py` — MySQL data injection, credential resolution, DataFrame conversion. This PR retroactively accelerates all existing and new commands.

### Phase 8: Economics + Fixed Income *(Lower Priority)*
- **PR-8a:** `economics` domain (GDP, inflation, confidence indices, government metrics)
- **PR-8b:** `fixedincome` domain (bond valuation, EURIBOR, Fed Funds, ECB rates)

### Phase 9: Documentation Completion
- **PR-9:** Update `COMMAND_COVERAGE_MATRIX.md`, `USAGE_GUIDE.md`; add notebook examples; final version bump

---

## 10. Expanded Command Coverage After All Phases

| Domain | Commands Before | Commands After |
|---|---|---|
| `models` | 5 | 5 |
| `options` | 1 | 1 |
| `risk` | 4 | 4 |
| `performance` | 3 | **13** |
| `discovery` | 2 | 2 |
| `ratios` | — | **20** |
| `technicals` | — | **16** |
| `economics` | — | **10** |
| `fixedincome` | — | **4** |
| **Total** | **16** | **~75** |

---

## 11. Verification & Testing Plan

```bash
# Step 1: Install updated extension
cd I:/masterswork/git/OpenBB/openbb_platform/extensions/financialtoolkit
pip install -e .

# Step 2: Rebuild OpenBB package index
python -c "import openbb; openbb.build()"

# Step 3: Smoke test — about() still works
python -c "from openbb import obb; print(obb.financialtoolkit.about())"

# Step 4: Smoke test — new ratios domain
python -c "
from openbb import obb
r = obb.financialtoolkit.ratios.profitability(symbols=['AAPL'], api_key='YOUR_KEY')
print(r.results[:2])
"

# Step 5: Smoke test — new technicals domain
python -c "
from openbb import obb
t = obb.financialtoolkit.technicals.rsi(symbols=['AAPL'], api_key='YOUR_KEY')
print(t.results[:5])
"

# Step 6: Smoke test — extended performance
python -c "
from openbb import obb
p = obb.financialtoolkit.performance.beta(symbols=['AAPL'], api_key='YOUR_KEY')
print(p.results)
"

# Step 7: Unit tests
pytest openbb_platform/extensions/financialtoolkit/tests/ -v -m "not integration"

# Step 8: Integration tests (requires FMP API key + MySQL)
pytest openbb_platform/extensions/financialtoolkit/integration/ -v -m integration

# Step 9: Verify fmp_cached bridge (requires MySQL configured)
python -c "
from openbb_financialtoolkit.adapters.fmp_cached_bridge import build_toolkit_from_cache
tk = build_toolkit_from_cache(['AAPL'], api_key='YOUR_KEY')
print(tk.ratios.get_gross_margin())
"
```

---

## 12. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| FinanceToolkit constructor signature changes | Low | High | `toolkit_factory.py` already uses `inspect.signature` for tolerant mapping |
| fmp_cached MySQL not configured (dev env) | Medium | Low | Full fallback to direct FMP API — zero feature loss |
| Multi-index DataFrame format mismatch | Medium | Medium | Central `fmp_cached_bridge.py` owns all format conversions; unit-test with fixtures |
| FinanceToolkit output shape variability | Medium | Medium | Central `common/transform.py` owns normalization; contract tests on representative outputs |
| Version drift between OpenBB and FinanceToolkit | Low | Medium | Pin `financetoolkit` in `pyproject.toml`; add startup compatibility check in `about()` |

---

*End of plan document.*
