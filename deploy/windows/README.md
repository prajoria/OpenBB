# OpenBB Portfolio Windows Service

These scripts install and operate the `OpenBBPortfolio` Windows Service. Run
them from an elevated PowerShell session on a dedicated Windows host.

## Install

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy\windows\install-openbb-service.ps1 `
  -SourceRoot (Resolve-Path .) `
  -PythonExecutable "C:\Python312\python.exe"
```

The installer publishes a self-contained `win-x64` host, copies the OpenBB
Python source, creates a service-owned virtual environment, generates the
widget token only when absent, applies restrictive ACLs, registers delayed
automatic startup and SCM recovery, starts the service, and runs `doctor`.

Preview all changes without elevation:

```powershell
.\deploy\windows\install-openbb-service.ps1 `
  -SourceRoot (Resolve-Path .) -WhatIf
```

## Verify

Run the read-only checks after install and after every reboot:

```powershell
.\deploy\windows\Test-OpenBBService.ps1 `
  -EvidencePath C:\ProgramData\OpenBB-Verification\health.json
```

On a disposable acceptance host, verify isolated child recovery and clean
shutdown:

```powershell
.\deploy\windows\Test-OpenBBService.ps1 `
  -ExerciseScmRecovery -ExerciseRecovery -ExerciseCleanStop -Confirm:$false `
  -EvidencePath C:\ProgramData\OpenBB-Verification\acceptance.json
```

Evidence contains only component names and timestamps. It never includes
tokens, account names, local paths, portfolio data, or process command lines.

## Update and rollback

```powershell
.\deploy\windows\update-openbb-service.ps1 `
  -SourceRoot (Resolve-Path .) `
  -PythonExecutable "C:\Python312\python.exe"
```

Updates publish into a staging directory, stop the service, atomically swap
the release, start it, and run `doctor`. Failed health restores the prior
release and exact prior configuration. Persistent state and secrets remain
under `C:\ProgramData\OpenBB Portfolio` and are never part of the swap.

## Uninstall

```powershell
.\deploy\windows\uninstall-openbb-service.ps1
```

This removes the service and application binaries but preserves ProgramData.
To permanently delete logs, job state, configuration, and secrets:

```powershell
.\deploy\windows\uninstall-openbb-service.ps1 -PurgeData
```

See the full [operator runbook](../../docs/operations/openbb-windows-service.md).
