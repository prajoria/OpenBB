# OpenBB Open Data Platform (ODP) - Comprehensive Project Documentation

> **Repository**: [OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB)
> **Version**: 4.6.0 (PyPI) | **License**: AGPLv3
> **Stars**: 60.4k+ | **Contributors**: 256+ | **Language**: Python (100%)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Overview](#2-architecture-overview)
3. [Repository Structure](#3-repository-structure)
4. [Core Platform (`openbb_platform/core`)](#4-core-platform)
5. [Router Extensions](#5-router-extensions)
6. [Data Providers](#6-data-providers)
7. [OBBject Extensions](#7-obbject-extensions)
8. [Standardization Framework](#8-standardization-framework)
9. [REST API](#9-rest-api)
10. [MCP Server (AI Agent Integration)](#10-mcp-server)
11. [Command-Line Interface (CLI)](#11-command-line-interface)
12. [Desktop Application](#12-desktop-application)
13. [OpenBB Workspace (Enterprise UI)](#13-openbb-workspace)
14. [Charting & Visualization](#14-charting--visualization)
15. [Cookiecutter Template](#15-cookiecutter-template)
16. [Build & Deployment](#16-build--deployment)
17. [Testing Framework](#17-testing-framework)
18. [Configuration & Credentials](#18-configuration--credentials)
19. [Examples & Notebooks](#19-examples--notebooks)
20. [Key Design Patterns](#20-key-design-patterns)
21. [Data Domains & Capabilities Matrix](#21-data-domains--capabilities-matrix)

---

## 1. Project Overview

The **Open Data Platform by OpenBB (ODP)** is an open-source toolset that helps data engineers integrate proprietary, licensed, and public financial data sources into downstream applications. It operates as a **"connect once, consume everywhere"** infrastructure layer.

### Core Value Proposition

- **Unified Data Access**: Single interface to 35+ financial data providers
- **Multi-Surface Delivery**: Python SDK, REST API, CLI, MCP Server, Excel, Desktop App
- **Standardized Schemas**: Consistent data models across all providers via the Standardization Framework
- **Extensible Architecture**: Plugin-based system for adding new data sources, commands, and visualizations
- **AI-Ready**: MCP server for LLM agent integration; OpenBB Workspace for AI-powered analytics

### Consumption Surfaces

| Surface | Use Case | Technology |
|---------|----------|------------|
| Python SDK | Quants & data engineers | `from openbb import obb` |
| REST API | Cross-language application development | FastAPI + Uvicorn |
| CLI | Interactive terminal sessions | `openbb` command |
| MCP Server | AI agent tool discovery & execution | MCP Protocol |
| Desktop App | GUI for environment & API management | Tauri + React |
| OpenBB Workspace | Enterprise analytics dashboards | Web application at pro.openbb.co |

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Consumption Layer                            │
│  ┌──────────┐ ┌──────────┐ ┌──────┐ ┌──────────┐ ┌───────────────┐ │
│  │ Python   │ │ REST API │ │ CLI  │ │ MCP      │ │ Desktop App   │ │
│  │ SDK      │ │ (FastAPI)│ │      │ │ Server   │ │ (Tauri/React) │ │
│  └────┬─────┘ └────┬─────┘ └──┬───┘ └────┬─────┘ └───────┬───────┘ │
│       │            │          │           │               │         │
│  ┌────▼────────────▼──────────▼───────────▼───────────────▼───────┐ │
│  │                    OpenBB Core (Router)                        │ │
│  │  ┌────────────────────────────────────────────────────────────┐│ │
│  │  │              Router Extensions                             ││ │
│  │  │  equity │ crypto │ economy │ etf │ fixedincome │ ...      ││ │
│  │  └────────────────────────┬───────────────────────────────────┘│ │
│  │                           │                                    │ │
│  │  ┌────────────────────────▼───────────────────────────────────┐│ │
│  │  │           Standardization Framework                        ││ │
│  │  │  QueryParams │ Data Models │ Fetcher (TET Pattern)        ││ │
│  │  └────────────────────────┬───────────────────────────────────┘│ │
│  │                           │                                    │ │
│  │  ┌────────────────────────▼───────────────────────────────────┐│ │
│  │  │              Provider Registry                             ││ │
│  │  │  fmp │ yfinance │ polygon │ fred │ sec │ intrinio │ ...   ││ │
│  │  └────────────────────────────────────────────────────────────┘│ │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │              OBBject Extensions                                 ││
│  │  charting (Plotly) │ technical analysis │ quantitative │ ...    ││
│  └─────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

### Key Architectural Principles

1. **Provider-Core Separation**: Provider package has zero dependencies on other OpenBB packages
2. **Core as Infrastructure**: Depends on Provider; handles routing, auth, command execution
3. **Extensions as Plugins**: Each extension is an independent, installable Python package
4. **Dynamic Discovery**: On `import openbb`, the system detects installed extensions and rebuilds the package interface
5. **Pydantic-First**: All data models use Pydantic for validation, serialization, and schema generation

---

## 3. Repository Structure

```
OpenBB/
├── openbb_platform/                 # === MAIN PLATFORM CODE ===
│   ├── core/                        # Core infrastructure
│   │   ├── openbb_core/
│   │   │   ├── api/                 # REST API (FastAPI)
│   │   │   │   ├── rest_api.py      # FastAPI app entry point
│   │   │   │   ├── app_loader.py    # Extension loading for API
│   │   │   │   ├── router/          # API route handlers
│   │   │   │   └── auth/            # Authentication system
│   │   │   ├── app/                 # Application logic
│   │   │   │   ├── router.py        # Command router system
│   │   │   │   ├── command_runner.py # Command execution engine
│   │   │   │   ├── extension_loader.py # Plugin discovery
│   │   │   │   ├── provider_interface.py # Provider abstraction
│   │   │   │   ├── query.py         # Query execution
│   │   │   │   ├── model/           # App-level models (OBBject, etc.)
│   │   │   │   ├── service/         # Business logic services
│   │   │   │   ├── logs/            # Logging infrastructure
│   │   │   │   └── static/          # Static assets for API docs
│   │   │   ├── provider/            # Provider framework
│   │   │   │   ├── abstract/        # Abstract base classes
│   │   │   │   │   ├── fetcher.py   # Fetcher base (TET pattern)
│   │   │   │   │   ├── data.py      # Data model base class
│   │   │   │   │   ├── query_params.py # Query parameter base
│   │   │   │   │   ├── provider.py  # Provider registration
│   │   │   │   │   └── annotated_result.py
│   │   │   │   ├── standard_models/  # 160+ standardized data models
│   │   │   │   ├── registry.py      # Provider registry
│   │   │   │   ├── registry_map.py  # Provider-model mapping
│   │   │   │   ├── query_executor.py # Query orchestration
│   │   │   │   └── utils/           # Provider utilities
│   │   │   ├── build.py             # Platform build script
│   │   │   └── env.py               # Environment configuration
│   │   ├── pyproject.toml
│   │   └── tests/
│   │
│   ├── extensions/                   # === ROUTER EXTENSIONS ===
│   │   ├── equity/                  # Equity/stock market data
│   │   ├── crypto/                  # Cryptocurrency data
│   │   ├── currency/                # Foreign exchange data
│   │   ├── economy/                 # Economic indicators
│   │   ├── etf/                     # ETF data
│   │   ├── fixedincome/             # Fixed income/bonds
│   │   ├── derivatives/             # Options & derivatives
│   │   ├── index/                   # Market indices
│   │   ├── news/                    # Financial news
│   │   ├── regulators/              # Regulatory data (SEC, CFTC)
│   │   ├── commodity/               # Commodity data
│   │   ├── technical/               # Technical analysis indicators
│   │   ├── quantitative/            # Quantitative analysis
│   │   ├── econometrics/            # Econometric analysis
│   │   ├── famafrench/              # Fama-French factor models
│   │   ├── uscongress/              # US Congressional data
│   │   ├── mcp_server/              # MCP Server for AI agents
│   │   ├── platform_api/            # API configuration extension
│   │   └── devtools/                # Developer tools
│   │
│   ├── providers/                    # === DATA PROVIDERS ===
│   │   ├── fmp/                     # Financial Modeling Prep
│   │   ├── yfinance/                # Yahoo Finance
│   │   ├── polygon/                 # Polygon.io
│   │   ├── fred/                    # Federal Reserve (FRED)
│   │   ├── sec/                     # SEC EDGAR
│   │   ├── intrinio/                # Intrinio
│   │   ├── benzinga/                # Benzinga
│   │   ├── tiingo/                  # Tiingo
│   │   ├── tradingeconomics/        # Trading Economics
│   │   ├── alpha_vantage/           # Alpha Vantage
│   │   ├── cboe/                    # Cboe
│   │   ├── ecb/                     # European Central Bank
│   │   ├── oecd/                    # OECD
│   │   ├── imf/                     # International Monetary Fund
│   │   ├── bls/                     # Bureau of Labor Statistics
│   │   ├── econdb/                  # EconDB
│   │   ├── nasdaq/                  # Nasdaq Data Link
│   │   ├── finra/                   # FINRA
│   │   ├── finviz/                  # Finviz
│   │   ├── tmx/                     # TMX (Toronto)
│   │   ├── tradier/                 # Tradier
│   │   ├── deribit/                 # Deribit (crypto derivatives)
│   │   ├── biztoc/                  # Biztoc News
│   │   ├── cftc/                    # CFTC (Commitments of Traders)
│   │   ├── congress_gov/            # US Congress API
│   │   ├── federal_reserve/         # Federal Reserve
│   │   ├── famafrench/              # Ken French Data Library
│   │   ├── government_us/           # US Government data
│   │   ├── seeking_alpha/           # Seeking Alpha
│   │   ├── stockgrid/               # Stockgrid
│   │   ├── wsj/                     # Wall Street Journal
│   │   ├── multpl/                  # Multpl (S&P 500 data)
│   │   ├── eia/                     # Energy Information Admin.
│   │   ├── fmp_cached/              # FMP with caching layer
│   │   └── __init__.py
│   │
│   ├── obbject_extensions/           # === OBBJECT EXTENSIONS ===
│   │   └── charting/                # Plotly charting extension
│   │
│   ├── conftest.py                  # Shared test configuration
│   ├── dev_install.py               # Development installation script
│   ├── pyproject.toml               # Root platform config
│   ├── CONTRIBUTING.md              # Developer contribution guide
│   └── tests/                       # Platform-wide tests
│
├── cli/                              # === COMMAND LINE INTERFACE ===
│   ├── openbb_cli/
│   │   ├── cli.py                   # CLI entry point
│   │   ├── session.py               # Session management
│   │   ├── controllers/             # Menu controllers
│   │   ├── models/                  # CLI data models
│   │   ├── config/                  # CLI configuration
│   │   ├── argparse_translator/     # Argparse adapter
│   │   ├── utils/                   # CLI utilities
│   │   └── assets/                  # CLI static assets
│   ├── integration/                 # CLI integration tests
│   └── tests/                       # CLI unit tests
│
├── desktop/                          # === DESKTOP APPLICATION ===
│   ├── src/                         # React TypeScript frontend
│   │   ├── components/              # UI components
│   │   ├── routes/                  # Route definitions
│   │   ├── contexts/                # React contexts
│   │   └── utils/                   # Frontend utilities
│   ├── src-tauri/                   # Rust Tauri backend
│   │   ├── src/                     # Rust source code
│   │   ├── tauri.conf.json          # Tauri configuration
│   │   └── scripts/                 # Build scripts
│   ├── package.json                 # Node.js dependencies
│   ├── vite.config.ts               # Vite build config
│   └── tailwind.config.js           # Tailwind CSS config
│
├── cookiecutter/                     # === EXTENSION TEMPLATE ===
│   ├── openbb_cookiecutter/         # Template source
│   └── cookiecutter.json            # Template configuration
│
├── build/                            # === BUILD & DEPLOY ===
│   ├── docker/
│   │   ├── platform.dockerfile      # Platform Docker image
│   │   └── platformAPI.Dockerfile   # API server Docker image
│   └── pypi/                        # PyPI publishing config
│
├── examples/                         # === JUPYTER NOTEBOOKS ===
│   ├── loadHistoricalPriceData.ipynb
│   ├── financialStatements.ipynb
│   ├── portfolioOptimizationUsingModernPortfolioTheory.ipynb
│   ├── BacktestingMomentumTrading.ipynb
│   ├── copperToGoldRatio.ipynb
│   ├── currencyExchangeRateForecasting.ipynb
│   ├── EthereumTrendAnalysis.ipynb
│   ├── openbbPlatformAsLLMTools.ipynb
│   ├── sectorRotationStrategy.ipynb
│   └── ... (15+ example notebooks)
│
├── frontend-components/              # Shared frontend components
├── FinanceToolkit/                   # Finance toolkit integration
├── examples_usage.py                 # Python usage examples
├── test_openbb.py                    # Quick installation test
├── openbb.sh                         # Helper shell script
├── pyrightconfig.json                # Pyright type-checking config
├── pytest.ini                        # Pytest configuration
└── ruff.toml                         # Ruff linter config
```

---

## 4. Core Platform

**Location**: `openbb_platform/core/openbb_core/`

The core is the foundational infrastructure that all other components depend on.

### 4.1 Application Layer (`app/`)

| Component | File | Purpose |
|-----------|------|---------|
| **Router** | `router.py` | Command routing system; maps functions to API endpoints using FastAPI conventions |
| **Command Runner** | `command_runner.py` | Executes commands with credential injection, logging, and error handling |
| **Extension Loader** | `extension_loader.py` | Discovers and loads installed extensions at runtime via Python entry points |
| **Provider Interface** | `provider_interface.py` | Abstracts provider selection; generates `ProviderChoices`, `StandardParams`, `ExtraParams` |
| **Query** | `query.py` | Orchestrates query execution across the TET pipeline |
| **Version** | `version.py` | Platform version management |
| **OBBject Model** | `model/obbject.py` | The universal return type for all commands |

### 4.2 Provider Framework (`provider/`)

| Component | File | Purpose |
|-----------|------|---------|
| **Fetcher** | `abstract/fetcher.py` | Generic base class implementing the TET pattern (Transform-Extract-Transform) |
| **Data** | `abstract/data.py` | Base Pydantic model for all data outputs |
| **QueryParams** | `abstract/query_params.py` | Base Pydantic model for all query inputs |
| **Provider** | `abstract/provider.py` | Provider registration with name, credentials, and fetcher mappings |
| **Registry** | `registry.py` | Central registry of all available providers |
| **Query Executor** | `query_executor.py` | Manages credential validation and fetcher execution |
| **Standard Models** | `standard_models/` | **160+ standardized data models** for cross-provider consistency |

### 4.3 API Layer (`api/`)

| Component | File | Purpose |
|-----------|------|---------|
| **REST API** | `rest_api.py` | FastAPI application with CORS, auth, and lifespan management |
| **App Loader** | `app_loader.py` | Loads extensions into the API router tree |
| **Auth** | `auth/` | Authentication middleware (optional, toggle via `API_AUTH` env var) |
| **Routers** | `router/commands.py`, `router/coverage.py`, `router/system.py` | API route groupings |

### 4.4 The OBBject

Every command returns an `OBBject` - the universal result container:

```python
result = obb.equity.price.historical("AAPL")

result.results      # List[Data] - the actual data
result.provider     # str - which provider was used
result.to_dataframe()  # pandas DataFrame conversion
result.to_dict()    # dictionary conversion
result.to_df()      # alias for to_dataframe()
result.chart        # Plotly chart (if charting extension installed)
```

---

## 5. Router Extensions

**Location**: `openbb_platform/extensions/`

Each extension defines a **command namespace** (e.g., `obb.equity.*`) and maps commands to standardized data models. Extensions are independently installable Python packages.

### Extension Registry

| Extension | Namespace | Sub-Routers | Key Capabilities |
|-----------|-----------|-------------|------------------|
| **equity** | `obb.equity.*` | `price/`, `fundamental/`, `ownership/`, `estimates/`, `calendar/`, `compare/`, `darkpool/`, `discovery/`, `shorts/` | Historical prices, quotes, financial statements, screener, analyst estimates, insider trading, institutional ownership, dark pool data |
| **crypto** | `obb.crypto.*` | `price/` | Cryptocurrency historical data, search, price charts |
| **currency** | `obb.currency.*` | — | FX rates, currency pair data, snapshots, reference rates |
| **economy** | `obb.economy.*` | `gdp/`, `survey/`, `shipping/` | GDP, CPI, employment, central bank rates, economic calendars, manufacturing surveys, port/shipping data |
| **etf** | `obb.etf.*` | — | ETF holdings, info, performance, sectors, country exposure, search |
| **fixedincome** | `obb.fixedincome.*` | — | Treasury rates, yield curves, corporate bonds, SOFR, SONIA, mortgage rates |
| **derivatives** | `obb.derivatives.*` | — | Options chains, futures curves, options snapshots |
| **index** | `obb.index.*` | — | Index constituents, historical data, snapshots, sector breakdown |
| **news** | `obb.news.*` | — | Company news, world news aggregation from multiple sources |
| **regulators** | `obb.regulators.*` | — | SEC filings, CFTC Commitments of Traders reports |
| **commodity** | `obb.commodity.*` | — | Commodity spot prices, petroleum status, energy outlook |
| **technical** | `obb.technical.*` | — | 50+ technical indicators (EMA, SMA, RSI, MACD, Bollinger, etc.) |
| **quantitative** | `obb.quantitative.*` | — | Statistical analysis, normality tests, Omega ratio, Sortino ratio |
| **econometrics** | `obb.econometrics.*` | — | Regression, cointegration, unit root tests, Granger causality |
| **famafrench** | `obb.famafrench.*` | — | Fama-French factor models and data |
| **uscongress** | `obb.uscongress.*` | — | Congressional trading data, bills, member info |
| **mcp_server** | — | — | MCP protocol server for AI agent tool discovery |
| **platform_api** | — | — | API configuration and system endpoints |
| **devtools** | — | — | Development utilities |

---

## 6. Data Providers

**Location**: `openbb_platform/providers/`

Each provider is a self-contained Python package that implements `Fetcher` classes for specific data models.

### 6.1 Default Providers (installed with `pip install openbb`)

| Provider | Package | Source | API Key | Key Data Points |
|----------|---------|--------|---------|-----------------|
| **FMP** | `openbb-fmp` | Financial Modeling Prep | Free tier | ~65 fetchers: equities, financials, ETFs, crypto, FX, news, screener, estimates |
| **Yahoo Finance** | `openbb-yfinance` | Yahoo Finance | None | ~28 fetchers: equities, crypto, FX, futures, options, ETFs, indices |
| **Polygon** | `openbb-polygon` | Polygon.io | Free tier | Equities, crypto, FX, options, indices, NBBO |
| **FRED** | `openbb-fred` | Federal Reserve | Free | ~36 fetchers: rates, CPI, employment, GDP, money supply, yield curves |
| **SEC** | `openbb-sec` | SEC EDGAR | None | Company filings, 13F reports, insider trading, financial statements |
| **Intrinio** | `openbb-intrinio` | Intrinio | Paid | Equities, options, financials, institutional ownership |
| **Benzinga** | `openbb-benzinga` | Benzinga | Paid | News, analyst ratings, IPO calendar, earnings |
| **Tiingo** | `openbb-tiingo` | Tiingo | Free tier | Equities, crypto, FX, news |
| **TradingEconomics** | `openbb-tradingeconomics` | Trading Economics | Paid | Economic indicators, calendars, GDP data |
| **BLS** | `openbb-bls` | Bureau of Labor Statistics | Free | Employment, CPI, wages |
| **OECD** | `openbb-oecd` | OECD | Free | GDP, CPI, unemployment, composite indicators |
| **IMF** | `openbb-imf` | International Monetary Fund | None | Economic indicators, direction of trade |
| **EconDB** | `openbb-econdb` | EconDB | None | Economic indicators, macro data |
| **Congress.gov** | `openbb-congress-gov` | US Congress API | Free | Bills, members, congressional data |
| **CFTC** | `openbb-cftc` | CFTC | Free | Commitments of Traders reports |

### 6.2 Extra Providers (installed separately or via `pip install openbb[all]`)

| Provider | Package | Source | API Key | Key Data Points |
|----------|---------|--------|---------|-----------------|
| **Alpha Vantage** | `openbb-alpha-vantage` | Alpha Vantage | Free tier | Equities, FX, crypto |
| **Cboe** | `openbb-cboe` | Cboe | None | Options, indices, equity data |
| **Deribit** | `openbb-deribit` | Deribit | None | Crypto derivatives, options |
| **ECB** | `openbb-ecb` | European Central Bank | None | Interest rates, yield curves |
| **Fama-French** | `openbb-famafrench` | Ken French Data Library | None | Factor models |
| **Federal Reserve** | `openbb-federal-reserve` | Federal Reserve | None | Fed funds rate, Treasury data |
| **FINRA** | `openbb-finra` | FINRA | None/Free | Short interest, OTC data |
| **Finviz** | `openbb-finviz` | Finviz | None | Screener, performance data |
| **US Government** | `openbb-government-us` | data.gov | None | Treasury auctions, government data |
| **Nasdaq** | `openbb-nasdaq` | Nasdaq Data Link | None/Free | Various datasets |
| **Seeking Alpha** | `openbb-seeking-alpha` | Seeking Alpha | None | Analyst ratings, news |
| **Stockgrid** | `openbb-stockgrid` | Stockgrid | None | Dark pool data, short volume |
| **TMX** | `openbb-tmx` | TMX | None | Canadian market data |
| **Tradier** | `openbb-tradier` | Tradier | None | Options, equities |
| **WSJ** | `openbb-wsj` | Wall Street Journal | None | Market movers, sector data |
| **Biztoc** | `openbb-biztoc` | Biztoc | Free | News aggregation |
| **EIA** | `openbb-eia` | Energy Information Admin. | None | Energy data, petroleum |
| **Multpl** | `openbb-multpl` | Multpl | None | S&P 500 historical multiples |
| **FMP Cached** | `openbb-fmp-cached` | FMP with caching | Free tier | Same as FMP with local caching |

### 6.3 Provider Implementation Pattern

Each provider follows a consistent structure:

```
providers/<name>/
├── openbb_<name>/
│   ├── __init__.py          # Provider registration (name, credentials, fetcher_dict)
│   ├── models/              # One file per data model / Fetcher
│   │   ├── equity_historical.py
│   │   ├── balance_sheet.py
│   │   └── ...
│   └── utils/               # Provider-specific helpers
├── tests/                   # Unit and integration tests
├── pyproject.toml           # Package metadata
└── poetry.lock
```

**Provider Registration Example** (`__init__.py`):
```python
from openbb_core.provider.abstract.provider import Provider

fmp_provider = Provider(
    name="fmp",
    website="https://site.financialmodelingprep.com/",
    description="Financial Modeling Prep data connector",
    credentials=["api_key"],
    fetcher_dict={
        "EquityHistorical": FMPEquityHistoricalFetcher,
        "BalanceSheet": FMPBalanceSheetFetcher,
        # ... 65+ fetcher mappings
    },
)
```

---

## 7. OBBject Extensions

**Location**: `openbb_platform/obbject_extensions/`

OBBject extensions add methods to the `OBBject` result container, enabling post-processing on returned data.

### Charting Extension (`openbb-charting`)

- **Integrated Plotly visualizations** attached to query results
- Access via `result.chart` property or `result.show()` method
- Supports pre-built chart templates for common data types
- Custom charting views per extension (e.g., `equity_views.py`, `economy_views.py`)
- Dedicated window rendering for interactive charts

---

## 8. Standardization Framework

The Standardization Framework is the backbone of cross-provider data consistency.

### How It Works

1. **Standard Models** define common fields shared across 2+ providers (160+ models in `standard_models/`)
2. **Provider Models** inherit from standard models and add provider-specific fields
3. **Fetchers** implement the TET pattern to transform, extract, and transform data
4. **The Platform** dynamically resolves which providers support which models

### Standard Model Categories (160+ models)

| Category | Example Models | Count |
|----------|---------------|-------|
| **Equity** | `EquityHistorical`, `EquityQuote`, `EquityInfo`, `EquityScreener`, `EquitySearch`, `EquityPeers`, `EquityPerformance` | ~25 |
| **Fundamental** | `BalanceSheet`, `IncomeStatement`, `CashFlow`, `FinancialRatios`, `KeyMetrics`, `RevenueBusinessLine` | ~20 |
| **Estimates** | `AnalystEstimates`, `ForwardEpsEstimates`, `ForwardEbitdaEstimates`, `PriceTarget`, `PriceTargetConsensus` | ~8 |
| **Calendar** | `CalendarDividend`, `CalendarEarnings`, `CalendarIPO`, `CalendarSplits`, `EconomicCalendar` | ~5 |
| **ETF** | `EtfHistorical`, `EtfHoldings`, `EtfInfo`, `EtfSearch`, `EtfSectors`, `EtfCountries` | ~10 |
| **Fixed Income** | `TreasuryRates`, `YieldCurve`, `BondPrices`, `BondIndices`, `MortgageIndices`, `SOFR`, `SONIA` | ~20 |
| **Economy** | `GdpReal`, `GdpNominal`, `ConsumerPriceIndex`, `Unemployment`, `NonFarmPayrolls`, `EconomicIndicators` | ~25 |
| **Crypto** | `CryptoHistorical`, `CryptoSearch` | ~2 |
| **Currency** | `CurrencyHistorical`, `CurrencyPairs`, `CurrencySnapshots`, `CurrencyReferenceRates` | ~4 |
| **Options** | `OptionsChains`, `OptionsSnapshots`, `OptionsUnusual` | ~3 |
| **Futures** | `FuturesCurve`, `FuturesHistorical`, `FuturesInstruments` | ~3 |
| **Index** | `IndexHistorical`, `IndexConstituents`, `IndexInfo`, `IndexSearch`, `IndexSnapshots` | ~6 |
| **Ownership** | `InstitutionalOwnership`, `InsiderTrading`, `EquityOwnership`, `Form13FHR` | ~5 |
| **ESG** | `EsgRiskRating`, `EsgScore`, `EsgSector` | ~3 |
| **News** | `CompanyNews`, `WorldNews` | ~2 |
| **Discovery** | `MarketMovers`, `MarketSnapshots`, `DiscoveryFilings` | ~3 |
| **Other** | `CikMap`, `SymbolMap`, `CompanyFilings`, `EarningsCallTranscript`, `RiskPremium`, `SP500Multiples` | ~20+ |

### QueryParams / Data Model Example

```python
# Standard query parameters (shared across all providers)
class EquityHistoricalQueryParams(QueryParams):
    symbol: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None

# Standard data output (shared fields)
class EquityHistoricalData(Data):
    date: datetime
    open: PositiveFloat
    high: PositiveFloat
    low: PositiveFloat
    close: PositiveFloat
    volume: float
    vwap: Optional[PositiveFloat] = None  # Optional: not all providers have it
```

---

## 9. REST API

**Entry Point**: `openbb_platform/core/openbb_core/api/rest_api.py`

The platform includes a production-ready REST API built on FastAPI.

### Starting the API

```bash
# Standard start
uvicorn openbb_core.api.rest_api:app --host 0.0.0.0 --port 8000 --reload

# Or via helper script
openbb-api  # Launches on 127.0.0.1:6900
```

### API Features

- **Auto-generated OpenAPI/Swagger docs** at `/docs`
- **All platform commands exposed as endpoints** (GET/POST)
- **CORS middleware** for cross-origin access
- **Optional authentication** via `API_AUTH` environment variable
- **Provider selection** via `provider` query parameter
- **Consistent error handling** with standardized status codes:
  - `400` - `OpenBBError` (custom business logic errors)
  - `422` - `ValidationError` (Pydantic query validation)
  - `500` - Unexpected errors

### API Endpoint Structure

```
GET  /api/v1/equity/price/historical?symbol=AAPL&provider=yfinance
GET  /api/v1/economy/gdp/nominal?country=united_states
GET  /api/v1/crypto/price/historical?symbol=BTC
POST /api/v1/technical/ema  (accepts data in request body)
GET  /api/v1/coverage/providers  (lists all available providers)
```

---

## 10. MCP Server

**Location**: `openbb_platform/extensions/mcp_server/`
**Package**: `openbb-mcp-server`

The MCP (Model Context Protocol) server enables **LLM agents** to interact with OpenBB's data endpoints.

### Key Features

- **Dynamic Tool Discovery**: Agents explore categories and activate only needed tools
- **Configurable Tool Categories**: Control which endpoints are exposed
- **Multiple Transports**: `streamable-http` (default), SSE, stdio
- **Authentication**: Client-side and server-side auth support
- **Server Prompts**: Custom prompt templates for agent guidance
- **System Prompts**: Configurable system context for agents

### Starting the MCP Server

```bash
openbb-mcp                          # Default settings
openbb-mcp --transport stdio        # For local agent integration
openbb-mcp --allowed-categories equity,economy  # Restrict to specific domains
openbb-mcp --no-tool-discovery      # Disable dynamic tool management
```

### Configuration

Settings are applied in order of precedence:
1. Command-line arguments (highest)
2. Environment variables
3. Config file at `~/.openbb_platform/mcp_settings.json`

---

## 11. Command-Line Interface

**Location**: `cli/`
**Package**: `openbb-cli`

Interactive terminal interface wrapping the Python SDK.

### Features

- **Menu-based navigation** through data categories
- **Auto-completion** for commands and parameters
- **Routine Scripts** for automated data collection workflows
- **Session management** for credential persistence
- **Argparse translation** from Python function signatures

### Usage

```bash
pip install openbb-cli
openbb                    # Launch interactive CLI

# Inside CLI:
/equity/price/historical --symbol AAPL --provider yfinance
/economy/gdp --country united_states
```

### CLI Architecture

```
cli/openbb_cli/
├── cli.py                    # Entry point
├── session.py                # Session management
├── controllers/              # Menu controllers for each extension
├── models/                   # CLI-specific data models
├── config/                   # Configuration handling
├── argparse_translator/      # Converts Python signatures to argparse
└── utils/                    # CLI utilities and helpers
```

---

## 12. Desktop Application

**Location**: `desktop/`

A native desktop application built with **Tauri (Rust)** and **React (TypeScript)**.

### Stack

- **Backend**: Rust via Tauri framework (~50% of codebase)
- **Frontend**: React + TypeScript + Tailwind CSS + Vite (~50%)
- **Distribution**: ~35 MB installed, ~12 MB compressed
- **Platforms**: macOS, Windows (Linux buildable from source)

### Capabilities

- **System tray icon** with background service
- **Environment management** via Miniforge (Conda)
- **Auto-installs**: REST API, MCP Server, NodeJS, Jupyter Lab
- **No admin/root required**: Per-user installation
- **GUI wrapper** for command-line developer tools

### Development

```bash
cd desktop
npm install
npm run tauri dev    # Start development server
```

---

## 13. OpenBB Workspace (Enterprise UI)

**URL**: [pro.openbb.co](https://pro.openbb.co)

OpenBB Workspace is the enterprise-grade web application that consumes data from the ODP backend.

### Core Capabilities

| Feature | Description |
|---------|-------------|
| **Widgets** | Self-contained data components with configurable parameters, metadata, and visual layers |
| **Dashboards** | Customizable canvas with linked widgets (parameter grouping for synchronized updates) |
| **AI Agents** | Context-aware agents that query widgets, perform multi-step analysis, and generate artifacts |
| **Apps** | Pre-built dashboard templates for specific workflows (portfolio management, market surveillance, research) |
| **Prompts** | Context-aware query suggestions that automatically reference relevant widgets |

### Integration with ODP

```bash
pip install "openbb[all]"
openbb-api                    # Starts FastAPI at 127.0.0.1:6900
# Then connect via Workspace UI: Settings > Apps > Connect Backend
```

### Enterprise Features

- On-premises / VPC deployment
- SOC2 Type II compliant
- Role-based access controls
- No data leakage to external services
- Run AI models locally
- Shared dashboards across teams

---

## 14. Charting & Visualization

**Location**: `openbb_platform/obbject_extensions/charting/`
**Package**: `openbb-charting`

### Features

- **Plotly-based** interactive charts
- **Integrated with OBBject**: `result.show()` or `result.chart`
- **Pre-built chart templates** for common visualizations
- **Custom views** per extension (`equity_views.py`, `economy_views.py`, `technical_views.py`)
- **Dedicated rendering window** for standalone chart display

### Usage

```python
from openbb import obb
result = obb.equity.price.historical("AAPL", provider="yfinance", chart=True)
result.show()  # Opens interactive Plotly chart
```

---

## 15. Cookiecutter Template

**Location**: `cookiecutter/`
**Package**: `openbb-cookiecutter`

A project template for bootstrapping new OpenBB extensions.

### Generated Structure

- `pyproject.toml` with proper entry points
- Router extension scaffolding
- Provider extension scaffolding
- OBBject extension scaffolding
- All three types generated together (delete unwanted ones)

### Usage

```bash
pip install openbb-cookiecutter
openbb-cookiecutter            # Interactive prompts for project setup
pip install -e .               # Install generated extension
openbb-build                   # Rebuild platform with new extension
```

---

## 16. Build & Deployment

### Docker

**Location**: `build/docker/`

| Dockerfile | Purpose |
|------------|---------|
| `platform.dockerfile` | Full platform image for development |
| `platformAPI.Dockerfile` | Production API server image |

### PyPI Distribution

**Location**: `build/pypi/`

- Each extension is independently publishable to PyPI
- Uses Poetry for build/publish lifecycle
- Version management via `pyproject.toml`

### Development Installation

```bash
cd openbb_platform
python dev_install.py -e        # Install all packages in editable mode
python dev_install.py --extras  # Include extra/optional extensions
```

### Platform Rebuild

After modifying extensions, rebuild the auto-generated Python interface:

```bash
python -c "import openbb; openbb.build()"
# Or
openbb-build
```

---

## 17. Testing Framework

### Test Types

| Type | Command | Scope |
|------|---------|-------|
| **Unit Tests** | `pytest openbb_platform -m "not integration"` | Individual Fetcher validation |
| **Integration Tests (Python)** | `pytest openbb_platform -m integration` | End-to-end Python SDK |
| **Integration Tests (API)** | Requires running API server | End-to-end REST API |
| **CLI Tests** | `pytest cli/tests` | CLI command parsing and execution |

### Auto-Generated Tests

```bash
# Generate unit tests for all provider Fetchers
python openbb_platform/providers/tests/utils/unit_tests_generator.py

# Generate Python integration tests
python openbb_platform/extensions/tests/utils/integration_tests_generator.py

# Generate API integration tests
python openbb_platform/extensions/tests/utils/integration_tests_api_generator.py

# Record test fixtures
pytest <test_file> --record=all
```

### Quality Tools

- **Ruff**: Linting and formatting (`ruff.toml`)
- **Pyright**: Static type checking (`pyrightconfig.json`)
- **Pre-commit hooks**: Pre-push validation (`.pre-commit-config.yaml`)
- **Codespell**: Spelling checks (`.codespell.ignore`, `.codespell.skip`)
- **Tuna**: Import time profiling

---

## 18. Configuration & Credentials

### User Settings

**File**: `~/.openbb_platform/user_settings.json`

```json
{
  "credentials": {
    "fmp_api_key": "YOUR_KEY",
    "polygon_api_key": "YOUR_KEY",
    "fred_api_key": "YOUR_KEY",
    "benzinga_api_key": "YOUR_KEY",
    "intrinio_api_key": "YOUR_KEY",
    "tiingo_token": "YOUR_KEY"
  }
}
```

### Runtime Configuration

```python
from openbb import obb
obb.user.credentials.fmp_api_key = "YOUR_KEY"
obb.user.credentials.polygon_api_key = "YOUR_KEY"
```

### MCP Server Settings

**File**: `~/.openbb_platform/mcp_settings.json`

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `API_AUTH` | Enable/disable API authentication |
| `FMP_CACHE_TEST_MODE` | Enable FMP cache testing mode |
| `OPENBB_API_AUTH` | API auth toggle |

---

## 19. Examples & Notebooks

**Location**: `examples/` and `Analysis/`

| Notebook | Topic |
|----------|-------|
| `loadHistoricalPriceData.ipynb` | Loading and visualizing stock prices |
| `financialStatements.ipynb` | Analyzing company financial statements |
| `portfolioOptimizationUsingModernPortfolioTheory.ipynb` | Mean-variance portfolio optimization |
| `BacktestingMomentumTrading.ipynb` | Backtesting momentum strategies |
| `copperToGoldRatio.ipynb` | Commodity ratio analysis |
| `currencyExchangeRateForecasting.ipynb` | FX rate prediction |
| `EthereumTrendAnalysis.ipynb` | Crypto trend analysis |
| `impliedEarningsMove.ipynb` | Options-implied earnings moves |
| `sectorRotationStrategy.ipynb` | Sector rotation investment strategy |
| `riskReturnAnalysis.ipynb` | Risk-return profiling |
| `usdLiquidityIndex.ipynb` | USD liquidity analysis |
| `mAndAImpact.ipynb` | M&A event impact analysis |
| `openbbPlatformAsLLMTools.ipynb` | Using OpenBB as LLM tools |
| `openbb_vs_langchain.ipynb` | Comparison with LangChain |
| `platform_standardization.ipynb` | Standardization framework demo |
| `MarketIndicators.ipynb` | Market breadth indicators |
| `findSymbols.ipynb` | Searching for securities |
| `googleColab.ipynb` | Running OpenBB in Google Colab |
| `openbb-apachebeam/` | Apache Beam data pipeline integration |
| `streamlit/` | Streamlit dashboard examples |

---

## 20. Key Design Patterns

### 20.1 TET Pattern (Transform-Extract-Transform)

The core data fetching pattern used by all providers:

```
1. Transform Query  → Convert user params to provider-specific format
2. Extract Data     → Make HTTP request to provider API
3. Transform Data   → Normalize raw response to standard schema
```

```python
class MyProviderEquityHistoricalFetcher(Fetcher[MyQueryParams, List[MyData]]):

    @staticmethod
    def transform_query(params: Dict[str, Any]) -> MyQueryParams:
        """Transform user input to provider format."""
        return MyQueryParams(**params)

    @staticmethod
    async def aextract_data(query: MyQueryParams, credentials: Dict) -> Any:
        """Fetch raw data from the API."""
        return await make_request(query, credentials)

    @staticmethod
    def transform_data(query: MyQueryParams, data: Any) -> List[MyData]:
        """Normalize raw data to standard schema."""
        return [MyData.model_validate(d) for d in data]
```

### 20.2 Extension Plugin System

Extensions register via Python entry points in `pyproject.toml`:

```toml
[tool.poetry.plugins."openbb_extensions"]
equity = "openbb_equity:equity_router"

[tool.poetry.plugins."openbb_providers"]
fmp = "openbb_fmp:fmp_provider"

[tool.poetry.plugins."openbb_obbject_extensions"]
charting = "openbb_charting:charting_obbject_extension"
```

### 20.3 Command Routing

FastAPI-based command definition with automatic schema generation:

```python
@router.command(model="EquityHistorical")
async def historical(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get historical equity prices."""
    return await OBBject.from_query(Query(**locals()))
```

### 20.4 Data Processing Pipeline

The `Data` base class enables universal post-processing:

```python
# Any data can be processed, regardless of source
result = obb.equity.price.historical("AAPL")
ema_result = obb.technical.ema(data=result.results, target="close", length=50)

# Or use custom data
from openbb_core.provider.abstract.data import Data
my_data = [Data.model_validate(record) for record in my_records]
obb.technical.ema(data=my_data)
```

---

## 21. Data Domains & Capabilities Matrix

### Provider × Domain Coverage

| Domain | FMP | yFinance | Polygon | FRED | SEC | Intrinio | Benzinga | Others |
|--------|-----|----------|---------|------|-----|----------|----------|--------|
| Equity Prices | ✅ | ✅ | ✅ | — | — | ✅ | — | Tiingo, Cboe |
| Equity Fundamentals | ✅ | ✅ | — | — | ✅ | ✅ | — | — |
| Equity Screener | ✅ | ✅ | — | — | — | — | — | Finviz |
| Options | ✅ | ✅ | ✅ | — | — | ✅ | — | Cboe, Tradier |
| Crypto | ✅ | ✅ | ✅ | — | — | — | — | Tiingo, Deribit |
| FX / Currency | ✅ | ✅ | ✅ | — | — | — | — | ECB |
| ETFs | ✅ | ✅ | — | — | — | ✅ | — | TMX |
| Fixed Income | ✅ | — | — | ✅ | — | — | — | ECB, Fed |
| Economic Data | ✅ | — | — | ✅ | — | — | — | OECD, BLS, IMF, EconDB |
| News | ✅ | — | — | — | — | — | ✅ | Biztoc, Tiingo |
| Indices | ✅ | ✅ | ✅ | — | — | — | — | Cboe |
| Insider Trading | ✅ | — | — | — | ✅ | — | — | — |
| Institutional | ✅ | — | — | — | ✅ | ✅ | — | — |
| Earnings | ✅ | — | — | — | — | ✅ | ✅ | — |
| Commodities | — | — | — | ✅ | — | — | — | EIA |
| Government | — | — | — | — | ✅ | — | — | Congress, CFTC |

### Technical Analysis Capabilities

The `technical` extension provides 50+ indicators including:

- **Trend**: EMA, SMA, WMA, HMA, DEMA, TEMA, VWAP, ADX, Aroon, Ichimoku
- **Momentum**: RSI, MACD, Stochastic, CCI, Williams %R, ROC, CMO
- **Volatility**: Bollinger Bands, ATR, Keltner Channels, Donchian
- **Volume**: OBV, AD, VWAP, MFI, CMF
- **Other**: Fibonacci, Pivot Points, Relative Rotation Graphs

---

## Summary

The OpenBB Open Data Platform is a comprehensive, modular financial data infrastructure with:

- **35+ data providers** covering equities, fixed income, crypto, FX, commodities, economics, and more
- **160+ standardized data models** ensuring cross-provider consistency
- **20+ router extensions** organizing 500+ data endpoints across financial domains
- **6 consumption surfaces**: Python SDK, REST API, CLI, MCP Server, Desktop App, and OpenBB Workspace
- **Enterprise-grade features**: Authentication, Docker deployment, SOC2 compliance, on-premises support
- **AI integration**: MCP server for LLM agents, OpenBB Workspace AI capabilities
- **Extensible architecture**: Cookiecutter templates, plugin system, and comprehensive developer documentation
- **Rich examples**: 15+ Jupyter notebooks covering investment strategies, analysis, and platform usage

The platform embodies the **"connect once, consume everywhere"** philosophy, making it a robust choice for teams needing unified financial data access across multiple workflows and tools.
