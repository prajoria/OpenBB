# Recipe 05 — Programmatic REST via curl (non-Python consumers)

**Goal**: Call `/api/v1/pine/run_byo` from a non-Python client (bash + curl + jq). Any language with an HTTP client can consume the pine extension the same way — the OpenBB Platform serves it as a standard REST endpoint.

**Prerequisites**:
1. `pip install openbb-extension-pine`
2. Start the OpenBB API server: `python -m openbb_core.api.rest_api`. Default binds `http://localhost:6900/api/v1/`.

## The request

Save your Pine source to `bb.pine`, then:

```bash
curl -s -X POST http://localhost:6900/api/v1/pine/run_byo \
  -H "Content-Type: application/json" \
  -d '{
    "source": "//@version=6\nindicator(\"BB\", overlay=true)\nplot(ta.sma(close, 5), title=\"sma\")\n",
    "records": [
      {"date": "2024-01-02T00:00:00Z", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000000},
      {"date": "2024-01-03T00:00:00Z", "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 1000000},
      {"date": "2024-01-04T00:00:00Z", "open": 102.0, "high": 103.0, "low": 101.0, "close": 102.5, "volume": 1000000},
      {"date": "2024-01-05T00:00:00Z", "open": 103.0, "high": 104.0, "low": 102.0, "close": 103.5, "volume": 1000000},
      {"date": "2024-01-08T00:00:00Z", "open": 104.0, "high": 105.0, "low": 103.0, "close": 104.5, "volume": 1000000},
      {"date": "2024-01-09T00:00:00Z", "open": 105.0, "high": 106.0, "low": 104.0, "close": 105.5, "volume": 1000000},
      {"date": "2024-01-10T00:00:00Z", "open": 106.0, "high": 107.0, "low": 105.0, "close": 106.5, "volume": 1000000}
    ],
    "symbol": "SMOKE"
  }' | jq .
```

## Expected response (truncated)

```json
{
  "results": [
    {"date": "2024-01-08T00:00:00+00:00", "sma": 102.5}
  ],
  "warnings": [],
  "chart": null,
  "extra": {
    "alerts": [],
    "orders": [],
    "attribution": "Powered by PyneSys (https://pynesys.io)",
    "compile_cache_hit": false,
    "exec_ms": 41,
    "provider_used": "byo",
    "bars_consumed": 7,
    "metadata": {
      "route": "/pine/run_byo",
      "timestamp": "2026-07-01T22:39:04.393146",
      "duration": 966580300
    }
  }
}
```

## Error responses

The middleware serializes every `PineError` subclass into a structured JSON envelope. Example — non-FMP provider request via `POST /api/v1/pine/run`:

```json
{
  "detail": {
    "code": "PineProviderError",
    "message": "Provider 'yahoo' is not supported (supported: ['fmp', 'fmp_cached'])",
    "requested": "yahoo",
    "supported": ["fmp", "fmp_cached"],
    "tracking_url": "https://github.com/prajoria/OpenBB/issues?q=is%3Aissue+label%3Aproject%3Apine+multi-provider"
  }
}
```

The `code` field is stable across releases — safe to switch on in your caller. The `tracking_url` field, when present, points at the exact GitHub-issue filter for filing the missing capability.

## Notes

- The OpenAPI schema at `http://localhost:6900/openapi.json` documents every pine endpoint including request/response shapes. Import it into Postman, Insomnia, or your OpenAPI client of choice.
- All authentication + rate-limiting configured for the host OpenBB API server applies to pine endpoints too — you don't have to configure pine separately.
- For programmatic Python callers, prefer `obb.pine.run_byo(...)` (Python) over the REST endpoint (HTTP) — same code path, less serialization overhead.

Powered by PyneSys (https://pynesys.io)
