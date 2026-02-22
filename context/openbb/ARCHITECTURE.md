# OpenBB Platform — Architecture Overview

> **Purpose:** Top-level architectural guide for the OpenBB Open Data Platform.
> Explains how all the pieces fit together — the plugin system, data flow,
> extension model, and key design patterns.

---

## 1. What is OpenBB Platform?

OpenBB is a **plugin-based financial data aggregation platform** that provides a
unified interface to 35+ data providers (FMP, Yahoo Finance, Polygon, FRED, etc.).

Key value proposition: **Write one query, get data from any provider** with a
standardized schema.  Provider differences are abstracted away by a shared
data model layer.

### Consumption Surfaces

| Surface | Entry Point | Description |
|---------|-------------|-------------|
| **Python SDK** | `from openbb import obb` | Direct Python API, auto-generated |
| **REST API** | `python -m openbb_core.api.rest_api` | FastAPI server (uvicorn) |
| **CLI** | `openbb` | Command-line interface |
| **MCP Server** | `openbb_mcp_server` | Model Context Protocol for AI agents |

All surfaces share the same underlying `CommandRunner` → `Query` → `Fetcher` pipeline.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CONSUMPTION LAYER                          │
│   Python SDK          REST API          CLI          MCP Server     │
│   (openbb/)           (FastAPI)         (openbb_cli) (ext)         │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────────┐
│                    COMMAND EXECUTION                                │
│   Router  →  CommandRunner  →  ParametersBuilder  →  Query         │
│              ExecutionContext     validation          execution     │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────────┐
│                    PROVIDER INTERFACE                               │
│   ProviderInterface (singleton)                                     │
│     ├── RegistryMap   — maps models → providers → fetchers          │
│     ├── Registry      — loaded Provider objects                     │
│     └── QueryExecutor — dispatches to correct Fetcher               │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────────┐
│                    PROVIDER LAYER                                   │
│   Fetcher[QueryParams, Data]                                       │
│     ├── transform_query()    — normalize params                     │
│     ├── extract_data()       — HTTP call to data source             │
│     └── transform_data()     — normalize response to Data model     │
│                                                                     │
│   Standard Models (shared):  EquityHistoricalQueryParams / Data     │
│   Provider Models (custom):  FMPEquityHistoricalQueryParams / Data  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────────┐
│                    OUTPUT LAYER                                     │
│   OBBject[T]                                                       │
│     ├── results: T         — the actual data (List[Data])           │
│     ├── provider: str      — which provider served it               │
│     ├── warnings: list     — any warnings                           │
│     ├── chart: Chart       — optional chart (charting extension)    │
│     └── .to_df()           — convert to pandas DataFrame            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. The Three Extension Types

OpenBB uses Python **entry points** (via `pyproject.toml`) to discover plugins at
install time.  There are three extension groups:

| Group | Entry Point Key | Purpose | Example |
|-------|-----------------|---------|---------|
| **Core Extension** | `openbb_core_extension` | Adds API routes (commands) | `openbb-equity`, `openbb-crypto` |
| **Provider Extension** | `openbb_provider_extension` | Adds data source adapters | `openbb-fmp`, `openbb-yfinance` |
| **OBBject Extension** | `openbb_obbject_extension` | Adds methods to OBBject results | `openbb-charting` |

### Registration Flow

```
pyproject.toml                    ExtensionLoader
  [openbb_core_extension]    →     core_entry_points    → Router objects
  equity = "openbb_equity        
    .equity_router:router"

  [openbb_provider_extension] →    provider_entry_points → Provider objects
  fmp = "openbb_fmp:fmp_provider"

  [openbb_obbject_extension]  →    obbject_entry_points  → Extension objects
  charting = "openbb_charting
    :ext"
```

### How It Works

1. `ExtensionLoader` (singleton) scans all installed packages for entry points
   in the three groups
2. Core extensions provide `Router` objects → mounted as API routes
3. Provider extensions provide `Provider` objects → registered in `Registry`
4. OBBject extensions provide `Extension` objects → added as accessors on `OBBject`

---

## 4. The Fetcher Pattern (Core Design)

Every data query flows through a **Fetcher** — the central abstraction:

```python
class Fetcher(Generic[Q, R]):
    """Q = QueryParams subclass, R = return type (usually List[Data])"""

    @staticmethod
    def transform_query(params: dict) -> Q:
        """Normalize user params → provider-specific query."""

    @staticmethod
    async def aextract_data(query: Q, credentials: dict) -> Any:
        """Async HTTP call to data source (or sync extract_data)."""

    @staticmethod
    def transform_data(query: Q, data: Any) -> R:
        """Raw API response → standardized Data models."""

    @classmethod
    async def fetch_data(cls, params, credentials) -> R:
        """Full pipeline: transform_query → extract_data → transform_data"""
```

