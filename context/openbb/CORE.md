# OpenBB Core — Deep Dive

> **Purpose:** Detailed reference for `openbb_platform/core/openbb_core/`,
> the engine that powers the entire OpenBB platform.
>
> **See also:** `context/openbb/ARCHITECTURE.md` for the high-level overview.

---

## 1. Module Map

```
openbb_platform/core/openbb_core/
├── api/
│   └── rest_api.py              # FastAPI application (106 lines)
├── app/
│   ├── command_runner.py        # Command execution pipeline (647 lines)
│   ├── extension_loader.py      # Plugin discovery via entry points (195 lines)
│   ├── provider_interface.py    # Dynamic param/schema builder (666 lines)
│   ├── query.py                 # Query dispatch to provider Fetcher (81 lines)
│   ├── router.py                # Router, CommandMap, SignatureInspector (519 lines)
│   ├── deprecation.py           # Deprecation warning support
│   ├── model/
│   │   ├── obbject.py           # OBBject[T] result container (383 lines)
│   │   ├── command_context.py   # CommandContext (user+system settings)
│   │   ├── metadata.py          # Metadata (route, duration, timestamp)
│   │   ├── extension.py         # Extension + CachedAccessor
│   │   ├── example.py           # APIEx example definitions
│   │   ├── system_settings.py   # SystemSettings model
│   │   ├── user_settings.py     # UserSettings model
│   │   └── abstract/
│   │       ├── error.py         # OpenBBError
│   │       ├── warning.py       # OpenBBWarning, Warning_
│   │       ├── singleton.py     # SingletonMeta metaclass
│   │       └── tagged.py        # Tagged base with UUID id
│   ├── service/
│   │   ├── auth_service.py      # Authentication
│   │   ├── system_service.py    # System settings management
│   │   └── user_service.py      # User settings management
│   ├── static/
│   │   └── package_builder.py   # Auto-generates SDK (3603 lines)
│   └── logs/
│       └── logging_service.py   # Logging
├── provider/
│   ├── abstract/
│   │   ├── fetcher.py           # Fetcher[Q, R] base class (234 lines)
│   │   ├── provider.py          # Provider class (~60 lines)
│   │   ├── data.py              # Data base model (97 lines)
│   │   ├── query_params.py      # QueryParams base model (~80 lines)
│   │   └── annotated_result.py  # AnnotatedResult wrapper
│   ├── registry.py              # Registry + RegistryLoader
│   ├── registry_map.py          # RegistryMap — model→provider→fields (208 lines)
│   ├── query_executor.py        # QueryExecutor — dispatches to Fetcher (98 lines)
│   ├── standard_models/         # 161 standard model definitions
│   └── utils/
│       └── helpers.py           # maybe_coroutine, run_async, to_snake_case
└── env.py                       # Env class (DEBUG_MODE, etc.)
```

---

## 2. Key Classes

### 2.1 Router (`app/router.py`)

The `Router` class wraps FastAPI's `APIRouter` and adds:

- **`@router.command(model="ModelName")`** — Decorator that binds a standard
  model to a route function.  The `SignatureInspector` injects the correct
  `ProviderChoices`, `StandardParams`, and `ExtraParams` as dependencies.
- **`include_router(router, prefix)`** — Nest sub-routers (e.g., `/equity/price`).
- **`CommandMap`** — Built from the fully-assembled router tree.  Maps
  route paths (strings) → endpoint callables.  Also computes provider coverage
  and command-to-model mappings.
- **`RouterLoader.from_extensions()`** — Loads all `openbb_core_extension`
  entry points and includes their routers.  Cached via `@lru_cache`.

```python
# Extension router pattern:
router = Router(prefix="", description="Equity market data.")
router.include_router(price_router, prefix="/price")

@router.command(model="EquitySearch")
async def search(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    return await OBBject.from_query(Query(**locals()))
```

### 2.2 CommandRunner (`app/command_runner.py`)

Two-class design:

| Class | Role |
|-------|------|
| `StaticCommandRunner` | Static methods: `_execute_func()`, `_command()`, `_chart()`, `run()` |
| `CommandRunner` | Instance wrapper with settings, delegates to `StaticCommandRunner` |

**Execution flow:**

```
CommandRunner.run(route, **kwargs)
  └→ StaticCommandRunner.run(execution_context, **kwargs)
       ├→ ParametersBuilder.build()     # merge, validate, inject CommandContext
       ├→ _command(func, kwargs)        # await the route function
       ├→ _chart(obbject)              # if chart=True, invoke charting extension
       ├→ _trigger_command_output_callbacks()  # obbject extension hooks
       └→ OBBject with metadata, warnings, provider info
```

**Key helpers:**

- **`ExecutionContext`** — Bundles `CommandMap`, route, `SystemSettings`, `UserSettings`.
- **`ParametersBuilder`** — Merges positional args + kwargs, injects `CommandContext`,
  validates via dynamic Pydantic model, warns on unknown extra params.

