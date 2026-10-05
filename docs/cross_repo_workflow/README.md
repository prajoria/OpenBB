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
- [Cache-job operator runbook](../operations/mcp-cache-jobs.md) defines the
  allowlisted maintenance and durable recovery boundary.
- [MCP client examples](../../.mcp.json.example) provides credential-free
  connection templates for each owning surface and both Workspace deployment
  modes.

The machine-readable catalog includes each capability's owning surface,
connection prerequisites, direct or indirect mapping, verification level,
verification scope, and current availability basis. Verification scopes are
unique so a capability is not counted again merely because another surface can
consume its output.
