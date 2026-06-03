# OpenBB Extensions — Deep Dive

> **Purpose:** Complete reference for all 19 core extensions (routers),
> their sub-routers, commands, and the obbject extension system.
>
> **See also:** `context/openbb/CORE.md` for Router and ExtensionLoader details.

---

## 1. Extension Types

| Type | Entry Point Group | What It Provides |
|------|-------------------|------------------|
| **Core** | `openbb_core_extension` | API routes (Router objects) |
| **Provider** | `openbb_provider_extension` | Data sources (Provider objects) |
| **OBBject** | `openbb_obbject_extension` | Result post-processors (Extension objects) |

This file covers **core extensions** (routers) and **obbject extensions**.
For providers, see `context/openbb/PROVIDERS.md`.

---

## 2. All 19 Core Extensions

### 2.1 Equity (`/equity`)

**Package:** `openbb_equity` | **9 sub-routers, 5 top-level commands**

| Sub-Router | Prefix | Key Commands |
|-----------|--------|--------------|
| `calendar` | `/calendar` | `dividends`, `earnings`, `ipo`, `splits` |
| `compare` | `/compare` | `peers`, `company_facts`, `groups` |
| `darkpool` | `/darkpool` | `otc` |
| `discovery` | `/discovery` | `active`, `gainers`, `losers`, `filings` |
| `estimates` | `/estimates` | `analyst`, `forward_eps`, `forward_ebitda`, `forward_sales`, `forward_pe`, `price_target`, `consensus` |
| `fundamental` | `/fundamental` | `balance`, `income`, `cash`, `ratios`, `metrics`, `dividends`, `earnings`, `management`, `overview`, `revenue_per_geography`, `revenue_per_segment`, `transcript`, `multiples`, `reported_financials`, `historical_eps` |
| `ownership` | `/ownership` | `institutional`, `insider_trading`, `share_statistics` |
| `price` | `/price` | `historical`, `quote`, `nbbo`, `performance` |
| `shorts` | `/shorts` | `fails_to_deliver`, `short_volume`, `short_interest` |

**Top-level commands:**
- `search` → `EquitySearch`
- `screener` → `EquityScreener`
- `profile` → `EquityInfo`
- `market_snapshots` → `MarketSnapshots`
- `historical_market_cap` → `HistoricalMarketCap`

### 2.2 Economy (`/economy`)

**Package:** `openbb_economy` | **3 sub-routers, 22+ top-level commands**

| Sub-Router | Prefix | Key Commands |
|-----------|--------|--------------|
| `gdp` | `/gdp` | `nominal`, `real`, `forecast` |
| `shipping` | `/shipping` | `port_info`, `port_volume`, `chokepoint_info`, `chokepoint_volume` |
| `survey` | `/survey` | `economic_conditions_chicago`, `manufacturing_outlook_texas`, `university_of_michigan`, `sloos` |

**Top-level commands:** `calendar`, `cpi`, `risk_premium`, `balance_of_payments`,
`fred_search`, `fred_series`, `fred_release_table`, `money_measures`,
`unemployment`, `composite_leading_indicator`, `fred_regional`,
`country_profile`, `available_indicators`, `indicators`,
`central_bank_holdings`, `share_price_index`, `house_price_index`,
`interest_rates`, `retail_prices`, `primary_dealer_positioning`, `pce`,
`export_destinations`, `primary_dealer_fails`, `direction_of_trade`,
`fomc_documents`

### 2.3 ETF (`/etf`)

**Package:** `openbb_etf` | **1 sub-router, 9 top-level commands**

| Sub-Router | Prefix | Key Commands |
|-----------|--------|--------------|
| `discovery` | `/discovery` | `active`, `gainers`, `losers` |

**Top-level commands:** `search`, `historical`, `info`, `sectors`,
`countries`, `price_performance`, `holdings`, `nport_disclosure`,
`equity_exposure`

### 2.4 Crypto (`/crypto`)

**Package:** `openbb_crypto` | **1 sub-router, 1 top-level command**

| Sub-Router | Prefix | Key Commands |
|-----------|--------|--------------|
| `price` | `/price` | `historical` |

