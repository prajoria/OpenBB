---
name: openbb-workspace-local-server
description: Use whenever a user mentions setting up, starting, stopping, checking status, verifying, replaying, recovering, or locally hosting OpenBB Workspace or BQ Workspace, including vague requests such as "run Workspace locally" or "is my Workspace up?" Do not wait for the user to name this skill.
compatibility: Windows 11, PowerShell 7, Docker Desktop Linux engine, Git, and Bun.
---

# OpenBB Workspace Local Server

## Core rule

Treat the checked-in PowerShell scripts as the only operational interface.
Choose and invoke them; do not reconstruct their Docker, Bun, environment,
credential, health, or process-management internals. A run is successful only
after `test_self_hosted_workspace.ps1` passes.

Run from the repository root:

| Script | Contract |
| --- | --- |
| `.\scripts\setup_self_hosted_workspace.ps1` | Validate prerequisites and generate ignored local state. |
| `.\scripts\run_self_hosted_workspace.ps1` | Start the owned backend and frontend. |
| `.\scripts\test_self_hosted_workspace.ps1` | Read-only authoritative verification. |
| `.\scripts\stop_self_hosted_workspace.ps1` | Stop only script-owned processes and Compose project. |

## Select the state-aware flow

- **First setup / fresh replay:** setup → run → test.
- **Setup complete, currently stopped:** run → test.
- **Status or verify only:** test. Do not start or stop anything.
- **Already running:** test only. Do not rerun setup or run.
- **Safe stop:** stop. Report stopped, not verified healthy.
- **Missing setup:** if run/test reports setup incomplete, run setup → run → test.
- **Docker stopped:** report the sanitized script failure and ask the operator to
  start Docker Desktop's Linux engine. Then setup → run → test.
- **Stale PID state:** when run reports existing/stale PID state, stop → run → test.
- **Health failure:** stop → run → test once. If a checked-in script still fails,
  perform only focused diagnosis of that failure and report the sanitized result.
- **Browser validation blocked:** keep script verification and browser validation
  distinct. Report the verifier result plus the browser blocker; never downgrade a
  failed verifier or claim browser success.

Setup rotates managed local credentials. Do not run setup merely to check status
or restart a healthy deployment.

## Hard boundaries

Never:

- write or edit `.env`, Compose override, credential, secret, PID, or runtime files;
- run raw `docker compose`, `bun`, ad-hoc environment, or process-start commands;
- kill processes by name or use broad termination;
- print credentials, tokens, environment contents, response bodies, or log bodies;
- edit anything under `third_party/workspace`;
- claim success based on a port, container list, browser page, or launcher alone;
- substitute manual commands when an authoritative script exists.

Raw commands are allowed only after a checked-in script has failed, and only to
diagnose that exact failure. Keep diagnosis read-only, narrow, and sanitized.
Return to the authoritative script for the final result.

## Output contract

Use this concise shape:

```text
Status: HEALTHY | STOPPED | BLOCKED | FAILED
Scripts: setup=<result>; run=<result>; test=<result>; stop=<result>
Endpoint: http://127.0.0.1:1420 (only when verified)
Next: <one focused operator action, or "none">
```

Omit scripts not used. Never include response bodies, credentials, or secret
values. A browser blocker belongs in `Next`.

## References

- [Operator runbook](../../../docs/operations/workspace-local-development.md)
- [Implementation report](../../../docs/operations/workspace-self-hosted-implementation-report.md)
