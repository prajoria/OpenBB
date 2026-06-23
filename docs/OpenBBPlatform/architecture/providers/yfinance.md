# yfinance — Yahoo Finance (free, sync, DataFrame-backed)

[← providers/ architecture](./README.md) · Design: [providers/ design](../../design/providers/README.md) · [GLOSSARY](../../GLOSSARY.md)

> The reference for a **keyless, synchronous, library-backed** provider that returns pandas.
> Source: `providers/yfinance/openbb_yfinance/`. Last verified: 2026-06-02.

---

## Quick-ref card

| Field | Value |
|---|---|
| **Provider id** | `yfinance` |
| **Credential** | **none** (keyless — no `credentials=` kwarg) |
| **repr_name** | `Yahoo Finance` |
| **Extract style** | **sync** (`extract_data`) |
| **Raw extract type** | pandas `DataFrame` |
| **HTTP layer** | `yfinance` lib + `curl_adapter.CurlCffiAdapter` (NOT core `amake_request`) |
| **Fetchers** | ~28 in `fetcher_dict` |
| **Notable** | `PrivateAttr` query knobs; set `require_credentials=False` not needed (no creds) |

→ Symbol: `openbb_yfinance/__init__.py::yfinance_provider`

---

## Provider manifest

```python
yfinance_provider = Provider(
    name="yfinance",
    website="https://finance.yahoo.com",
    repr_name="Yahoo Finance",
    # no credentials= → keyless
    fetcher_dict={ "EquityHistorical": YFinanceEquityHistoricalFetcher, ... },  # ~28
)
```

Because no credentials are declared, `QueryExecutor.filter_credentials` finds nothing to
validate — the command runs with no key. → [ADR-6](../../design/01-decisions.md#adr-6--late-credential-validation-with-secretstr)

---

## Representative model — `models/equity_historical.py`

```python
class YFinanceEquityHistoricalQueryParams(EquityHistoricalQueryParams):
    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}
    interval: ...
    extended_hours: bool
    include_actions: bool
    adjustment: ...
    # internal knobs not exposed to consumers — PrivateAttr:
    _period: ... = PrivateAttr(default="max")
    _ignore_tz = PrivateAttr(...)
    _progress = PrivateAttr(...)
    _keepna = PrivateAttr(...)
    _rounding = PrivateAttr(...)
    _repair = PrivateAttr(...)
    _group_by = PrivateAttr(...)

class YFinanceEquityHistoricalData(EquityHistoricalData):
    __alias_dict__ = {"split_ratio": "stock_splits", "dividend": "dividends"}
    split_ratio: Optional[float]
    dividend: Optional[float]

class YFinanceEquityHistoricalFetcher(Fetcher[...]):
    @staticmethod
    def extract_data(query, credentials, **kwargs) -> "DataFrame":   # SYNC
        from openbb_yfinance.utils.helpers import yf_download         # lazy import
        ...   # returns a pandas DataFrame

    @staticmethod
    def transform_data(query, data, **kwargs) -> list[...Data]:
        return [...model_validate(d) for d in data.to_dict("records")]
```

- Implements **`extract_data` (sync)** — yfinance is a blocking library, so async would add
  no benefit. The engine handles sync uniformly via `maybe_coroutine`. → [ADR-4](../../design/01-decisions.md#adr-4--fetcher-implements-either-sync-or-async-extract-never-forced)
- **`PrivateAttr`** carries internal tuning that should not appear in the public signature —
  a pattern for "engine-only" knobs.
- Raw return is a **`DataFrame`**; `transform_data` converts via `to_dict("records")` before
  validation (extract still returns raw, not `Data`). → [Gotchas G6](../../design/04-gotchas.md#g6--returning-data-from-extract_data)

---

## Helpers — `utils/helpers.py`

| Function | Role |
|---|---|
| `yf_download(...)` | core OHLC fetch; lazy-imports `yfinance`, uses `get_requests_session()` + `CurlCffiAdapter`, returns a normalized DataFrame |
| `get_custom_screener` / `get_defined_screener` | Yahoo screener via `yfinance.data.YfData` / `yf.screen` |
| `get_futures_*` | futures curve/quotes (reads bundled `futures.csv`) |
| `df_transform_numbers` | DataFrame numeric-suffix normalizer |

HTTP is entirely inside the `yfinance` library path — this provider does **not** use the
core `amake_request`. That's the key contrast with [fmp](./fmp.md) and [fred](./fred.md).

---

→ Contrast: [fmp (async REST)](./fmp.md) · [fred (time-series)](./fred.md)
→ Mechanics: [Provider Framework](../core/provider-framework.md) · Add one: [Recipes A](../../design/03-recipes.md#recipe-a--add-a-provider-integration-for-an-existing-standard-model)
