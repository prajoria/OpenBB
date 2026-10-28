# MCP capability coverage

This report summarizes reviewed implementation coverage. It is not a live
health check. For a connected Platform session, read
`resource://openbb/capabilities/v1`; for deterministic offline evidence, run
`scripts/audit_mcp_capabilities.py --metadata-only`.

## Coverage rules

- A capability has one owning surface and one verification scope.
- A connection example does not prove a server is live.
- A source implementation is not MCP coverage until registration, policy,
  schema, privacy, and protocol evidence pass.
- A capability consumed by Workspace or an agent is not counted again as an
  independently implemented tool.
- `disabled`, `absent`, `not_evaluated`, and `not_probed` are not `available`.

## Reviewed surfaces

| Owning surface | Reviewed capability | Mapping | Verification | Live-state rule |
| --- | --- | --- | --- | --- |
| Platform | Reviewed OpenAPI provider/compute tools | Direct | Runtime registered/enabled inventory | Derived from the connected session |
| Platform | Portfolio and Intelligence adapters | Indirect to original handlers | Profile admission plus adapter tests | Available only when admitted and enabled |
| Platform | Cache observability (`cache_health`, `cache_coverage`) | Indirect sanitized adapter | Policy-owned members and tests | Portfolio profiles; database health is reported, not assumed |
| Platform | Five durable cache-job tools | Indirect guarded adapter | Policy-owned members and tests | `portfolio-ops`, effective auth, explicit maintenance opt-in |
| Platform | Notebook story catalog and run registry (five tools) | Direct story adapter | Policy-owned members and tests (#2216) | Portfolio profiles; runs scoped to the server's effective credential, version-checked JSON state |
| Platform | Basket look-through, sector view, concentration and construction (four `story_*` tools) | Direct story adapter over the notebook engine | Policy-owned members, engine, notebook-parity and adapter tests (#2313) | Portfolio profiles; bounded inputs, finite non-negative weights, provider failures are errors |
| Platform | Seven-phase single-name analysis (`story_single_name_analysis`) | Direct story adapter over `Analysis/stock_analysis` (loaded, not copied) | Policy-owned member, adapter and live smoke tests (#2314) | Portfolio profiles; strict JSON, bounded tables, two concurrent runs; 503 when `Analysis/` is absent |
| Platform | Brinson attribution, what-if diff and candidate trades (three `story_*` tools) | Direct story adapter over the Brinson oracle and the trade-preview engine | Policy-owned members, engine, notebook-parity and adapter tests (#2315) | Portfolio profiles; pure computation, finite bounded inputs, no guessed prices or renormalized weights |
| Platform | TechTrade story analytics (six `story_*` tools: market weather, 13F summary, actionable plans, round-trip P&L, replay, indicator config) | Direct story adapter over `openbb_techtrade.engine.story_analytics` | Policy-owned members, engine, notebook-parity and adapter tests (#2316) | Portfolio profiles; bounded finite inputs, provider failures are errors, replay capped at 25 |
| Platform | Run-scoped story artifacts (seven `story_artifact_*` tools: table, chart, report, workbook, TechTrade workbook, list, read) | Direct story adapter over the TechTrade export writer | Policy-owned members and adapter tests (#2217) | Portfolio profiles; server-issued IDs, atomic no-overwrite files without link escape, formula-safe cells, per-file and per-run limits, hash-verified reads, retention |
| Platform | Story jobs on the durable jobs service (four `story_job_*` tools; five allowlisted kinds: single-name, backtest, validate, tune, replay) | Direct story adapter that enqueues on the core `JobService`; the existing worker runs the kinds | Policy-owned members, adapter and live smoke tests (#2218) | Portfolio profiles; typed payloads, idempotent operation IDs, worker runs only recorded submissions, results as run artifacts, 4 active jobs per principal, tuning never persisted |
| Platform | Story paper sandboxes and the human approval gate (six `story_paper_*` tools; TechTrade paper engine) | Direct story adapter over `SqlitePaperEngine` | Policy-owned members, adapter and real-MCP profile tests (#2331) | Read and ops profiles create sandboxes, prepare and inspect; only portfolio-ops applies, and only with an HMAC approval a person grants outside the model; consumed once, deduplicated, no broker or live endpoint |
| Platform | TechTrade order batches and paper-sink artifacts (`story_paper_order_batch`, `story_paper_batch_artifacts`) | Direct story adapter over `OrderBatch` and `PaperOrderSink` | Policy-owned members and adapter tests (#2332) | Portfolio profiles; typed tickets and gates, engine's content SHA and checklist, Fidelity CSV and review workbook published as run artifacts; nothing submitted or approved |
| Workspace | Browser, dashboard, widget, app, backend, and agent control | Direct Workspace handlers | Source/protocol tests | Separate session; always `not_probed` from Platform |
| Agents | `get_positions`, `get_sector_exposure` | Direct explicit registry | Real stdio tests | Separate session; always `not_probed` from Platform |
| Daytrade | Six reviewed read-only market/session tools | Direct dispatch registry | Real stdio tests | Separate session; always `not_probed` from Platform |

Workspace has two deployment modes for the same capability surface:

- integrated backend: `http://127.0.0.1:8000/mcp`;
- optional standalone sidecar: `http://127.0.0.1:8787/mcp`.

They are alternative connections, not duplicate coverage.

## Portfolio profile denominator

The reviewed Portfolio program currently includes:

- 181/181 registered FMP Cached models routed;
- 123 dedicated/persistent and 58 explicitly non-persistent fallback
  registrations;
- 15 sanitized Portfolio direct reads and four permanently denied raw private
  operations;
- 60 reviewed Intelligence read-profile tools and one additional ops-only scan
  trigger;
- 67 conditional FinancialToolkit operations when both the extension and
  underlying package are installed;
- two sanitized cache-observability tools;
- five authenticated, explicitly enabled durable cache-job tools;
- two Agents tools;
- six Daytrade tools; and
- 42 bundled prompts with structured readiness dependencies.

These denominators have different owners and verification scopes. They must not
be summed as interchangeable tools or used to infer that optional packages,
providers, databases, workers, browser sessions, or separate MCP processes are
currently available.

The program metrics (model reachability, persistence, disposition, invocation,
and prompt-dependency coverage), the acceptance-criteria status, and the
rollback proof for this release are in the
[parity release record](../operations/portfolio-mcp-release.md).

## Approved exclusions and unavailable products

The reviewed policy continues to deny or omit:

- broker/order execution and other execution mutations;
- raw Portfolio positions, allocation, cost basis, and tax summary operations;
- private core paper state from public profiles;
- success-shaped Intelligence stubs;
- arbitrary jobs, scripts, SQL, cache invalidation, and MCP job cancellation;
- caller-controlled document URL fetchers that lack SSRF hardening (the
  hardened SEC, Congress, and weather-bulletin fetchers are admitted since
  #2290); and
- agent products that are documented as absent rather than synthesized from
  unrelated tools.

Consult
[capability decisions](./mcp-capability-decisions.md) for ownership, rationale,
source evidence, and review triggers.

## Reproducing metadata-only coverage

From a clean Portfolio checkout with its owning Python environment:

```powershell
$AuditDir = Join-Path ([System.IO.Path]::GetTempPath()) "openbb-mcp-audit"
& $env:OPENBB_PORTFOLIO_PYTHON .\scripts\audit_mcp_capabilities.py `
    --profile portfolio-read `
    --output-dir $AuditDir `
    --metadata-only
```

This path does not call data providers, personal portfolio services, browser
bridges, cache tables, or MCP transports. Review `scope_limitations`,
`unavailable_components`, collisions, and lineage state rather than treating a
successful export as live readiness.

For setup, restart, rollback, and troubleshooting, use the
[Portfolio MCP operator runbook](../operations/portfolio-mcp.md).
