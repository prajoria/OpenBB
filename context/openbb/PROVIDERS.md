# OpenBB Providers — Deep Dive

> **Purpose:** Complete reference for the OpenBB provider system — how providers
> register, the credential model, all 34 providers, and the FMP/FMP-Cached
> relationship.
>
> **See also:** `context/openbb/CORE.md` for Fetcher and QueryExecutor details.

---

## 1. Provider Class

Every data provider is an instance of `Provider` (from
`openbb_core/provider/abstract/provider.py`):

```python
class Provider:
    def __init__(
        self,
        name: str,                          # "fmp", "yfinance", etc.
        description: str,                   # Human-readable description
        website: str | None = None,         # Provider website URL
        credentials: list[str] | None,      # e.g. ["api_key"]
        fetcher_dict: dict[str, type[Fetcher]],  # model → Fetcher class
        repr_name: str | None = None,       # Display name
        deprecated_credentials: dict | None,
        instructions: str | None = None,    # Setup instructions
    )
```

**Credential auto-prefixing:** When you pass `credentials=["api_key"]` for
provider `name="fmp"`, the stored credential name becomes `fmp_api_key`.
This ensures no collisions between providers.

---

## 2. Registration Pattern

Providers register via Python entry points in `pyproject.toml`:

```toml
[tool.poetry.plugins."openbb_provider_extension"]
fmp = "openbb_fmp:fmp_provider"
```

The entry point value must resolve to a `Provider` instance.  At startup:

```
ExtensionLoader (singleton)
  └→ reads entry_points(group="openbb_provider_extension")
       └→ loads each → Provider instance
            └→ RegistryLoader.from_extensions()
                 └→ Registry.include_provider(provider)
                      └→ stored as registry.providers["fmp"]
```

---

## 3. All 34 Providers

| # | Provider | Package | Credentials | Fetchers | Category |
|---|----------|---------|-------------|----------|----------|
| 1 | `alpha_vantage` | `openbb_alpha_vantage` | `api_key` | ~8 | Market data |
| 2 | `benzinga` | `openbb_benzinga` | `api_key` | ~6 | News & calendar |
| 3 | `biztoc` | `openbb_biztoc` | `api_key` | ~2 | News |
| 4 | `bls` | `openbb_bls` | `api_key` | ~3 | Labor statistics |
| 5 | `cboe` | `openbb_cboe` | None | ~8 | Options & indices |
| 6 | `cftc` | `openbb_cftc` | None | ~2 | Futures (COT) |
| 7 | `congress_gov` | `openbb_congress_gov` | None | ~1 | US Congress |
| 8 | `deribit` | `openbb_deribit` | None | ~3 | Crypto derivatives |
| 9 | `ecb` | `openbb_ecb` | None | ~3 | European Central Bank |
| 10 | `econdb` | `openbb_econdb` | `token` | ~5 | Economic data |
| 11 | `eia` | `openbb_eia` | `api_key` | ~3 | Energy data |
| 12 | `famafrench` | `openbb_famafrench` | None | ~1 | Academic factors |
| 13 | `federal_reserve` | `openbb_federal_reserve` | None | ~10 | Fed data |
| 14 | `finra` | `openbb_finra` | None | ~3 | Short interest |
| 15 | `finviz` | `openbb_finviz` | None | ~3 | Screening |
| 16 | **`fmp`** | `openbb_fmp` | `api_key` | **65** | **Primary market data** |
| 17 | **`fmp_cached`** | `openbb_fmp_cached` | `api_key` | **65+** | **FMP + DB caching** |
| 18 | `fred` | `openbb_fred` | `api_key` | ~6 | Fed Reserve (FRED) |
| 19 | `government_us` | `openbb_government_us` | None | ~2 | US Gov data |
| 20 | `imf` | `openbb_imf` | None | ~3 | Int'l Monetary Fund |
| 21 | `intrinio` | `openbb_intrinio` | `api_key` | ~12 | Market data |
| 22 | `multpl` | `openbb_multpl` | None | ~1 | SP500 multiples |
| 23 | `nasdaq` | `openbb_nasdaq` | `api_key` | ~5 | NASDAQ data |
| 24 | `oecd` | `openbb_oecd` | None | ~10 | OECD economics |
| 25 | `polygon` | `openbb_polygon` | `api_key` | 13 | Market data |
| 26 | `sec` | `openbb_sec` | None | ~8 | SEC filings |
| 27 | `seeking_alpha` | `openbb_seeking_alpha` | None | ~2 | News/analysis |
| 28 | `stockgrid` | `openbb_stockgrid` | None | ~2 | Short data |
| 29 | `tiingo` | `openbb_tiingo` | `token` | ~4 | Market data |
| 30 | `tmx` | `openbb_tmx` | None | ~8 | Toronto Exchange |
| 31 | `tradier` | `openbb_tradier` | `api_key` | ~4 | Options |
| 32 | `tradingeconomics` | `openbb_tradingeconomics` | `api_key` | ~3 | Global econ |
| 33 | `wsj` | `openbb_wsj` | None | ~3 | Wall Street Journal |
| 34 | `yfinance` | `openbb_yfinance` | None | **28** | **Free market data** |

