# MCP runtime profile manifests

The versioned source is
`openbb_mcp_server/assets/runtime_profiles.json`.

| Profile | Installation | App | Access |
| --- | --- | --- | --- |
| `platform-standard` | isolated `uv` | core OpenBB API | public/provider read |
| `portfolio-read` | `.venv_portfolio` | Portfolio custom composition | read/private read |
| `portfolio-ops` | `.venv_portfolio` | Portfolio custom composition | operator access |

Each manifest declares Python compatibility, required distributions and import
modules, checkout-relative source roots, optional analytics, app target, policy
profile, operator status and maintenance status. Missing required components,
source-origin mismatches and configuration conflicts are explicit resolution
evidence. Source checks use package metadata and module specifications without
importing the target package.

Operator access does not imply maintenance: all current manifests set
`maintenance_enabled=false`. A future task must add an explicit reviewed
maintenance selection before `OPENBB_MCP_ENABLE_MAINTENANCE_OPERATIONS=true`
can resolve ready.

`portfolio-read` and `portfolio-ops` require the fork packages and the explicit
`openbb_platform/extensions/portfolio/launch.py` composition. The isolated
standard profile does not silently inherit packages from `.venv_portfolio`.
Optional FinancialToolkit installation is reported separately and does not make
the base read profile unavailable.

The dual-MCP launcher resolves its isolated `uv` environment from checkout-local
editable packages, validates their import origins before startup, and writes
`runtime-resolution.json` beside its process logs. The artifact records package
versions, repository-relative origins, and policy-relevant effective settings
while replacing outside-checkout paths with `outside_repository`; it can
therefore be retained for replay without persisting machine-specific paths.
The verifier loads settings through the same file-then-environment precedence as
the server. Direct external dependencies are exact-pinned in the launcher.
Platform uses FastMCP 3.4.0 because its FastAPI constraint requires Starlette
below 1.0; Workspace uses FastMCP 3.4.6 and Starlette 1.6.0.
The launcher requires PowerShell 7 because its streamable-HTTP readiness probe
depends on modern `Invoke-WebRequest` behavior.

Portfolio profile provenance must use the checkout that owns
`.venv_portfolio` as `repository_root`. A feature worktree intentionally fails
that check when it reuses editable packages installed from the integration
checkout. Non-editable local copies also fail: these profiles require editable
origins so an outdated installed wheel cannot masquerade as current source.