### Standard vs Provider Models

```
Standard Model (shared contract)     Provider Model (source-specific)
─────────────────────────────────    ─────────────────────────────────
EquityHistoricalQueryParams          FMPEquityHistoricalQueryParams
  symbol: str                          (inherits standard fields)
  start_date: date                     interval: "1d" | "1m" | ...
  end_date: date                       adjustment: "splits_only" | ...

EquityHistoricalData                 FMPEquityHistoricalData
  date: date                           (inherits standard fields)
  open: float                          adj_close: float
  high: float                          change: float
  low: float                           change_percent: float
  close: float
  volume: int
  vwap: float
```

---

## 5. Query Execution Pipeline

When a user calls `obb.equity.price.historical(symbol="AAPL", provider="fmp")`:

```
1. Python SDK method (auto-generated)
   └── calls CommandRunner.run()

2. CommandRunner
   ├── creates ExecutionContext (route, settings)
   ├── ParametersBuilder validates & builds typed params
   │   ├── ProviderChoices (which provider)
   │   ├── StandardParams  (shared fields)
   │   └── ExtraParams     (provider-specific fields)
   └── invokes the route function

3. Route function (e.g., equity_router.py → price_router.py)
   └── return await OBBject.from_query(Query(**locals()))

4. Query
   ├── resolves provider from ProviderChoices
   ├── filters ExtraParams for the chosen provider
   └── calls ProviderInterface.execute()

5. QueryExecutor
   ├── gets Provider from Registry
   ├── gets Fetcher from provider's fetcher_dict
   ├── filters credentials
   └── calls Fetcher.fetch_data(params, credentials)

6. Fetcher.fetch_data()
   ├── transform_query()  — dict → QueryParams
   ├── extract_data()     — HTTP call to FMP/Yahoo/etc.
   └── transform_data()   — raw JSON → List[Data]

7. Result wrapped in OBBject[List[Data]]
   └── returned to user with .to_df(), .results, .chart
```

---

## 6. Auto-Generated SDK

The Python SDK (`openbb/package/`) is **auto-generated** by `PackageBuilder`:

1. Reads all registered routes from core extensions
2. Reads all registered providers and their params from `ProviderInterface`
3. Generates Python modules with typed methods, docstrings, and examples
4. Writes to `openbb/package/*.py` and `openbb/assets/reference.json`

This is triggered by `python -c "from openbb import obb"` on first import,
or explicitly via `openbb_core.app.static.package_builder.PackageBuilder.build()`.

**Key implication:** After adding a new provider or extension, you must rebuild
the SDK package for it to appear in `obb.*` calls.

---

## 7. Configuration & Settings

| Setting | Source | Purpose |
|---------|--------|---------|
| `user_settings.json` | `~/.openbb_platform/` | API keys, default providers, preferences |
| `system_settings.json` | `~/.openbb_platform/` | API server config, logging, debug mode |
| `Env` class | `openbb_core/env.py` | Environment variable reader (DEBUG_MODE, API_AUTH, etc.) |

Credentials are stored as `SecretStr` and never logged.  The `UserService`
provides access: `UserService.read_default_user_settings().credentials`.

---

## 8. Module Map

| Module | Location | Purpose |
|--------|----------|---------|
| `openbb_core.api` | `core/openbb_core/api/` | FastAPI REST server + routes |
| `openbb_core.app` | `core/openbb_core/app/` | Command runner, router, provider interface |
| `openbb_core.provider` | `core/openbb_core/provider/` | Abstract classes, standard models, registry |
| `openbb` | `core/openbb/` | Auto-generated Python SDK package |
| Extensions | `extensions/*/` | Feature routers (equity, crypto, etc.) |
| Providers | `providers/*/` | Data source adapters (fmp, yfinance, etc.) |
| OBBject Extensions | `obbject_extensions/*/` | Result extensions (charting) |

See the companion files for deep dives into each module:
- `OPENBB_CORE.md` — Core infrastructure details
- `OPENBB_PROVIDERS.md` — Provider system and all 35+ providers
- `OPENBB_EXTENSIONS.md` — All core extensions and their routes
- `OPENBB_STANDARD_MODELS.md` — Complete standard model catalog

---

*Last updated: 2026-02-21*