**No-credential providers** (free/scraping): cboe, cftc, congress_gov, deribit,
ecb, famafrench, federal_reserve, finra, finviz, government_us, imf, multpl,
oecd, sec, seeking_alpha, stockgrid, tmx, wsj.

---

## 4. FMP Provider — Detailed

**Location:** `openbb_platform/providers/fmp/openbb_fmp/`

**Credentials:** `fmp_api_key` (from `credentials=["api_key"]`)

### 4.1 All 65+ Fetcher Mappings

| Model Name | Fetcher Class | Category |
|-----------|---------------|----------|
| `AnalystEstimates` | `FMPAnalystEstimatesFetcher` | Estimates |
| `AvailableIndices` | `FMPAvailableIndicesFetcher` | Index |
| `BalanceSheet` | `FMPBalanceSheetFetcher` | Fundamental |
| `BalanceSheetGrowth` | `FMPBalanceSheetGrowthFetcher` | Fundamental |
| `CalendarDividend` | `FMPCalendarDividendFetcher` | Calendar |
| `CalendarEarnings` | `FMPCalendarEarningsFetcher` | Calendar |
| `CalendarEvents` | `FMPCalendarEventsFetcher` | Calendar |
| `CalendarIpo` | `FMPCalendarIpoFetcher` | Calendar |
| `CalendarSplits` | `FMPCalendarSplitsFetcher` | Calendar |
| `CashFlowStatement` | `FMPCashFlowStatementFetcher` | Fundamental |
| `CashFlowStatementGrowth` | `FMPCashFlowStatementGrowthFetcher` | Fundamental |
| `CompanyFilings` | `FMPCompanyFilingsFetcher` | Filings |
| `CompanyNews` | `FMPCompanyNewsFetcher` | News |
| `CryptoHistorical` | `FMPCryptoHistoricalFetcher` | Crypto |
| `CryptoSearch` | `FMPCryptoSearchFetcher` | Crypto |
| `CurrencyHistorical` | `FMPCurrencyHistoricalFetcher` | Currency |
| `CurrencyPairs` | `FMPCurrencyPairsFetcher` | Currency |
| `CurrencySnapshots` | `FMPCurrencySnapshotsFetcher` | Currency |
| `DiscoveryFilings` | `FMPDiscoveryFilingsFetcher` | Discovery |
| `EarningsCallTranscript` | `FMPEarningsCallTranscriptFetcher` | Fundamental |
| `EconomicCalendar` | `FMPEconomicCalendarFetcher` | Economy |
| `EquityActive` | `FMPEquityActiveFetcher` | Discovery |
| `EquityHistorical` | `FMPEquityHistoricalFetcher` | Price |
| `EquityOwnership` | `FMPEquityOwnershipFetcher` | Ownership |
| `EquityPeers` | `FMPEquityPeersFetcher` | Equity |
| `EquityInfo` | `FMPEquityProfileFetcher` | Equity |
| `EquityGainers` | `FMPGainersFetcher` | Discovery |
| `EquityLosers` | `FMPLosersFetcher` | Discovery |
| `EquityQuote` | `FMPEquityQuoteFetcher` | Price |
| `EquityScreener` | `FMPEquityScreenerFetcher` | Discovery |
| `EsgScore` | `FMPEsgScoreFetcher` | ESG |
| `EtfCountries` | `FMPEtfCountriesFetcher` | ETF |
| `EtfEquityExposure` | `FMPEtfEquityExposureFetcher` | ETF |
| `EtfHoldings` | `FMPEtfHoldingsFetcher` | ETF |
| `EtfHistorical` | `FMPEquityHistoricalFetcher` | ETF (reuses equity) |
| `EtfInfo` | `FMPEtfInfoFetcher` | ETF |
| `EtfPricePerformance` | `FMPPricePerformanceFetcher` | ETF |
| `EtfSearch` | `FMPEtfSearchFetcher` | ETF |
| `EtfSectors` | `FMPEtfSectorsFetcher` | ETF |
| `ExecutiveCompensation` | `FMPExecutiveCompensationFetcher` | Fundamental |
| `FinancialRatios` | `FMPFinancialRatiosFetcher` | Fundamental |
| `ForwardEbitdaEstimates` | `FMPForwardEbitdaEstimatesFetcher` | Estimates |
| `ForwardEpsEstimates` | `FMPForwardEpsEstimatesFetcher` | Estimates |
| `GovernmentTrades` | `FMPGovernmentTradesFetcher` | Government |
| `HistoricalDividends` | `FMPHistoricalDividendsFetcher` | Dividends |
| `HistoricalEmployees` | `FMPHistoricalEmployeesFetcher` | Fundamental |
| `HistoricalEps` | `FMPHistoricalEpsFetcher` | Fundamental |
| `HistoricalMarketCap` | `FmpHistoricalMarketCapFetcher` | Price |
| `HistoricalSplits` | `FMPHistoricalSplitsFetcher` | Corporate Actions |
| `IncomeStatement` | `FMPIncomeStatementFetcher` | Fundamental |
| `IncomeStatementGrowth` | `FMPIncomeStatementGrowthFetcher` | Fundamental |
| `IndexConstituents` | `FMPIndexConstituentsFetcher` | Index |
| `IndexHistorical` | `FMPIndexHistoricalFetcher` | Index |
| `InsiderTrading` | `FMPInsiderTradingFetcher` | Ownership |
| `InstitutionalOwnership` | `FMPInstitutionalOwnershipFetcher` | Ownership |
| `KeyExecutives` | `FMPKeyExecutivesFetcher` | Fundamental |
| `KeyMetrics` | `FMPKeyMetricsFetcher` | Fundamental |
| `MarketSnapshots` | `FMPMarketSnapshotsFetcher` | Price |
| `NportDisclosure` | `FMPNportDisclosureFetcher` | ETF |
| `PricePerformance` | `FMPPricePerformanceFetcher` | Price |
| `PriceTarget` | `FMPPriceTargetFetcher` | Estimates |
| `PriceTargetConsensus` | `FMPPriceTargetConsensusFetcher` | Estimates |
| `RevenueBusinessLine` | `FMPRevenueBusinessLineFetcher` | Fundamental |
| `RevenueGeographic` | `FMPRevenueGeographicFetcher` | Fundamental |
| `RiskPremium` | `FMPRiskPremiumFetcher` | Economy |
| `ShareStatistics` | `FMPShareStatisticsFetcher` | Equity |
| `TreasuryRates` | `FMPTreasuryRatesFetcher` | Fixed Income |
| `WorldNews` | `FMPWorldNewsFetcher` | News |
| `YieldCurve` | `FMPYieldCurveFetcher` | Fixed Income |

