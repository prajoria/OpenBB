# OpenBB Portfolio Windows Service Runbook

## Scope

`OpenBBPortfolio` is a .NET 10 Generic Host registered with the Windows
Service Control Manager. It supervises the durable jobs worker, Portfolio API,
and Portfolio Intelligence UX as separate child processes. All listeners bind
to loopback.

## Layout and security

| Location | Contents | Service access |
| --- | --- | --- |
| `C:\Program Files\OpenBB Portfolio\current` | Host, Python environment, application source | Read and execute |
| `C:\ProgramData\OpenBB Portfolio` | Configuration, secrets, logs, SQLite state | Modify |

The service runs as `NT SERVICE\OpenBBPortfolio`. SYSTEM and local
Administrators retain full control. Do not move provider credentials into the
application directory or pass them on command lines. The installer generates
`PI_WIDGET_BACKEND_TOKEN` only when `secrets.env` is absent and never prints
its value.

## Installation

1. Use a dedicated Windows host with .NET SDK 10 and supported CPython.
2. Clone or unpack the release source into an administrator-controlled staging
   directory.
3. Preview the install with `-WhatIf`.
4. Run `deploy\windows\install-openbb-service.ps1` elevated.
5. Reboot before interactive logon and run the acceptance command below.

The installer is idempotent. A missing or incomplete current release is
rebuilt in a staging directory before activation. Existing secrets are
preserved.

## Health and acceptance

```powershell
Get-Service OpenBBPortfolio
sc.exe qc OpenBBPortfolio
sc.exe qfailure OpenBBPortfolio
.\deploy\windows\Test-OpenBBService.ps1 `
  -EvidencePath C:\ProgramData\OpenBB-Verification\health.json
```

The harness verifies:

- automatic service startup under the virtual service account;
- service-host `doctor --json`;
- Portfolio Intelligence `/viewer` and `/widgets.json`;
- Portfolio API command coverage;
- authenticated jobs health and worker heartbeat.

On a disposable acceptance machine, run:

```powershell
.\deploy\windows\Test-OpenBBService.ps1 `
  -ExerciseScmRecovery -ExerciseRecovery -ExerciseCleanStop -Confirm:$false `
  -EvidencePath C:\ProgramData\OpenBB-Verification\acceptance.json
```

This exhausts the jobs-worker restart budget and verifies SCM replaces the
aggregate host, then terminates each child by exact PID and verifies an isolated
replacement. Finally, it stops the aggregate service, proves all captured
descendants exit, and restarts the service. Never run the destructive modes
during market-critical work.

## Upgrade and rollback

Run `update-openbb-service.ps1` elevated. It stages a complete release before
stopping service, preserves the exact prior configuration in memory, swaps
only application binaries, and requires `doctor` to pass. Any start or health
failure restores the prior release and configuration before restarting.

For an acceptance rollback test, copy the published artifact directory, remove
`OpenBB.ServiceHost.exe` or provide an invalid build, and verify the update
fails before activation. For a post-activation rollback test on a disposable
host, use a package with an intentionally failing health endpoint and confirm
the previous release returns healthy.

## Backup and restore

Stop the service before copying mutable state:

```powershell
Stop-Service OpenBBPortfolio
Copy-Item "C:\ProgramData\OpenBB Portfolio" D:\Backups\OpenBBPortfolio -Recurse
Start-Service OpenBBPortfolio
```

Restore into an empty ProgramData directory while the service is stopped.
Reapply ACLs by rerunning the installer, then start the service and run the
read-only acceptance harness. Backups contain credentials and portfolio state;
encrypt them and restrict operator access.

## Troubleshooting

1. Run the acceptance harness without destructive switches.
2. Check Windows Event Viewer for source `OpenBB Portfolio`.
3. Inspect component logs in ProgramData. Logs are UTF-8 JSON, redacted,
   bounded to 16 KiB per line, and retained for 14 days or 250 MiB per
   component.
4. Confirm ports 6902 and 6120 are not owned by another process:
   `Get-NetTCPConnection -LocalPort 6902,6120`.
5. Validate configuration without launching children:
   `OpenBB.ServiceHost.exe --validate-config --config <service.json>`.
6. If an update fails, retain the error output and verify the restored service
   with `doctor`; do not manually delete ProgramData.

Use `uninstall-openbb-service.ps1` for removal. ProgramData is retained unless
`-PurgeData` is explicitly supplied.
