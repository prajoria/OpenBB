# Portfolio Intelligence Engine — Release Notes (pi-rc-1)

**Release cut:** 2026-07-21
**Branch:** `portfolio` (fork of `develop`)
**Tracking:** [Project #4 — Portfolio Intelligence Engine](https://github.com/users/prajoria/projects/4)
**Meta issue:** #491

The Portfolio Intelligence Engine is a comprehensive personal-portfolio decision surface built on top of the OpenBB Platform. This release ships the first end-to-end vertical: from the paper-trading ledger through analytics (X-Ray, What-If, Brinson attribution, risk, alerts) into OpenBB Workspace via a compliant custom-backend widget suite.

## Shipped in this release

### Analytics (Python, all portfolio-scoped)

- **What-If diff engine** (#558) — Stateless engine composing X-Ray + risk substrate; 3 silent-failure guards (partial-book variance, NaN in cov/returns/benchmark, NaN/Inf prices), all reverse-verified per R7.11.
- **Corporate-action reconciler** (#554) — Pure-function reconciler intersecting held positions with dividend/split calendar rows; idempotent via deterministic entry_id from SHA1(event_type:symbol:ex_date); loud-empty guard on `(positions ≠ ∅, calendar rows ≠ ∅, intersection = ∅)`.
- **Brinson-Fachler synthetic test-data generator + oracle + 7 golden fixtures** (#935) — Dirichlet-drawn weights that sum to 1 by construction; oracle is a literal transcription of BF formulas; fixtures cover all §4.2 edge cases from the spec.
- **Brinson-Fachler attribution engine** (#559) — Pure function matching all 7 golden fixtures + 2 externally-cited references to ±1bp per effect; per-group AttributionRow output for the waterfall widget.
- **Brinson external reference fixtures** (#557) — Textbook (Brinson-Fachler 1985; Brinson-Hood-Beebower 1986) + Bloomberg PLACEHOLDER first-class QA hand-off point.

### Widget backend (FastAPI, OpenBB Workspace compliant)

Ships as `openbb_portfolio_intel.widget_backend`. Serves `widgets.json` + `apps.json` + 26 widget endpoints. Follows the canonical [OpenBB-finance/backends-for-openbb](https://github.com/OpenBB-finance/backends-for-openbb) contract.

- **Auth**: bearer token via `PI_WIDGET_BACKEND_TOKEN`, or explicit `PI_WIDGET_BACKEND_AUTH_MODE=loopback-dev` opt-out. Fail-fast startup, `hmac.compare_digest`, no spoofable client-host bypass.
- **CORS**: locked to `https://pro.openbb.co`; wildcard rejected in tests.
- **Input validation**: strict allowlists (`^[A-Z0-9.\-]{1,10}$` for tickers, `^[A-Za-z0-9_.\-]{1,64}$` for account IDs, enum for windows).
- **Loud empties**: demo path returns real-shaped rows; unwired paths return marker rows explaining the gap.

**26 shipped widgets**:

| Category | Widgets |
|---|---|
| X-Ray (#529, #530) | Sector pie, Country pie, Look-Through Top-25 table, Concentration gauge |
| Events (#531) | Event Calendar table |
| Smart-Money (#532) | Ribbon table |
| Risk (#533) | Dashboard metric grid, Rolling volatility chart |
| Paper Trading (#549, #550, #551, #555) | Order ticket (2-step), Blotter, Performance equity curve, KPIs |
| What-If (#558, #552) | Markdown summary, Structured diff card |
| Attribution (#559, #553) | Brinson waterfall chart |
| Alerts & Sentiment (#575, #576) | News, Sentiment gauge, Alerts panel |
| Backtest (#577) | One-click backtest button |
| Equity Profile (#781, #990-#996) | Header, Key stats, Financial charts, Technicals+pivots, Analyst forecasts, ETF/bond ladder, Competitor strip |

### Data-layer

- **Equity Profile Dashboard PRD + data-coverage audit** (#781) — Every field in every section mapped to `(provider, endpoint, field_name)`; 53 direct-covered, 16 derived, 2 fmp_cached sub-gaps (#997, #998), 2 hard provider gaps (#999 options IV, #1000 corporate bonds).
- **P0 EtfHoldings model** (#542 — prior release cycle; consumed by §6 ETF exposure widget).

### Infrastructure & tooling

- **Coordination policy** — GitHub Issues as sole tracker (bd retired), heartbeats every ≤10 min on claimed work, 2h stale = reclaimable with audit comment. Documented in `CLAUDE.md`.
- **Portfolio-branch CI** — `pi-desktop-frontend` workflow gates PRs touching `desktop/` on lint + typecheck + vitest. (Note: widget host in `desktop/src/pi/` from #981/#982 was a scope error — retained as a headless local preview harness only; the shipping surface is Workspace consuming the FastAPI backend above.)
- **Closes-syntax linter** — checks every PR body for one-clause-per-line `Closes #NN.` grammar (rejected inline mixed clauses like `Closes #NN. Refs #MM.`).

## Deferred / blocked (out of this release)

Tracked and drainable in follow-up cycles:

- **Bloomberg-sourced Brinson fixtures** (#557 companion) — Placeholder JSON committed; QA fills post-release with Terminal access.
- **fmp_cached fixture coverage — 65 uncovered endpoints** (#955) — Cross-team; portfolio team does not PR to `providers/fmp_cached/`.
- **fmp_cached sub-gaps** (#997 rating-split, #998 historical revenue estimate) — Cross-team.
- **Provider gaps** (#999 options chain + ATM IV term structure, #1000 corporate bond issuance + YTM) — Require external provider integration; not blocking Workspace launch of the widgets that use them, which display BLOCKED marker rows documenting the gap.
- **Nightly CI green ×3 consecutive nights** (#565) — Time-based gate.
- **Recorded demos** (#534, #556, #569) — Human production step.
- **Upstream promotion PR** (#568) — Per user's explicit standing rule: portfolio → develop only opens on unambiguous user sign-off; never automated.

## Test coverage

- **Analytics**: 82 unit tests across reconciler (13), Brinson oracle/generator (29), attribution engine (25), external fixtures (5), plus preexisting What-If (10).
- **Widget backend**: 150 unit tests covering manifest schema, manifest ↔ FastAPI route parity, CORS, auth (loopback-dev + required modes, hmac compare, startup fail-fast), input allowlists, per-endpoint shape contracts, and per-endpoint rejection of bad account_id/symbol.
- **All load-bearing tests R7.11-verified**: mutating the production code causes the test to fail; restoring makes it green.

## API examples

### Local development

```bash
# Install portfolio_intel + deps in .venv_portfolio
python -m venv .venv_portfolio
.venv_portfolio/Scripts/python.exe -m pip install \
  -e openbb_platform/core \
  -e openbb_platform/extensions/backtest \
  -e openbb_platform/extensions/portfolio_intel

# Run the widget backend (dev, no auth)
PI_WIDGET_BACKEND_AUTH_MODE=loopback-dev \
  .venv_portfolio/Scripts/python.exe -m uvicorn \
  openbb_portfolio_intel.widget_backend.main:app --port 6120

# Point OpenBB Workspace at http://localhost:6120
# (Data connectors → Custom backend → Add)
```

### Python analytics example

```python
from openbb_portfolio_intel.analytics.brinson import brinson_reference, make_case
from openbb_portfolio_intel.analytics.attribution_engine import build_from_dataframe

# Generate a deterministic BF test case
case = make_case(n_groups=5, seed=42)

# Trusted oracle
effects = brinson_reference(case.df)
print(f"Total active return: {effects.active_return:.4f}")
print(f"Allocation: {effects.allocation:.4f}")
print(f"Selection:  {effects.selection:.4f}")

# Attribution waterfall
waterfall = build_from_dataframe(case.df, window="1Y", benchmark_symbol="SPY")
for row in waterfall.rows:
    print(row.sector, row.allocation, row.selection)
```

### What-If analytics example

```python
from openbb_portfolio_intel.analytics.whatif import diff

# Preview a hypothetical trade impact against your paper book
result = diff(symbol="AAPL", delta_shares=100, positions=..., prices=...)
print(result.metrics)  # dict of before/after/delta per metric
```

## Migration notes for next cycle

None. This is the first `pi-rc-1` cut. Follow-up releases will target:

1. Wire analytics modules into widget adapters (each currently returns demo data on the `account_id="demo"` path).
2. Land upstream provider gaps (#999, #1000) so the BLOCKED marker rows can be replaced with real data.
3. Close remaining Cross-team `fmp_cached` gaps (#997, #998, #955).
4. Cut demos (#534, #556, #569) + gate reviews (#499) once a live paper book is loaded.
5. Then, only on explicit user sign-off, open the `portfolio` → `develop` upstream promotion PR (#568).

## Contributors

- Portfolio team (this release) — Daisy + Claude (openbb-dev-cycle loop).
- Cross-team dependencies acknowledged: `fmp_cached` team (schema owner for #997, #998, #955); Options + Bonds provider work (to be filed once #999, #1000 are picked up).

## Closes

Closes #566.
