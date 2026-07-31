# F12 Portfolio-management workflow — design spec

**Date:** 2026-07-31
**Epic:** #1634 Portfolio Intelligence Terminal
**Feature:** #1678 F12 Portfolio-management workflow
**Sub-tasks:** #1685 (T12.1), #1686 (T12.2), #1687 (T12.3), #1688 (T12.4), #1689 (T12.5)
**Approach:** C (hybrid — real for provider-health + tour manifest, stubs elsewhere, honest Playwright deferral)
**Follow-ups filed:** #1713 (Playwright), #1714 (basket input), #1715 (tier fallback)

---

## 1. Purpose

F12 is the **workflow layer** on top of the 11-tab terminal. The 11 tabs are a control
panel; F12 wires up the sequences a user actually executes against it. It's the
dashboard embodiment of the `notebooks/portfolio/` NB01→NB08 arc — a user who
has done the notebooks doesn't have to context-switch to the browser and hunt
across tabs; the tour tells them where to go next.

**What F12 is:** composition + guided navigation. Almost entirely REUSE.

**What F12 is not:** new analytics. Explicit PRD constraint: zero new engines.

---

## 2. Scope by sub-task

| Sub | Deliverable | Approach | Real vs stub |
|---|---|---|---|
| T12.1 #1685 | `pi_provider_health` widget (app chrome, all tabs) | REAL | Real per-tier pings, cached 60s, timeouts 2s |
| T12.2 #1686 | Morning Review one-pager tab | STUB (layout only, all REUSE) | Regression-lock test |
| T12.3 #1687 | `pi_basket_analyst_consensus` widget | STUB (demo consensus) | TODO cites #1714 |
| T12.4 #1688 | Sunday Routine `guidedTour` manifest in apps.json | REAL (data-only) | Loaded by Workspace tour renderer or diagnostic tests |
| T12.5 #1689 | Tour smoke test | pytest substitute + follow-up | TODO cites #1713 |

---

## 3. Sub-task designs

### T12.1 #1685 — `pi_provider_health` (REAL)

**Endpoint:** `GET /pi/health/providers`

**Response shape:**

```json
{
  "checked_at": "2026-07-31T13:45:00Z",
  "stale_since": null,
  "tracks": {
    "A": {
      "label": "Portfolio Intelligence (paid)",
      "tiers": [
        {"tier": 1, "name": "fmp_cached", "status": "healthy", "latency_ms": 42},
        {"tier": 2, "name": "fmp",        "status": "healthy", "latency_ms": 118},
        {"tier": 3, "name": "cboe",       "status": "degraded", "latency_ms": 1450, "note": "high_latency"},
        {"tier": 4, "name": "sec",        "status": "healthy", "latency_ms": 90},
        {"tier": 5, "name": "yfinance-snapshot", "status": "healthy", "latency_ms": 12, "note": "snapshot_age_2h"}
      ]
    },
    "B": {
      "label": "Techtrade (free)",
      "tiers": [
        {"tier": 1, "name": "cboe",     "status": "degraded", "latency_ms": 1450},
        {"tier": 2, "name": "sec",      "status": "healthy",  "latency_ms": 90},
        {"tier": 3, "name": "yfinance", "status": "healthy",  "latency_ms": 240}
      ]
    }
  }
}
```

**Widget type:** `markdown` (renders as a compact strip with color-coded badges per tier).

**Health check semantics:**

- `healthy`: HTTP 200 within 500ms
- `degraded`: HTTP 200 but latency > 500ms, OR HTTP 4xx (auth issues), OR snapshot age > 24h
- `down`: HTTP 5xx, timeout, network error
- `unknown`: no probe result yet (cold cache before first background probe completes)

**Startup + concurrency (P0-1 fix per code review):**

- **Endpoint returns immediately.** On cold cache, return the shape with every tier
  `status="unknown"` and a top-level `stale_since=null` — do NOT block on probes.
- **Probes run in a background task**, kicked off after the first request but not
  awaited by the response.
- **Probe fan-out uses `asyncio.gather(..., return_exceptions=True)` with a hard
  2.5s total wall clock.** Per-probe timeout is 2s; total budget is 2.5s so a
  single slow probe can't stall the fleet.
- Result: no request ever blocks Workspace connect on probe latency, worst case.

**Cache semantics (P0-2 fix per code review):**

