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

## Approved exclusions and unavailable products

The reviewed policy continues to deny or omit:

- broker/order execution and other execution mutations;
- raw Portfolio positions, allocation, cost basis, and tax summary operations;
- private core paper state from public profiles;
- success-shaped Intelligence stubs;
- arbitrary jobs, scripts, SQL, cache invalidation, and MCP job cancellation;
- caller-controlled document URL fetchers without complete SSRF hardening; and
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