### 4.2 FMP Model Directory Structure

```
openbb_fmp/models/
├── analyst_estimates.py
├── balance_sheet.py
├── balance_sheet_growth.py
├── calendar_dividend.py
├── ...
├── equity_historical.py     # FMPEquityHistoricalFetcher
├── ...
└── yield_curve.py
```

Each model file follows the pattern:
```python
class FMPEquityHistoricalQueryParams(EquityHistoricalQueryParams):
    """FMP-specific query params — adds interval, adjustment, extended_hours, etc."""
    __alias_dict__ = {"start_date": "from", "end_date": "to"}
    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}

class FMPEquityHistoricalData(EquityHistoricalData):
    """FMP-specific data — adds adj_close, unadjusted_volume, change, etc."""
    adj_close: float | None = None
    change: float | None = None
    change_percent: float | None = None

class FMPEquityHistoricalFetcher(Fetcher[FMPEquityHistoricalQueryParams, list[FMPEquityHistoricalData]]):
    @staticmethod
    def transform_query(params): ...
    @staticmethod
    async def aextract_data(query, credentials): ...
    @staticmethod
    def transform_data(query, data): ...
```

---

## 5. FMP Cached Provider — Detailed

**Location:** `openbb_platform/providers/fmp_cached/openbb_fmp_cached/`