- **60s TTL** in-memory cache of the last successful probe result
- **On refresh failure** (any exception during background probe fan-out): serve the
  stale cached result with a top-level `stale_since` timestamp set to the last
  successful probe time, and a top-level `note="probe_failed_serving_stale"`.
  **NEVER silently return the stale result as fresh.**
- **On cold cache + refresh failure:** return unknown tiers with `note="probe_failed_cold_cache"`.

**Exception → note mapping (P0-3 fix per code review):**

Explicit allowlist of exception classes → fixed human strings. **NEVER return
`str(exc)` or `repr(exc)` — they can carry API keys in URL fragments.**

```python
_EXC_NOTE_MAP = {
    "TimeoutError": "timeout",
    "ConnectError": "network_unreachable",
    "HTTPStatusError": "http_error",  # never include the URL
    "ReadTimeout": "read_timeout",
    "ConnectTimeout": "connect_timeout",
}
# default fallback: "probe_error" (never the exception message)
```

This is CI-enforceable — a small unit test asserts no code path returns a raw
exception string in any response field.

**Widget rendering:** two rows in the markdown body:

```
**Track A (paid):**  ● fmp_cached  ● fmp  ⚠ cboe (1450ms)  ● sec  ● yfinance-snap (2h)
**Track B (free):**  ⚠ cboe (1450ms)  ● sec  ● yfinance
```

**Chrome placement:** the widget goes into the `portfolio-intelligence-terminal` app's top-level `params` context and is added to **every tab** at position `(0, -1, w=40, h=1)` above the existing context bars. This is the "app chrome" the issue body specifies.

### T12.2 #1686 — Morning Review one-pager (STUB, layout only)

**New tab:** `"morning-review"` in the terminal app.

**Layout:**

```
| pi_book_context (all)                              |
| pi_provider_health (chrome)                        |
| pi_concentration_gauge | pi_risk_dashboard         |
| pi_paper_perf_kpis     | pi_event_calendar         |
| pi_alerts_panel                                    |
```

All 5 REUSE widgets, no new endpoints. Regression-lock test asserts every ID present.