### 2.3 ExtensionLoader (`app/extension_loader.py`)

**Singleton** that discovers plugins via Python entry points:

| Entry Point Group | What It Loads | Property |
|-------------------|---------------|----------|
| `openbb_core_extension` | `Router` objects | `.core_objects` |
| `openbb_provider_extension` | `Provider` objects | `.provider_objects` |
| `openbb_obbject_extension` | `Extension` objects | `.obbject_objects` |

All properties are `@lru_cache`d.  Loading is lazy — extensions are loaded on
first access.

**Command output callbacks:** OBBject extensions can register to be called after
every command execution (e.g., the charting extension).  The `ExtensionLoader`
manages callback registration and the `CommandRunner` triggers them.

### 2.4 ProviderInterface (`app/provider_interface.py`)

**Singleton** that builds the bridge between standard models and provider-specific
implementations.  This is the most complex class in the system (~666 lines).

**What it builds (on initialization):**

| Property | Type | Description |
|----------|------|-------------|
| `.map` | `MapType` | `{model → {provider → {QueryParams/Data → fields}}}` |
| `.model_providers` | `dict[str, ProviderChoices]` | Per-model provider choice dataclass |
| `.params` | `dict[str, dict]` | Per-model standard + extra params |
| `.data` | `dict[str, dict]` | Per-model standard + extra data schemas |
| `.return_schema` | `dict[str, BaseModel]` | Per-model merged return type |
| `.return_annotations` | `dict[str, OBBject]` | Per-model typed `OBBject[T]` |
| `.available_providers` | `list[str]` | All loaded provider names |
| `.models` | `list[str]` | All model names |
| `.credentials` | `dict[str, list]` | Provider → required credentials |

**Key methods:**

- `_create_field()` — Builds dataclass fields with description, type info,
  and json_schema_extra (multiple_items_allowed, choices, etc.).
- `_merge_fields()` — Merges fields from multiple providers that define the
  same field name, combining descriptions and types.
- `_generate_params_dc()` — Generates `StandardParams` and `ExtraParams`
  dataclasses for each model dynamically.
- `create_executor()` — Returns a fresh `QueryExecutor` instance.

### 2.5 Query (`app/query.py`)

Simple 81-line class that:

1. Receives `provider_choices`, `standard_params`, `extra_params`
2. Resolves the provider name from `provider_choices`
3. Filters extra params to only those relevant to the chosen provider
4. Calls `QueryExecutor.execute(provider_name, model_name, params, credentials)`
5. Returns `OBBject` with results

### 2.6 OBBject (`app/model/obbject.py`)

Generic result container `OBBject[T]`:

```python
class OBBject(Tagged, Generic[T]):
    results: T | None          # The actual data
    provider: str | None       # Which provider served it
    warnings: list[Warning_]   # Any warnings during fetch
    chart: Chart | None        # Auto-generated chart (if requested)
    extra: dict[str, Any]      # Metadata, custom info
```

**Key methods:**
- `to_df()` / `to_dataframe()` — Convert results to Pandas DataFrame
- `to_dict()` — Convert to dict
- `to_polars()` — Convert to Polars DataFrame
- `to_numpy()` — Convert to NumPy array
- `show()` — Display chart

**Accessor pattern:** OBBject extensions (like charting) register themselves
as descriptors via `CachedAccessor`.  Access via `obbject.charting.show()`.

---

## 3. The Fetcher Pattern

The `Fetcher[Q, R]` generic class is the **core data abstraction**:

```python
class Fetcher(Generic[Q, R]):
    require_credentials = True

    @staticmethod
    def transform_query(params: dict) -> Q:
        """Validate and transform input params into provider-specific QueryParams."""

    @staticmethod
    def extract_data(query: Q, credentials: dict) -> Any:
        """Make the API call and return raw data."""

    @staticmethod
    def transform_data(query: Q, data: Any) -> R:
        """Transform raw data into standardized Data models."""

    @classmethod
    async def fetch_data(cls, params, credentials) -> R:
        """Pipeline: transform_query → extract_data → transform_data"""
```

**Design decisions:**
- `extract_data` and `aextract_data` — If async version is implemented, it
  takes precedence.  If neither is implemented, raises `NotImplementedError`.
- `transform_data` can return `R` or `AnnotatedResult[R]` (for extra metadata).
- `test()` classmethod — Built-in TET (Transform-Extract-Transform) test
  that validates types, fields, and data at each stage.

**Type introspection properties:**
- `query_params_type` — Extracts `Q` from `Fetcher[Q, R]`
- `return_type` — Extracts `R` (unwraps `AnnotatedResult`)
- `data_type` — Extracts the inner `Data` type from `R` (handles `list[D]`)

---

## 4. Data Layer

### 4.1 Data (`provider/abstract/data.py`)