**Purpose:** Extends FMP with MySQL database caching.  All FMP endpoints are
available, but data fetched from the API is stored in MySQL and served from
cache on subsequent requests.

### 5.1 Two-Tier Architecture

**Tier 1: Dedicated Cached Fetchers** (custom DB persistence):

| Model | Cached Fetcher | Has Custom DB Schema |
|-------|---------------|---------------------|
| `AnalystEstimates` | `FMPCachedAnalystEstimatesFetcher` | Yes |
| `EquityHistorical` | `FMPCachedEquityHistoricalFetcher` | Yes |
| `EtfHistorical` | `FMPCachedEquityHistoricalFetcher` | Yes (same class) |
| `IndexConstituents` | `FMPCachedIndexConstituentsFetcher` | Yes |

These have hand-written DB table schemas and caching logic.

**Tier 2: Auto-Wrapped Fetchers** (runtime wrapping):

All remaining ~60 FMP fetchers are wrapped at module load time:

```python
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# For each FMP fetcher not in Tier 1:
CachedFooFetcher = create_cached_fetcher_class(FMPFooFetcher, "Foo")
```

The `create_cached_fetcher_class()` factory:
1. Creates a new class inheriting from the original FMP fetcher
2. Overrides `extract_data` to check MySQL cache first
3. Falls back to original API call if cache miss
4. Stores result in MySQL for future requests

### 5.2 Build Process

```python
def create_all_cached_fetchers() -> dict[str, type[Fetcher]]:
    """Build the complete fetcher_dict for fmp_cached provider."""
    fetcher_dict = {}

    # Tier 1: Dedicated cached fetchers
    fetcher_dict["AnalystEstimates"] = FMPCachedAnalystEstimatesFetcher
    fetcher_dict["EquityHistorical"] = FMPCachedEquityHistoricalFetcher
    fetcher_dict["EtfHistorical"] = FMPCachedEquityHistoricalFetcher
    fetcher_dict["IndexConstituents"] = FMPCachedIndexConstituentsFetcher

    # Tier 2: Auto-wrap all remaining FMP fetchers
    for model_name, fetcher_cls in fmp_fetcher_dict.items():
        if model_name not in fetcher_dict:
            fetcher_dict[model_name] = create_cached_fetcher_class(fetcher_cls, model_name)

    return fetcher_dict
```

### 5.3 Database Details

- **Database:** `openbb_fmp_cache` (production), `openbb_fmp_cache_test` (portfolio)
- **Connection:** Via `DatabaseConfig` → `get_connection()` (reads credentials
  from `~/.openbb_platform/user_settings.json`)
