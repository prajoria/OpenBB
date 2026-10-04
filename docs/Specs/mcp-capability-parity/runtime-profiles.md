# MCP runtime profile manifests

The versioned source is
`openbb_mcp_server/assets/runtime_profiles.json`.

| Profile | Installation | App | Access |
| --- | --- | --- | --- |
| `platform-standard` | isolated `uv` | core OpenBB API | public/provider read |
| `portfolio-read` | `.venv_portfolio` | Portfolio custom composition | read/private read |
| `portfolio-ops` | `.venv_portfolio` | Portfolio custom composition | operator access |

Each manifest declares Python compatibility, required distributions and import
modules, optional analytics, app target, policy profile, operator status and
maintenance status. Missing required components and configuration conflicts are
explicit resolution evidence.

Operator access does not imply maintenance: all current manifests set
`maintenance_enabled=false`. A future task must add an explicit reviewed
maintenance selection before `OPENBB_MCP_ENABLE_MAINTENANCE_OPERATIONS=true`
can resolve ready.

`portfolio-read` and `portfolio-ops` require the fork packages and the explicit
`openbb_platform/extensions/portfolio/launch.py:app` composition. The isolated
standard profile does not silently inherit packages from `.venv_portfolio`.
Optional FinancialToolkit installation is reported separately and does not make
the base read profile unavailable.