```python
class Data(BaseModel):
    model_config = ConfigDict(
        extra="allow",           # Accept fields not in schema
        populate_by_name=True,   # Allow both alias and name
        strict=False,
    )
```

- **`extra="allow"`** is critical — providers can return fields beyond the
  standard model, and they pass through.
- **Alias generation:** `camelCase` for validation, `snake_case` for serialization.
- **`__alias_dict__`** — Subclasses can define custom aliases.

### 4.2 QueryParams (`provider/abstract/query_params.py`)

```python
class QueryParams(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
```

- **`__alias_dict__`** — Maps field names to API-specific parameter names.
  Applied during `model_dump()`.
- **`__json_schema_extra__`** — Metadata for the schema (e.g.,
  `multiple_items_allowed`, `choices`).  Merged across providers by
  `RegistryMap`.

### 4.3 Standard Models (`provider/standard_models/`)

161 files defining standardized interfaces.  Each file exports:
- `*QueryParams(QueryParams)` — Standard query fields
- `*Data(Data)` — Standard response fields

Example pattern:
```python
class EquityHistoricalQueryParams(QueryParams):
    symbol: str
    start_date: dateType | None = None
    end_date: dateType | None = None

class EquityHistoricalData(Data):
    date: dateType | datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | int | None = None
    vwap: float | None = None
```

Provider-specific implementations **inherit** these and add extra fields.

---

## 5. Registry & Discovery

### 5.1 Registry (`provider/registry.py`)

```python
class Registry:
    providers: dict[str, Provider]  # name → Provider
    def include_provider(provider: Provider) -> None

class RegistryLoader:
    @staticmethod @lru_cache
    def from_extensions() -> Registry
```

`RegistryLoader.from_extensions()` delegates to `ExtensionLoader().provider_objects`
which reads the `openbb_provider_extension` entry points.

### 5.2 RegistryMap (`provider/registry_map.py`)

Builds the **grand map** of all models across all providers:

```python
standard_extra: {
    "EquityHistorical": {
        "openbb": { "QueryParams": {...}, "Data": {...} },
        "fmp":    { "QueryParams": {...}, "Data": {...} },
        "yfinance": { "QueryParams": {...}, "Data": {...} },
        ...
    }
}
```

- Separates **standard fields** (from files in `standard_models/`) from
  **extra fields** (defined in provider-specific models) using source file
  path inspection.
- Merges `__json_schema_extra__` across providers for each field.

### 5.3 QueryExecutor (`provider/query_executor.py`)

```python
class QueryExecutor:
    async def execute(provider_name, model_name, params, credentials) -> Any:
        provider = self.get_provider(provider_name)
        fetcher = self.get_fetcher(provider, model_name)
        credentials = self.filter_credentials(credentials, provider, fetcher.require_credentials)
        return await fetcher.fetch_data(params, credentials)
```

**Credential filtering:** Extracts only the credentials relevant to the
chosen provider, validates they are non-empty, raises `OpenBBError` with
helpful message if missing.

---

## 6. REST API (`api/rest_api.py`)

Simple FastAPI app (~106 lines):

```python
app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, ...)
app.include_router(CommandRunner()._command_map._router.api_router)
```

- **Lifespan:** Prints banner on startup.
- **CORS:** Allows all origins by default.
- **Routes:** Auto-included from the CommandMap router tree.
- **Launch:** `uvicorn openbb_core.api.rest_api:app`

---

## 7. Auto-Generated SDK (`app/static/package_builder.py`)

The `PackageBuilder` (3603 lines) **auto-generates** the `openbb/package/*.py`
files that create the user-facing Python SDK.

**What it generates:**
- `openbb/package/module_equity.py` — `class ROUTER_equity` with methods
  like `.search()`, `.screener()`, `.profile()`.
- `openbb/package/module_equity_price.py` — `class ROUTER_equity_price`
  with `.historical()`, `.quote()`, etc.
- Proper type annotations, docstrings, provider choices, default values.

**Built from:**
- `CommandMap` — All routes and their endpoints.
- `ProviderInterface` — Parameter types, provider choices, return types.
- `PathHandler` — Route path parsing and mapping.

---

## 8. Configuration

### SystemSettings
- `logging_suppress` — Disable logging.
- `debug_mode` — Enable stack traces and model validation errors.
- `api_settings` — Custom headers, CORS config.

### UserSettings
- `preferences.metadata` — Include metadata in OBBject.
- `preferences.show_warnings` — Display warnings.
- `credentials` — Provider API keys (`dict[str, SecretStr]`).
- Stored in `~/.openbb_platform/user_settings.json`.

### Env (`env.py`)
- `DEBUG_MODE` — From environment variable `OPENBB_DEBUG_MODE`.
- Accessed as `Env().DEBUG_MODE` throughout codebase.

---

*Last updated: 2026-02-21*
