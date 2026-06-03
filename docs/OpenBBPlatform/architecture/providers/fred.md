# fred — Federal Reserve Economic Data (economic time-series)

[← providers/ architecture](./README.md) · Design: [providers/ design](../../design/providers/README.md) · [GLOSSARY](../../GLOSSARY.md)

> The reference for an **economic time-series** provider whose results are pivoted from
> per-series dicts and carry **side-band metadata** via `AnnotatedResult`.
> Source: `providers/fred/openbb_fred/`. Last verified: 2026-06-02.

---

## Quick-ref card

| Field | Value |
|---|---|
| **Provider id** | `fred` |
| **Credential** | `fred_api_key` (`credentials=["api_key"]`) |
| **repr_name** | `Federal Reserve Economic Data \| St. Louis FED (FRED)` |
| **Extract style** | **async** (`aextract_data`) |
| **Raw extract type** | `list[dict]` (`{series_id: {title, units, ..., data: {date: value}}}`) |
| **HTTP layer** | core `amake_requests` |
| **Fetchers** | ~37 in `fetcher_dict` |
| **Notable** | `transform_data` returns `AnnotatedResult[list[Data]]` (results + metadata) |

→ Symbol: `openbb_fred/__init__.py::fred_provider`

---

## Provider manifest

```python
fred_provider = Provider(
    name="fred",
    website="https://fred.stlouisfed.org",
    credentials=["api_key"],                  # → fred_api_key
    repr_name="Federal Reserve Economic Data | St. Louis FED (FRED)",
    deprecated_credentials={"API_FRED_KEY": "fred_api_key"},
    fetcher_dict={ "FredSeries": FredSeriesFetcher, ... },   # ~37
)
```

---

## Representative model — `models/series.py`

```python
class FredSeriesQueryParams(SeriesQueryParams):
    __alias_dict__ = {                          # outbound → FRED param names
        "symbol": "series_id",
        "start_date": "observation_start",
        "end_date": "observation_end",
        "transform": "units",
    }
    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}
    frequency: ...
    aggregation_method: ...
    transform: ...
    limit: int = 100000

class FredSeriesData(SeriesData):
    """Empty subclass — values attach dynamically per series_id column."""

class FredSeriesFetcher(Fetcher[FredSeriesQueryParams, list[FredSeriesData]]):
    @staticmethod
    async def aextract_data(query, credentials, **kwargs) -> list[dict]:
        api_key = credentials.get("fred_api_key")
        from openbb_core.provider.utils.helpers import amake_requests, get_querystring
        ...   # hits /fred/series/observations per series_id (+ metadata from /fred/series)

    @staticmethod
    def transform_data(query, data, **kwargs) -> AnnotatedResult[list[FredSeriesData]]:
        ...   # pivots per-series dicts into date-indexed records; returns results + metadata
```

- The standard `SeriesData` shape is essentially just `date: dateType`; **observation values
  are columns attached dynamically** per series (this is why `extra="allow"` matters). → [ADR-5](../../design/01-decisions.md#adr-5--extraallow-on-queryparams-and-data)
- `transform_data` returns an **`AnnotatedResult`** so series titles/units/frequency travel
  in `OBBject.extra` rather than polluting each row. → [GLOSSARY AnnotatedResult](../../GLOSSARY.md)
- Metadata is fetched from `.../fred/series` (note the FRED `"seriess"` JSON key — intentional).

---

## Supporting code — `utils/`

| File | Role |
|---|---|
| `fred_base.py::Fred` | base class for the FRED API |
| `fred_helpers.py` | data-shaping helpers (`get_cpi_options`, `process_projections`, `get_ice_bofa_series_id`, …) + bundled reference data (`cpi.csv`, `corporate_spot_rates.csv`, …) |

FRED relies on **core** `amake_requests` for HTTP — no provider-local `get_data` wrapper
like fmp.

---

→ Contrast: [fmp (async REST, list[dict])](./fmp.md) · [yfinance (sync, DataFrame)](./yfinance.md)
→ Mechanics: [Provider Framework](../core/provider-framework.md) · Add one: [Recipes A](../../design/03-recipes.md#recipe-a--add-a-provider-integration-for-an-existing-standard-model)
