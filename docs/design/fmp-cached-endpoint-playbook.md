# FMP-cached endpoint playbook

**Audience:** contributors picking up wave-task issues (children of #1029–#1036).
**Wave 0 deliverable:** #1315
**Reference example:** `FMPCachedAnalystRecommendationsFetcher` (#1022 — shipped PR #1027)

This playbook walks through the two-provider unit of work end-to-end
using a single real endpoint as the working example. Read this
BEFORE opening your first wave-task PR.

## What a "wave task" ships

Every downstream wave-task issue delivers the same 5-piece unit:

1. **Raw live fetcher** in `openbb_fmp` — a class that hits FMP's HTTP
   endpoint directly, does the pydantic Query/Data models, and knows
   about plan-limit quirks (e.g. paid-tier 402 responses).
2. **Cached wrapper** in `openbb_fmp_cached` — a subclass of the live
   fetcher whose `aextract_data` reads MySQL first, falls back to the
   raw fetch, and writes results back.
3. **DDL + registration** — a `create_<name>_table()` in
   `openbb_fmp_cached/utils/cache_schema.py` plus a
   `fmp_cached_provider.fetcher_dict['<Name>'] = <FetcherClass>`
   entry in `openbb_fmp_cached/__init__.py`.
4. **Tests** — a structural (typed) test + an `@pytest.mark.record_http`
   integration test that replays from a checked-in VCR cassette.
5. **Cassette recording** — one committed YAML under
   `openbb_platform/providers/fmp_cached/tests/record/http/test_fmp_cached_fetchers/`.

## Before you start

1. **Check `_PLAN_LIMITED`** in `openbb_fmp_cached/utils/plan_limited.py`.
   If your endpoint is listed, cassette recording will 402 — file a
   plan-block follow-up instead of shipping a wrapper that can never be
   tested.
2. **Read the auto-generated two-provider coverage report** at
   `docs/reports/fmp-two-provider-coverage.md`. If your endpoint is
   listed under "openbb_fmp only" that's your target; if it's in
   "openbb_fmp_cached only" it's a native and you don't need a
   live fetcher.
3. **Skim the reference example**:
   - Live fetcher: N/A for `AnalystRecommendations` (native — no upstream
     wrap). See `openbb_fmp/models/equity_peers.py` for a live fetcher
     shape and `openbb_fmp_cached/models/equity_peers.py` for the
     cached-wrap shape.
   - Native example (no live fetcher): `openbb_fmp_cached/models/analyst_recommendations.py`.
   - DDL: `create_analyst_grades_table()` in `openbb_fmp_cached/utils/cache_schema.py`.
   - Test: `test_fmp_cached_analyst_recommendations_fetcher` in `tests/test_fmp_cached_fetchers.py`.
   - Cassette: `tests/record/http/test_fmp_cached_fetchers/test_fmp_cached_analyst_recommendations_fetcher_urllib3_v2.yaml`.
   - Unit tests: `tests/test_analyst_recommendations.py`.

## Step-by-step

### 1. Understand the FMP endpoint

Spike-fetch it once with your key to confirm the response shape:

```python
import httpx
from openbb_core.app.service.user_service import UserService

key = UserService().default_user_settings.credentials.fmp_api_key
if hasattr(key, "get_secret_value"):
    key = key.get_secret_value()
r = httpx.get(
    "https://financialmodelingprep.com/stable/<endpoint>",
    params={"symbol": "AAPL", "apikey": key},
    timeout=15,
)
print(r.status_code, r.json()[:2] if r.status_code == 200 else r.text[:200])
```

**402 response** → endpoint is plan-limited on our tier. Add an entry
to `_PLAN_LIMITED` (see `plan_limited.py` for the shape) and file a
follow-up; DO NOT ship a wrapper.

**404 with empty body** → FMP retired the endpoint. Look for a
replacement in the [FMP docs](https://site.financialmodelingprep.com/developer/docs).

### 2. Live fetcher in `openbb_fmp` (if not already there)

Follow the pattern in `openbb_fmp/models/equity_peers.py`:

```python
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.<name> import (
    <Name>Data, <Name>QueryParams,
)

class FMP<Name>QueryParams(<Name>QueryParams):
    """FMP-specific query params (usually just inherits + adds FMP quirks)."""

class FMP<Name>Data(<Name>Data):
    __alias_dict__ = {"our_field_name": "fmpRawFieldName"}

class FMP<Name>Fetcher(Fetcher[FMP<Name>QueryParams, list[FMP<Name>Data]]):
    @staticmethod
    def transform_query(params: dict): ...
    @staticmethod
    async def aextract_data(query, credentials, **kwargs): ...
    @staticmethod
    def transform_data(query, data, **kwargs): ...
```

Register it in `openbb_fmp/__init__.py`:

```python
fmp_provider = Provider(
    ...
    fetcher_dict={
        ...
        "<Name>": FMP<Name>Fetcher,
    },
)
```

### 3. Cached wrapper in `openbb_fmp_cached`

Follow the pattern in `openbb_fmp_cached/models/equity_peers.py`:

```python
from openbb_fmp.models.<name> import FMP<Name>Fetcher, FMP<Name>QueryParams
from openbb_fmp_cached.utils.cache_schema import create_<name>_table
from openbb_fmp_cached.utils.database import execute_query, execute_many, init_database

class FMPCached<Name>Fetcher(FMP<Name>Fetcher):
    @staticmethod
    async def aextract_data(query, credentials, **kwargs):
        try:
            init_database()
            create_<name>_table()
        except Exception as exc:
            logger.warning("<name> cache init failed: %s", exc)
            return await FMP<Name>Fetcher.aextract_data(query, credentials, **kwargs)
        cached = _get_cached(query)
        if cached:
            return cached
        fresh = await FMP<Name>Fetcher.aextract_data(query, credentials, **kwargs)
        if fresh:
            _store(query, fresh)
        return fresh
```

Register in `openbb_fmp_cached/__init__.py`:

```python
from openbb_fmp_cached.models.<name> import FMPCached<Name>Fetcher
...
fetcher_dict={
    ...
    "<Name>": FMPCached<Name>Fetcher,
}
```

### 4. DDL

Add a `create_<name>_table()` function in `openbb_fmp_cached/utils/cache_schema.py`.
Use `CREATE TABLE IF NOT EXISTS` + a UNIQUE index that matches the natural key
for the endpoint (e.g. `(symbol, date)` for time-series, `(symbol, period, date)`
for financials). Use `ON DUPLICATE KEY UPDATE` in your `_store` INSERT so
re-fetches upsert.

**Non-idempotent migrations** (e.g. backfills, column drops) use the
new `schema_version` machinery — see `openbb_fmp_cached/utils/database.py`:

```python
from openbb_fmp_cached.utils.database import migration_ran, record_migration

version = "W1-statements-add-ttm-tables"
if not migration_ran(version):
    # ... run the migration ...
    record_migration(version, notes="added ttm tables per #1029")
```

### 5. Tests

Two tests:

**Structural / unit** — mocks the HTTP call, exercises `transform_query`
+ `transform_data` in isolation. Fast, no cassette, deterministic.
Naming: `tests/test_<name>.py`.

**Fixture replay** — one `@pytest.mark.record_http` test that calls
`Fetcher.test(params, credentials)`. This replays the recorded cassette
in CI. Naming: `def test_fmp_cached_<snake_name>_fetcher(credentials=test_credentials):`
in `tests/test_fmp_cached_fetchers.py`.

### 6. Record the cassette

```bash
PYTHONIOENCODING=utf-8 .venv_win/Scripts/python.exe \
  scripts/pi_fmp_record.py --endpoint <snake_name>
```

The script clears any L2 cache rows that would short-circuit the HTTP
call, runs the fixture-recording test, and writes the YAML cassette.

**Common failure modes** (see #955 drain for the full list):

- Pydantic date coercion: `Fetcher.test` asserts `getattr(query, "start_date") == "2024-01-01"`; model coerces to `date`. Pass `date(2024, 1, 1)` in the test (or `datetime()` if model coerces to datetime). See `test_fmp_cached_equity_intraday_historical_fetcher` for the datetime variant.
- Missing cache-clear row: if the endpoint uses a dedicated L2 table (e.g. `etf_holdings`), add a `_CACHE_CLEAR_ROWS` entry in `pi_fmp_record.py` so pytest-recorder sees the HTTP call.

### 7. Coverage gate integration

Nothing to do — `test_fetcher_dict_coverage.py` picks up any newly-registered
fetcher automatically. If it fails with "no cassette", you skipped step 6.
If it fails with "in _KNOWN_UNCOVERED but cassette exists now", remove the
allowlist entry.

## Security

- FMP's API takes the key in the querystring. That means an httpx error
  message will embed `apikey=<value>`. Always use
  `openbb_fmp_cached.utils.security.raise_for_status_redacted` to scrub
  the URL from any HTTPError before it hits logs. See
  `AnalystRecommendations._fetch_grades_live` for the pattern.
- Never echo exception text into response bodies (widget layer). Log
  the detail via `logger.warning` and return a static message to the
  HTTP caller.

## PR checklist

- [ ] `openbb_fmp/models/<name>.py` — live fetcher (if not already there)
- [ ] `openbb_fmp_cached/models/<name>.py` — cached wrapper
- [ ] `openbb_fmp_cached/utils/cache_schema.py` — `create_<name>_table()`
- [ ] `openbb_fmp/__init__.py` and `openbb_fmp_cached/__init__.py` — registration
- [ ] `tests/test_<name>.py` — unit tests
- [ ] `tests/test_fmp_cached_fetchers.py` — one `@record_http` smoke test
- [ ] Cassette committed under `tests/record/http/test_fmp_cached_fetchers/`
- [ ] Coverage-gate test green (`test_fetcher_dict_coverage.py`)
- [ ] Two-provider report regenerated (`docs/reports/fmp-two-provider-coverage.md`)
- [ ] ruff + black + pylint clean on new files (10.00/10 target)
- [ ] `Closes #NNNN.` on its own line in PR body