**Top-level:** `search` → `CryptoSearch`

### 2.5 Currency (`/currency`)

**Package:** `openbb_currency` | **1 sub-router, 2 top-level commands**

| Sub-Router | Prefix | Key Commands |
|-----------|--------|--------------|
| `price` | `/price` | `historical` |

**Top-level:** `search` → `CurrencyPairs`, `snapshots` → `CurrencySnapshots`

### 2.6 Derivatives (`/derivatives`)

**Package:** `openbb_derivatives` | **2 sub-routers**

| Sub-Router | Prefix | Key Commands |
|-----------|--------|--------------|
| `futures` | `/futures` | `historical`, `curve`, `search`, `info` |
| `options` | `/options` | `chains`, `unusual`, `snapshots` |

### 2.7 Fixed Income (`/fixedincome`)

**Package:** `openbb_fixedincome` | **4 sub-routers, 2 top-level commands**

| Sub-Router | Prefix | Key Commands |
|-----------|--------|--------------|
| `rate` | `/rate` | `ameribor`, `sofr`, `sonia`, `estr`, `ecb`, `effr`, `iorb`, `dpcredit`, `overnight_bank_funding`, `federal_funds` |
| `spreads` | `/spreads` | `treasury_bill`, `tips_vs_treasury`, `high_quality_market`, `tbffr`, `tmc` |
| `government` | `/government` | `treasury_rates`, `yield_curve`, `treasury_auctions`, `treasury_prices`, `tips_yields` |
| `corporate` | `/corporate` | `bond_prices`, `bond_reference`, `bond_trades`, `commercial_paper`, `spot_rates`, `hqm` |

**Top-level:** `bond_indices`, `mortgage_indices`

### 2.8 Index (`/index`)

**Package:** `openbb_index` | **1 sub-router, 5 top-level commands**

| Sub-Router | Prefix | Key Commands |
|-----------|--------|--------------|
| `price` | `/price` | `historical` |

**Top-level:** `search`, `info`, `constituents`, `sectors`, `snapshots`, `available`

### 2.9 Commodity (`/commodity`)

**Package:** `openbb_commodity` | **0 sub-routers, 3 top-level commands**

**Top-level:** `lbma_fixing`, `spot_prices`, `petroleum_status_report`

### 2.10 News (`/news`)

**Package:** `openbb_news` | **0 sub-routers, 2 top-level commands**

**Top-level:** `company` → `CompanyNews`, `world` → `WorldNews`

### 2.11 Regulators (`/regulators`)

**Package:** `openbb_regulators` | **2 sub-routers**

| Sub-Router | Prefix | Key Commands |
|-----------|--------|--------------|
| `sec` | `/sec` | `cik_map`, `symbol_map`, `search`, `filings`, `rss_filings`, `ftd`, `forms_13f` |
| `cftc` | `/cftc` | `cot`, `cot_search` |

### 2.12 Technical (`/technical`)

**Package:** `openbb_technical` | **0 sub-routers, 27+ commands**

Operates on OBBject data (post-fetch). Key indicators:
`ema`, `sma`, `wma`, `hma`, `zlma`, `dema`, `tema`, `rsi`, `macd`,
`bbands`, `stoch`, `aroon`, `adx`, `obv`, `atr`, `kc`, `donchian`,
`ichimoku`, `cones`, `fib`, `ad`, `adosc`, `vwap`

**Important:** Technical does NOT use the standard Fetcher pattern.
Commands operate on existing data, not API calls.

### 2.13 Quantitative (`/quantitative`)

**Package:** `openbb_quantitative` | **0 sub-routers, 10+ commands**

Statistical analysis on OBBject data: `normality`, `summary`, `capm`,
`omega_ratio`, `sortino_ratio`, `kurtosis`, `unitroot_test`,
`performance` (rolling), `rolling`

### 2.14 Econometrics (`/econometrics`)

**Package:** `openbb_econometrics` | **0 sub-routers, 10+ commands**

