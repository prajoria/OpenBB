# 09 — API / Router Surface

**GitHub:** [#46](https://github.com/prajoria/OpenBB/issues/46) · **Depends on:** [#41](https://github.com/prajoria/OpenBB/issues/41), [#42](https://github.com/prajoria/OpenBB/issues/42), [#44](https://github.com/prajoria/OpenBB/issues/44), [#45](https://github.com/prajoria/OpenBB/issues/45), [#47](https://github.com/prajoria/OpenBB/issues/47)
**Beads:** OpenBB-2gu, OpenBB-z1f

The public face: the `obb.backtest.*` namespace exposed through the standard OpenBB router, so
every capability is reachable from Python, the REST API, and OpenAPI/MCP automatically.

---

## 1. Command surface

`router.py` defines a `Router` with these commands (all return `OBBject[...]`):

| Command | Returns | Backed by |
|---|---|---|
| `obb.backtest.run` | `BacktestResult` | engine (component 04/05) |
| `obb.backtest.sweep` | `SweepResult` | vectorized sweep (component 04) |
| `obb.backtest.pipeline` | `FactorPanel` | Pipeline (component 05) |
| `obb.backtest.factor_eval` | `FactorReport` | alphalens (component 05/07) |
| `obb.backtest.tearsheet` | `TearSheet` | analytics (component 07) |
| `obb.backtest.validate` | `ValidationReport` | validation (component 08) |
| `obb.backtest.reconcile` | `ReconciliationReport` | engine parity gate (component 04) |
| `obb.backtest.bundle.ingest` | `BundleInfo` | data bundle (component 03) |
| `obb.backtest.bundle.list` | `list[BundleInfo]` | bundle registry |

```python
@router.command(model="Backtest")
def run(strategy: str | Strategy, config: BacktestConfig,
        engine: Literal["auto", "vector", "event"] = "auto") -> OBBject[BacktestResult]:
    ...
```

- **Engine selection:** `engine="auto"` picks vectorized for parameter sweeps / simple
  signal strategies and event-driven for path-dependent / Pipeline strategies; explicit
  `vector`/`event` (and optional adapter names from component 11) override.
- **Standardization:** dates, symbols, frequency, calendar follow OpenBB query-param
  conventions so the commands feel native alongside `obb.equity.*`.
- Every command carries an `examples=[...]` block and full docstrings → OpenAPI + MCP tool
  schemas are generated automatically.

---

## 2. Async, long-running execution & plumbing

- Commands are defined `async` where the work is long (full backtests, sweeps, validation);
  the REST layer streams/polls per OpenBB's existing async command support, so a multi-minute
  CPCV run does not block the event loop.
- **Provider/credential plumbing:** the router resolves `fmp_cached` MySQL config and FMP
  credentials through the standard OpenBB provider/credentials interface (reuses component 01
  config), never reading secrets directly.
- **Privacy boundary:** outward responses contain normalized returns/metrics only; raw
  positions/lot data never cross the router (fork privacy rule).
- Errors surface as standard `OpenBBError` subclasses (e.g. `OptionalDependencyError` from
  component 11) with actionable messages.

---

## 3. Registration

- `router` is exported via the `openbb_core_extension` entry point (component 01); after
  `dev_install.py -e` + `openbb.build()` the `obb.backtest` namespace appears on the `obb` object
  and in the REST app with no extra wiring.

---

## Acceptance mapping (#46)

| Acceptance criterion | Satisfied by |
|---|---|
| Command list / namespace | §1 table |
| Parameter standardization | §1 |
| Engine selection | §1 (`engine` arg + auto policy) |
| Async/long-running support | §2 |
| OpenAPI/MCP exposure | §1 (examples/docstrings) + §3 |
| Credential/provider plumbing | §2 |
