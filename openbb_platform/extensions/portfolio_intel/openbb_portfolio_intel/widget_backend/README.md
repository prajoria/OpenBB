# Portfolio-Intel Workspace backend (#1007)

Custom-backend widgets for [OpenBB Workspace](https://pro.openbb.co) that expose the `portfolio_intel` analytics modules as Workspace-consumable widgets.

Follows the canonical Workspace custom-backend contract documented in [OpenBB-finance/backends-for-openbb](https://github.com/OpenBB-finance/backends-for-openbb).

## Run locally

```bash
# From repo root, with .venv_portfolio activated:
.venv_portfolio/Scripts/python.exe -m uvicorn \
  openbb_portfolio_intel.widget_backend.main:app \
  --host 127.0.0.1 --port 6120 --reload
```

Confirm it's up:

```bash
curl http://127.0.0.1:6120/widgets.json
```

## Connect to Workspace

1. Open <https://pro.openbb.co>.
2. **Data connectors → Custom backend → Add**.
3. Name: `portfolio-intel`, URL: `http://127.0.0.1:6120`.
4. Save. Workspace fetches `/widgets.json` and adds the widgets under the **Portfolio Intelligence** category.
5. The pre-built **Portfolio Intelligence — Overview** app appears in your apps list (from `/apps.json`).

## Widgets shipped in this backend

| Widget id | Type | Endpoint | Wraps |
|---|---|---|---|
| `pi_xray_sector` | `chart` (raw records) | `/pi/xray/sector` | `analytics.xray` sector breakdown |
| `pi_whatif_diff` | `markdown` | `/pi/whatif` | `analytics.whatif` diff engine (#558) |
| `pi_brinson_attribution` | `chart` (raw records) | `/pi/attribution` | `analytics.attribution_engine` (#559) |

Each endpoint is a **thin adapter** over an existing analytics module. No new financial math lives in this backend — the shape is:

```
Widget → HTTP endpoint → analytics.<module> → JSON response
```

## Add a new widget

1. Add an entry to `widgets.json` (name, description, type, endpoint, gridData, params).
2. Add the FastAPI route to `main.py` returning data matching the declared `type`:
   - `markdown` → return a str.
   - `chart` with `raw: true` → return a list of dicts.
   - `chart` without `raw` → return a Plotly figure dict.
   - `table` → return a list of dicts.
   - `metric` → return `{"value": <scalar>, "delta": <scalar>, ...}`.
3. Reference the analytics module rather than reimplementing math.
4. Add a smoke test in `tests/unit/test_widget_backend.py` that hits the endpoint via `TestClient` and asserts the shape matches the widget type contract.

## CORS

Locked to `https://pro.openbb.co` on purpose. This backend is a Workspace data source, not a public API. If you're running a self-hosted Workspace, add its origin to `_ALLOWED_ORIGINS` in `main.py` — do NOT open to `"*"`.

## Authentication

`/pi/*` routes are gated by a bearer token. Policy is set at import time by two env vars:

| `PI_WIDGET_BACKEND_AUTH_MODE` | `PI_WIDGET_BACKEND_TOKEN` | Behavior |
|---|---|---|
| **`required`** (default) | set | Every `/pi/*` request needs `Authorization: Bearer <token>`. Compared constant-time via `hmac.compare_digest`. |
| `required` | unset | **Startup fails fast** with a clear error. This is by design — running the default mode without a token is a config bug. |
| `loopback-dev` | any | No auth. Operator explicitly opted out. Logs a WARN on startup. **Never bind off-host in this mode.** |
| anything else | any | Startup fails with `invalid auth mode`. Typos are loud, not silent auth-disables. |

The auth decision is made **only** from these env vars — never from `request.client.host`, `X-Forwarded-For`, or bind address. A proxy claiming loopback origin cannot bypass auth.

Discovery endpoints (`/widgets.json`, `/apps.json`, `/`) are unauthenticated by design — Workspace fetches them anonymously on connect. That's the contract, not an oversight.

### Running locally

```bash
# Dev (no auth, loopback only):
PI_WIDGET_BACKEND_AUTH_MODE=loopback-dev \
  .venv_portfolio/Scripts/python.exe -m uvicorn \
  openbb_portfolio_intel.widget_backend.main:app --port 6120

# Production shape (auth required):
export PI_WIDGET_BACKEND_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
.venv_portfolio/Scripts/python.exe -m uvicorn \
  openbb_portfolio_intel.widget_backend.main:app --port 6120
# Configure Workspace's custom-backend to send Authorization: Bearer $PI_WIDGET_BACKEND_TOKEN
```

Reverse-proxy the backend behind Cloudflare Access / Tailscale / IAP if it's reachable off-host. The bearer token is a floor, not a moat.

## Input validation

All user-supplied params are validated against strict allowlists before echoing into response bodies or engine kwargs:

- `symbol` / `benchmark_symbol` → `^[A-Z0-9.\-]{1,10}$` (ticker allowlist, covers `BRK.B`, `BF-A`, `AAPL`, etc.).
- `account_id` → `^[A-Za-z0-9_.\-]{1,64}$`.
- `window` → fixed enum `{1M, 3M, 6M, 1Y, YTD, MTD}`.
- `delta_shares` → parsed as int; bad input returns a generic markdown error that does NOT reflect the user value.

Reject-and-400 rather than silently coerce; the widget shows a Workspace-side error indicator rather than a corrupted render.

## Follow-ups tracked separately

- Account resolver — `xray_sector` currently returns demo data for any non-`demo` `account_id`; wire to `PositionStore` in a follow-up PR against the paper program.
- What-If full plumbing — `whatif` returns a stub; the structured diff (#558) needs a positions store + price fetcher wired in.
- Brinson live book — `attribution` uses a #935 golden fixture as the demo book; live wiring waits on the #543 index-constituent history feed.

## What this replaces

The `desktop/src/pi/` canvas from #981 / #982 / #1004 was a scope error — that shipped a bespoke React canvas which is NOT how Workspace consumes widgets. It stays in the tree as a **local preview harness** (headless smoke testing of the SDK contract), but the shipping surface for portfolio-intel widgets is THIS backend + Workspace as the frontend.
