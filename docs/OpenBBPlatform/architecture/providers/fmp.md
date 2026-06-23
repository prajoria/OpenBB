# fmp — Financial Modeling Prep (broad async REST provider)

[← providers/ architecture](./README.md) · Design: [providers/ design](../../design/providers/README.md) · [GLOSSARY](../../GLOSSARY.md)

> The widest provider in the platform (~67 fetchers). Use it as the **template for any
> async REST-API provider**. Source: `providers/fmp/openbb_fmp/`. Last verified: 2026-06-02.

---

## Quick-ref card

| Field | Value |
|---|---|
| **Provider id** | `fmp` |
| **Credential** | `fmp_api_key` (`credentials=["api_key"]`, auto-prefixed) |
| **repr_name** | `Financial Modeling Prep (FMP)` |
| **Extract style** | **async** (`aextract_data`) |
| **Raw extract type** | `list[dict]` |
| **HTTP layer** | core `amake_request(s)` via local `utils/helpers.py::get_data` wrapper |
| **Fetchers** | ~67 in `fetcher_dict` |
| **Notable flags** | `deprecated_credentials={"API_KEY_FINANCIALMODELINGPREP": "fmp_api_key"}` |

→ Symbol: `openbb_fmp/__init__.py::fmp_provider`

---

## Provider manifest

```python
fmp_provider = Provider(
    name="fmp",
    website="https://financialmodelingprep.com",
    credentials=["api_key"],                 # → fmp_api_key
    repr_name="Financial Modeling Prep (FMP)",
    deprecated_credentials={"API_KEY_FINANCIALMODELINGPREP": "fmp_api_key"},
    fetcher_dict={ "EquityHistorical": FMPEquityHistoricalFetcher, ... },  # ~67
    instructions="Go to: https://site.financialmodelingprep.com/developer/docs ...",
)
```

**One fetcher can serve multiple models** (the routing table is just a dict):
`EtfHistorical → FMPEquityHistoricalFetcher`, `EquityInfo → FMPEquityProfileFetcher`,
`EtfPricePerformance → FMPPricePerformanceFetcher`.

---

## Representative model — `models/equity_historical.py`

```python
class FMPEquityHistoricalQueryParams(EquityHistoricalQueryParams):
    __alias_dict__ = {"start_date": "from", "end_date": "to"}      # outbound → vendor
    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}
    interval: ...        # 1m … 1d
    adjustment: ...      # splits_only / splits_and_dividends / unadjusted
    # model_validator(mode="before") normalizes inputs

class FMPEquityHistoricalData(EquityHistoricalData):
    __alias_dict__ = {"open": "adjOpen", "high": "adjHigh",         # inbound vendor → ours
                      "low": "adjLow", "close": "adjClose"}
    change: Optional[float]
    change_percent: Optional[float]   # field_validator divides vendor % by 100

class FMPEquityHistoricalFetcher(
    Fetcher[FMPEquityHistoricalQueryParams, list[FMPEquityHistoricalData]]
):
    @staticmethod
    async def aextract_data(query, credentials, **kwargs) -> list[dict]:
        from openbb_fmp.utils.helpers import get_historical_ohlc   # lazy import
        ...   # returns list[dict], each with a `symbol` injected
```

- Implements **`aextract_data`** only → async wins per `Fetcher.__init_subclass__`. → [ADR-4](../../design/01-decisions.md#adr-4--fetcher-implements-either-sync-or-async-extract-never-forced)
- Note the **two `__alias_dict__` directions**: outbound on QueryParams, inbound on Data. → [Gotchas G3](../../design/04-gotchas.md#g3--__alias_dict__-mapped-the-wrong-direction)
- `transform_data` sorts, `model_validate`s, and raises `EmptyDataError` on empty.

---

## HTTP helpers — `utils/helpers.py`

| Function | Role |
|---|---|
| `create_url(version, endpoint, api_key, query, exclude)` | builds `financialmodelingprep.com/api/v{n}/...` |
| `get_data(url, **kwargs)` | wraps core `amake_request` |
| `get_data_urls` / `get_data_many` / `get_data_one` | concurrent / list / single helpers |
| `get_historical_ohlc(query, credentials, ...)` | per-symbol async fetch via `asyncio.gather` + `amake_request` |
| `response_callback(response, _)` | shared aiohttp callback; raises `UnauthorizedError`/`OpenBBError` on FMP errors |

All HTTP routes through the **core** `amake_request(s)`; the provider just wraps it. This is
the canonical async-REST shape other providers copy.

---

→ Contrast: [yfinance (sync/DataFrame)](./yfinance.md) · [fred (time-series)](./fred.md) · [fmp_cached (caching)](./fmp-cached.md)
→ Mechanics: [Provider Framework](../core/provider-framework.md) · Add one: [Recipes A](../../design/03-recipes.md#recipe-a--add-a-provider-integration-for-an-existing-standard-model)