Econometric analysis: `ols_regression`, `ols_summary`, `autocorrelation`,
`residuals`, `cointegration_engle_granger`, `cointegration_johansen`,
`stationarity`, `granger_causality`, `panel_random_effects`,
`panel_between`, `panel_pooled`, `panel_fixed`, `panel_first_difference`,
`panel_fmac`

### 2.15 Fama-French (`/famafrench`)

**Package:** `openbb_famafrench` | **Top-level:** `available`, `data`

### 2.16 US Congress (`/uscongress`)

**Package:** `openbb_uscongress` | **Top-level:** `trades`

### 2.17 DevTools (`/devtools`)

Internal extension for development and testing.

### 2.18 Platform API (`/platform_api`)

Internal extension for REST API setup.

### 2.19 MCP Server (`/mcp_server`)

Model Context Protocol server for AI agent integration.

---

## 3. Router Pattern

Every extension follows this pattern:

```python
# equity_router.py
from openbb_core.app.router import Router
from openbb_core.app.query import Query
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.provider_interface import (
    ExtraParams, ProviderChoices, StandardParams,
)

router = Router(prefix="", description="Equity market data.")

# Include sub-routers
router.include_router(price_router, prefix="/price")
router.include_router(fundamental_router, prefix="/fundamental")

# Top-level command
@router.command(model="EquitySearch")
async def search(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Search for stock symbol, CIK, LEI, or company name."""
    return await OBBject.from_query(Query(**locals()))
```

**Key points:**
- `model="EquitySearch"` binds the route to a standard model name.
- The `SignatureInspector` replaces `ProviderChoices`, `StandardParams`,
  `ExtraParams` with the actual dynamically-generated dataclasses at startup.
- `Query(**locals())` dispatches to the correct provider's Fetcher.
- Every command returns `OBBject`.

---

## 4. Charting Extension (OBBject)

The only OBBject extension currently: `openbb-charting`.

**Entry point:**
```toml
[tool.poetry.plugins."openbb_obbject_extension"]
charting = "openbb_charting:Charting"
```

**What it does:**
- Registers as a `CachedAccessor` on `OBBject`
- Accessible as `obbject.charting.show()`
- Each core extension can define a `*_views.py` with charting support:
  ```toml
  [tool.poetry.plugins."openbb_charting_extension"]
  equity = "openbb_equity.equity_views:EquityViews"
  ```
- The charting extension renders Plotly charts

**Usage:**
```python
result = obb.equity.price.historical("AAPL", chart=True)
result.show()  # Opens interactive chart
```

---

## 5. SDK Auto-Generation

Each router command automatically creates a corresponding Python SDK method:

| Route | SDK Method |
|-------|-----------|
| `/equity/search` | `obb.equity.search(...)` |
| `/equity/price/historical` | `obb.equity.price.historical(...)` |
| `/economy/fred_series` | `obb.economy.fred_series(...)` |
| `/etf/holdings` | `obb.etf.holdings(...)` |
| `/crypto/price/historical` | `obb.crypto.price.historical(...)` |

The `PackageBuilder` generates these with:
- Full type annotations
- Provider-specific parameter documentation
- Default values
- Proper return type `OBBject[T]`

---

## 6. Extension Development

To create a new core extension:

### Step 1: Package Structure
```
openbb_platform/extensions/my_ext/
├── pyproject.toml
├── openbb_my_ext/
│   ├── __init__.py
│   ├── my_ext_router.py
│   └── submodule/
│       └── sub_router.py
└── tests/
```

### Step 2: Define Router
```python
# my_ext_router.py
from openbb_core.app.router import Router

router = Router(prefix="", description="My extension.")

@router.command(model="MyModel")
async def my_command(cc, provider_choices, standard_params, extra_params):
    """My command description."""
    return await OBBject.from_query(Query(**locals()))
```

### Step 3: Register
```toml
[tool.poetry.plugins."openbb_core_extension"]
my_ext = "openbb_my_ext.my_ext_router:router"
```

### Step 4: Install
```bash
pip install -e openbb_platform/extensions/my_ext
```

The `PackageBuilder` will auto-generate `obb.my_ext.my_command(...)` in the SDK.

---

*Last updated: 2026-02-21*
