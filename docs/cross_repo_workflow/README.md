# Cross-repository MCP workflow

The Platform MCP server publishes the versioned
`resource://openbb/capabilities/v1` JSON resource as the single ownership and
connection view for OpenBB MCP capabilities. It distinguishes:

- the current Platform MCP session;
- the integrated Workspace endpoint at `http://127.0.0.1:8000/mcp`;
- the optional standalone Workspace sidecar at
  `http://127.0.0.1:8787/mcp`;
- the separate Agents stdio server; and
- the separate Daytrade stdio server.

Only the current Platform registration is reported as runtime-observed.
Workspace, Agents, and Daytrade remain `not_probed` until a client connects to
those separate sessions. Their presence in `.mcp.json.example` is a connection
example, not live-availability evidence.

## Documents

- [MCP capability coverage](./mcp-coverage-report.md) summarizes reviewed
  denominators, owners, verification scopes, and exclusions without presenting
  static configuration as live health.
- [Capability decisions and accountability](./mcp-capability-decisions.md)
  records policy ownership, exclusions, drift handling, and FMP Cached
  persistence decisions.
- [Portfolio MCP operator runbook](../operations/portfolio-mcp.md) covers clean
  profile setup, provenance, bridge activation, metadata-only readiness,
  maintenance, controlled restart, rollback, and troubleshooting.
- [Portfolio MCP parity release record](../operations/portfolio-mcp-release.md)
  records staged rollout, release/rollback lineage, final denominators,
  invocation evidence, exceptions, and remaining expansion work.
- [Cache-job operator runbook](../operations/mcp-cache-jobs.md) defines the
  allowlisted maintenance and durable recovery boundary.
- [MCP client examples](../../.mcp.json.example) provides credential-free
  connection templates for each owning surface and both Workspace deployment
  modes.

## Program plans and audit inventories (2026-10-03 snapshot)

These documents were written against audit baseline `39f17160`. Their counts
and issue states are a record of that audit, not current status; GitHub Issues
on Project #4 are the source of truth.

- [MCP capability-parity plan](../superpowers/plans/2026-10-03-portfolio-mcp-capability-parity.md)
  (program #2123) and
  [Notebook MCP Companion plan](../superpowers/plans/2026-10-03-notebook-mcp-agent.md)
  (program #2195), with its
  [design](../designs/notebook-mcp-agent-design.md) and
  [requirements](../Specs/notebook-mcp-agent/requirements.md).
- [Notebook story inventory](./notebook-mcp-story-inventory.csv) and
  [story coverage](./notebook-mcp-story-coverage.md) for the 25 portfolio
  notebook stories.
- [Repository inventory](./repository-inventory.md),
  [dependency architecture](./dependency-architecture.md),
  [development workflows](./development-workflows.md) and
  [submodule consolidation](./submodule-consolidation.md).
- [Project issue map](./project-issue-map.md)
  ([JSON](./project-issue-map.json)) linking plan IDs to issues.
- The audit's operation, FMP-model, catalog and commit snapshots are
  hash-pinned test fixtures under
  [`capability_audit/`](../../openbb_platform/extensions/mcp_server/tests/fixtures/capability_audit/).

The machine-readable catalog includes each capability's owning surface,
connection prerequisites, direct or indirect mapping, verification level,
verification scope, and current availability basis. Verification scopes are
unique so a capability is not counted again merely because another surface can
consume its output.