**Tab position:** insert as a new "workflow" tab AFTER the existing 11 tabs
(so the terminal now has 12 tabs; F13 techtrade lives in a separate app already
so this doesn't collide with the tab-12 count for techtrade).

### T12.3 #1687 — `pi_basket_analyst_consensus` (STUB with clear TODO)

**Endpoint:** `GET /pi/equity/basket-analyst-consensus?basket_id=demo`

**Response shape (stub):**

```json
[
  {"symbol": "AAPL", "avg_target": 200.0, "buy": 24, "hold": 8,  "sell": 1, "consensus": "BUY"},
  {"symbol": "MSFT", "avg_target": 465.0, "buy": 28, "hold": 4,  "sell": 0, "consensus": "STRONG_BUY"},
  {"symbol": "GOOGL","avg_target": 210.0, "buy": 22, "hold": 10, "sell": 2, "consensus": "BUY"},
  {"symbol": "NVDA", "avg_target": 175.0, "buy": 32, "hold": 3,  "sell": 0, "consensus": "STRONG_BUY"},
  {"symbol": "META", "avg_target": 530.0, "buy": 26, "hold": 5,  "sell": 1, "consensus": "BUY"}
]
```

**Widget type:** `table`.

**Param:** `basket_id` — new `_BASKET_ID_RE` regex (P2-8 fix: semantically distinct
from `_ACCOUNT_ID_RE`, though the character class may end up identical).

**Non-demo basket_id handling (P1-7 fix per code review):**

- `basket_id=demo` returns the stub rows above (200)
- Any other allowlisted `basket_id` returns **HTTP 422** with body
  `{"detail": "basket_input_wiring_deferred", "follow_up": "#1714"}` —
  NEVER returns the demo rows with a marker note, because a caller ignoring
  the note gets bogus consensus for a real portfolio. Loud empty per R7.3.
- Malformed `basket_id` (fails regex) returns HTTP 400 as usual.

**TODO wired to #1714** for real basket-input design.

### T12.4 #1688 — Sunday Routine guided-tour manifest (REAL, data-only)

**Choice: Q1 (a)** — `guidedTour` key on the `portfolio-intelligence-terminal` app entry.

Schema (private convention; Workspace may or may not consume it — a follow-on
if not, but the data is the load-bearing part regardless):

```json
"guidedTour": {
  "id": "sunday-routine",
  "name": "Portfolio Sunday Routine",
  "description": "Steps the W0-W9 notebook-aligned portfolio review flow.",
  "steps": [
    {"step": "W0", "tab": "overview",       "focusWidget": "pi_provider_health",    "note": "Confirm provider tier health before the review starts."},
    {"step": "W1", "tab": "overview",       "focusWidget": "pi_equity_profile_header","note": "Ground yourself on a single symbol (NB01)."},
    {"step": "W2", "tab": "financials",     "focusWidget": "pi_equity_financial_charts","note": "Review the fundamentals (NB02)."},
    {"step": "W3", "tab": "xray",           "focusWidget": "pi_xray_sector",         "note": "Portfolio composition breakdown (NB03)."},
    {"step": "W4", "tab": "risk",           "focusWidget": "pi_risk_dashboard",      "note": "Risk metrics + Brinson attribution (NB03/NB05)."},
    {"step": "W5", "tab": "calendar",       "focusWidget": "pi_event_calendar",      "note": "Upcoming catalysts (NB04)."},
    {"step": "W6", "tab": "alerts",         "focusWidget": "pi_alerts_panel",        "note": "Active alerts and smart-money moves (NB04)."},
    {"step": "W7", "tab": "paper",          "focusWidget": "pi_paper_perf_kpis",     "note": "Paper account performance vs. plan (NB05)."},
    {"step": "W8", "tab": "morning-review", "focusWidget": "pi_alerts_panel",        "note": "One-page Morning Review composite (NB06/07)."},
    {"step": "W9", "tab": "estimates",      "focusWidget": "pi_basket_analyst_consensus","note": "Basket-consensus analyst view (NB08) — DEMO ONLY (basket input wiring is #1714)."}
  ]
}
```

**Why this shape:**

- `step` matches PRD W0-W9 naming
- `tab` is the tab_id from the existing app entry — Workspace already knows how to navigate to a tab
- `focusWidget` is the widget_id the tour should highlight at that step (Workspace can scroll/highlight if it supports it; otherwise it's diagnostic-only)
- `note` maps back to the notebook cell so a user reading the tour recognizes the workflow

### T12.5 #1689 — Tour smoke test (pytest substitute + #1713 follow-up)

**Substitute:** pytest test that:

1. Loads apps.json, finds the `guidedTour`
2. Asserts steps are ordered W0-W9
3. For each step, resolves `tab` against the app's `tabs` dict, `focusWidget` against `widgets.json`, and the tab's layout
4. Asserts every focusWidget is present on its tab's layout (blank-render class of defect — same class as #1633)
5. Asserts no step's tab is empty

**Real Playwright test:** tracked in #1713, cites this test as the substitute-to-replace.

---

## 4. Silent-failure guards (R7.3)

- **provider-health probe timeout:** returns `status=down` with `note="timeout"`, never a silent 200 with empty tiers
- **provider-health cache miss:** if the cache is empty and a probe raises, still return the shape with all tiers `status=unknown` and a top-level `note`
- **Morning Review empty layout:** the regression-lock test fails if any of the 5 required widgets is missing
- **Tour step points at unknown tab or widget:** the substitute smoke fails at PR time

---

## 5. Test discipline

Naming the specific mutations per R7.11 (P1-6 fix per code review — the
generic "I'll do the mutation check during implementation" is exactly the
ceremonial-test antipattern R7.11 warns about).

**T12.1 provider-health:**
- Contract test against a **recorded fixture** of a real fmp_cached response
  (per R7.1 realistic-shape fixtures) — one per (tier, status) combination
  is inadequate on its own; the fixture asserts the code parses a real shape,
  not a mock we hand-crafted to satisfy our own assumption. Fixture recorded
  into `tests/unit/fixtures/provider_health_probe_2026-07-31.json`.
- **Mutation 1:** drop the `latency_ms > 500` check → `test_degraded_over_500ms`
  fails because a slow response is reported as `healthy`.
- **Mutation 2:** remove the exception-note allowlist → `test_note_never_leaks_url`
  fails because raw exception `str()` gets into the response.
- **Mutation 3:** remove the `stale_since` field on cache-refresh failure →
  `test_stale_cache_marks_stale_since` fails because a stale result is served
  as fresh.

**T12.2 morning-review layout:**
- **Mutation:** drop `pi_provider_health` from the morning-review layout →
  `test_morning_review_contains_all_5_required` fails with the specific
  widget name in the message.

**T12.3 basket consensus:**
- **Mutation:** change the non-demo `basket_id` handler to return demo rows +
  a note → `test_non_demo_basket_id_returns_422` fails because it now sees
  200 with rows.
- Symbol allowlist test on the `basket_id` param family.

**T12.4 tour manifest:**
- **Mutation 1:** rename a tab in the tour manifest → `test_every_step_tab_exists`
  fails because the resolver returns None.
- **Mutation 2:** point a step at a widget id not in widgets.json →
  `test_every_step_focuswidget_exists` fails.
- **Mutation 3:** reorder steps to skip W7 → `test_steps_are_ordered_W0_to_W9`
  fails.

**T12.5 pytest substitute:**
- Not a mutation test — it's the substitute for the real Playwright follow-up
  (#1713). The test still validates the tour manifest can be executed
  headlessly and every step's tab has non-empty content.

**Reverse-verify discipline:** before the final commit, I revert each mutation,
re-run the test, and paste the mutation-fail evidence into
`.dev-cycle/verify-f12-mutations.log`.

---

## 6. Files this spec will create (implementation)

- `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/widgets_endpoints.py` — 2 new endpoints (`/pi/health/providers`, `/pi/equity/basket-analyst-consensus`)
- `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/widgets.json` — 2 new widgets (`pi_provider_health`, `pi_basket_analyst_consensus`)
- `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/apps.json` — new `morning-review` tab, `guidedTour` on the terminal app, `pi_provider_health` chrome row on every tab
- `openbb_platform/extensions/portfolio_intel/tests/unit/test_pi_terminal_f12.py` — new test file covering all 5 sub-tasks

---

## 7. Judgment calls I made without explicit user confirmation

These are noted so a reviewer can override before or after implementation:

1. **Q1 → (a)** guidedTour key on the terminal app entry, with a probe test
   (P1-4 fix per code review): before landing the guidedTour, add a pre-flight
   test that loads apps.json with an unknown key and asserts JSON is still
   valid. **Fallback if Workspace validates apps.json against a schema and
   rejects unknown keys:** move the manifest to a sidecar `tours.json` served
   from a new `/pi/tour/portfolio-sunday-routine` endpoint (Q1 (c) fallback).
   Decision point: implement Q1 (a) FIRST; if Workspace connect breaks in a
   /verify pass against a running Workspace, switch to (c) and file a note in
   this spec.
2. **Q2 → side-by-side tracks** in provider-health. Rationale: it's a small strip;
   showing both is honest; lets the user see when a Track B fallback would happen.
   Downside: takes more visual real estate than an auto-detect mode.
3. **Provider-health as app chrome placement (P1-5 fix per code review):** shown
   on every tab via a `y: -1` slot. **This is NOT verified in Workspace's layout
   engine.** Adopt the safe pattern FIRST: place at `y: 0` and shift every
   existing slot in every tab down by 2 units. This is a bigger apps.json diff
   but doesn't depend on an unverified layout convention. If a future Workspace
   docs check confirms `y: -1` is supported, we can consolidate back.
4. **12th tab for Morning Review:** the terminal grows from 11 to 12 tabs. Alternative
   was to make Morning Review a separate app; kept it in the terminal because the
   tour navigates *between* the existing tabs and Morning Review is the composed
   summary of them.

---

## 8. Explicitly out of scope (follow-ups filed)

- **#1713** Real Playwright + Workspace-in-CI (T0.6 / T12.5 gap)
- **#1714** Basket-mode input design (blocks real T12.3 wiring)
- **#1715** Real 5-tier chain fallback (blocks provider-health from operational status → operational routing)

Each TODO comment in code cites its follow-up ticket by number.

---

## 9. Verification plan

1. Full widget_backend test surface stays green after changes
2. New `test_pi_terminal_f12.py` — 15+ tests covering the sub-tasks
3. `.dev-cycle/verify-f12.log` capturing:
   - `GET /pi/health/providers` real output with tier statuses
   - `GET /pi/equity/basket-analyst-consensus?basket_id=demo` shape
   - Morning Review tab layout enumeration
   - guidedTour step-count + step resolution
4. Reverse-verify every load-bearing regression test per R7.11 (mutate → fail → restore)