- **Auto-create:** `init_database()` creates all 67+ tables if they don't exist.
  Disable with `FMP_CACHE_AUTO_CREATE_DB=false` for performance.

---

## 6. Creating a New Provider

### Step 1: Package Structure

```
openbb_platform/providers/my_provider/
├── pyproject.toml
├── openbb_my_provider/
│   ├── __init__.py        # Provider instance
│   ├── models/
│   │   ├── equity_historical.py  # Fetcher implementation
│   │   └── ...
│   └── utils/
│       └── helpers.py     # API client, auth, etc.
└── tests/
```

### Step 2: Define Fetcher

```python
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_historical import (
    EquityHistoricalQueryParams, EquityHistoricalData,
)

class MyProviderEquityHistoricalQueryParams(EquityHistoricalQueryParams):
    """My provider specific query params."""
    # Add provider-specific fields here

class MyProviderEquityHistoricalData(EquityHistoricalData):
    """My provider specific data."""
    # Add provider-specific fields here

class MyProviderEquityHistoricalFetcher(
    Fetcher[MyProviderEquityHistoricalQueryParams, list[MyProviderEquityHistoricalData]]
):
    @staticmethod
    def transform_query(params: dict) -> MyProviderEquityHistoricalQueryParams:
        return MyProviderEquityHistoricalQueryParams(**params)

    @staticmethod
    async def aextract_data(query, credentials, **kwargs):
        # Make API call using credentials["my_provider_api_key"]
        ...

    @staticmethod
    def transform_data(query, data, **kwargs) -> list[MyProviderEquityHistoricalData]:
        return [MyProviderEquityHistoricalData.model_validate(d) for d in data]
```

### Step 3: Register Provider

```python
# openbb_my_provider/__init__.py
from openbb_core.provider.abstract.provider import Provider
from openbb_my_provider.models.equity_historical import MyProviderEquityHistoricalFetcher

my_provider = Provider(
    name="my_provider",
    description="My custom data provider",
    website="https://my-provider.com",
    credentials=["api_key"],  # becomes "my_provider_api_key"
    fetcher_dict={
        "EquityHistorical": MyProviderEquityHistoricalFetcher,
    },
)
```

### Step 4: Entry Point

```toml
# pyproject.toml
[tool.poetry.plugins."openbb_provider_extension"]
my_provider = "openbb_my_provider:my_provider"
```

### Step 5: Install & Verify

```bash
pip install -e openbb_platform/providers/my_provider
python -c "from openbb import obb; print(obb.equity.price.historical('AAPL', provider='my_provider'))"
```

---

## 7. Credential Management

Credentials are stored in `~/.openbb_platform/user_settings.json`:

```json
{
  "credentials": {
    "fmp_api_key": "your_key_here",
    "polygon_api_key": "your_key_here",
    "fred_api_key": "your_key_here"
  }
}
```

**Runtime flow:**
1. `UserService.read_from_file()` loads settings
2. `CommandRunner` passes credentials to `ExecutionContext`
3. `QueryExecutor.filter_credentials()` extracts provider-specific credentials
4. Credentials are passed as `dict[str, str]` to `Fetcher.extract_data()`

**Important:** `SecretStr` wrapper is used in Python — `.get_secret_value()`
extracts the actual string.  The `filter_credentials()` method handles this.

---

## 8. Provider Comparison

| Feature | FMP | yFinance | Polygon | FRED |
|---------|-----|----------|---------|------|
| Fetchers | 65 | 28 | 13 | 6 |
| API Key | Yes | No | Yes | Yes |
| Equity OHLCV | Yes | Yes | Yes | No |
| Fundamentals | Yes (full) | Yes (some) | No | No |
| Options | No | Yes | Yes | No |
| Economic | Basic | No | No | Yes (full) |
| Free tier | Limited | Unlimited | Limited | Generous |
| Rate limits | Varies | Aggressive | 5/min (free) | 120/min |

---

*Last updated: 2026-02-21*
