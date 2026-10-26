# Owned-process lifecycle helpers for the dual MCP launcher.

function Get-ProcessIdentity {
    param([System.Diagnostics.Process]$Process)

    return @{
        pid = $Process.Id
        started_at = $Process.StartTime.ToUniversalTime().ToString("o")
        executable = $Process.Path
    }
}

function Test-ProcessIdentity {
    param($Identity)

    if ($null -eq $Identity -or -not $Identity.pid -or -not $Identity.started_at) {
        return $false
    }
    try {
        $process = Get-Process -Id $Identity.pid -ErrorAction SilentlyContinue
        if ($null -eq $process -or $null -eq $process.StartTime) {
            return $false
        }
        if ($Identity.started_at -is [datetime]) {
            $expectedStart = $Identity.started_at
        } else {
            $expectedStart = [datetime]::MinValue
            if (-not [datetime]::TryParse(
                [string]$Identity.started_at,
                [ref]$expectedStart
            )) {
                return $false
            }
        }
        $expectedStart = $expectedStart.ToUniversalTime()
        $sameStart = $process.StartTime.ToUniversalTime() -eq $expectedStart
        $sameExecutable = -not $Identity.executable -or
            [string]::Equals(
                $process.Path,
                $Identity.executable,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        return $sameStart -and $sameExecutable
    } catch {
        return $false
    }
}

function Test-PortListening {
    param([int]$Port)

    return $null -ne (
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
    )
}

function Read-ProcessState {
    param([string]$StatePath)

    if (-not (Test-Path -LiteralPath $StatePath)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    } catch {
        Write-Warning "Ignoring unreadable MCP process state at $StatePath."
        Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
        return $null
    }
}

function Get-DescendantProcessIds {
    param([int]$ParentId)

    $childrenByParent = @{}
    Get-CimInstance Win32_Process | ForEach-Object {
        $key = [int]$_.ParentProcessId
        if (-not $childrenByParent.ContainsKey($key)) {
            $childrenByParent[$key] = [System.Collections.Generic.List[int]]::new()
        }
        $childrenByParent[$key].Add([int]$_.ProcessId)
    }

    $result = [System.Collections.Generic.List[int]]::new()
    $pending = [System.Collections.Generic.Stack[int]]::new()
    $pending.Push($ParentId)
    while ($pending.Count -gt 0) {
        $current = $pending.Pop()
        if (-not $childrenByParent.ContainsKey($current)) {
            continue
        }
        foreach ($childId in $childrenByParent[$current]) {
            $result.Add($childId)
            $pending.Push($childId)
        }
    }
    return $result
}

function Stop-ProcessTree {
    param($Identity)

    if (-not (Test-ProcessIdentity -Identity $Identity)) {
        Write-Warning "Skipping stale or reused process ID $($Identity.pid)."
        return
    }
    $descendants = @(Get-DescendantProcessIds -ParentId $Identity.pid)
    [array]::Reverse($descendants)
    foreach ($processId in $descendants) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $Identity.pid -Force -ErrorAction SilentlyContinue
}

function ConvertTo-NativeArguments {
    param([string[]]$Arguments)

    return $Arguments | ForEach-Object {
        if ($_ -notmatch '[\s"]') {
            $_
        } elseif ($_ -match '"') {
            throw "Native argument contains an unsupported quote: $_"
        } else {
            '"' + ($_ -replace '(\\+)$', '$1$1') + '"'
        }
    }
}

function Get-ServerAuthHeader {
    param(
        [string]$SerializedCredentials,
        [switch]$Required
    )

    if (-not $SerializedCredentials) {
        if ($Required) {
            throw "portfolio-ops requires OPENBB_MCP_SERVER_AUTH with a high-entropy password."
        }
        return $null
    }
    try {
        $credentials = @($SerializedCredentials | ConvertFrom-Json)
    } catch {
        throw "OPENBB_MCP_SERVER_AUTH must be a JSON [username,password] array."
    }
    if ($credentials.Count -ne 2 -or -not [string]$credentials[0] -or
        -not [string]$credentials[1]) {
        throw "OPENBB_MCP_SERVER_AUTH must contain a username and password."
    }
    if (([string]$credentials[1]).Length -lt 32 -and $Required) {
        throw "OPENBB_MCP_SERVER_AUTH must contain a username and password of at least 32 characters."
    }
    if (([string]$credentials[1]).Length -lt 32) {
        Write-Warning "OPENBB_MCP_SERVER_AUTH uses a password shorter than 32 characters."
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes(
        "$($credentials[0]):$($credentials[1])"
    )
    return "Bearer $([Convert]::ToBase64String($bytes))"
}

function Wait-ForOwnedListener {
    param(
        [string]$Name,
        $LauncherIdentity,
        [int]$Port,
        [string]$ErrorLog,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen `
            -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $connection) {
            $launcherProcesses = @($LauncherIdentity.pid) +
                @(Get-DescendantProcessIds -ParentId $LauncherIdentity.pid)
            if ($connection.OwningProcess -notin $launcherProcesses) {
                throw "$Name port $Port was claimed by an unrelated process."
            }
            $serverProcess = Get-Process -Id $connection.OwningProcess -ErrorAction Stop
            return Get-ProcessIdentity -Process $serverProcess
        }
        Start-Sleep -Milliseconds 500
    }
    $launcherStatus = if (Test-ProcessIdentity -Identity $LauncherIdentity) {
        "The launcher is still running."
    } else {
        "The launcher exited."
    }
    $details = if (Test-Path -LiteralPath $ErrorLog) {
        (Get-Content -LiteralPath $ErrorLog -Tail 30) -join [Environment]::NewLine
    } else {
        "No error log was created."
    }
    throw "$Name did not listen on port $Port within $TimeoutSeconds seconds. " +
        "$launcherStatus$([Environment]::NewLine)$details"
}

function Stop-PartialStack {
    param(
        $PlatformIdentity,
        $PlatformLauncherIdentity,
        $WorkspaceIdentity,
        $WorkspaceLauncherIdentity
    )

    if ($null -ne $WorkspaceIdentity) {
        Stop-ProcessTree -Identity $WorkspaceIdentity
    }
    if ($null -ne $WorkspaceLauncherIdentity) {
        Stop-ProcessTree -Identity $WorkspaceLauncherIdentity
    }
    if ($null -ne $PlatformIdentity) {
        Stop-ProcessTree -Identity $PlatformIdentity
    }
    if ($null -ne $PlatformLauncherIdentity) {
        Stop-ProcessTree -Identity $PlatformLauncherIdentity
    }
}

function Clear-StaleProcessState {
    param(
        $State,
        [string]$StatePath
    )

    $running = @(
        $State.platform,
        $State.workspace,
        $State.platform_launcher,
        $State.workspace_launcher
    ) |
        Where-Object { Test-ProcessIdentity -Identity $_ }
    if ($running.Count -gt 0) {
        throw "A recorded MCP stack is still running. Use -Action Status or -Action Stop first."
    }
    Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
}

function Resolve-PortfolioEnvironment {
    param(
        [string]$OpenBBRoot,
        [string]$PortfolioPython,
        [string]$PortfolioRoot
    )

    if ($PortfolioPython) {
        $resolvedPython = [System.IO.Path]::GetFullPath($PortfolioPython)
        if (-not (Test-Path -LiteralPath $resolvedPython -PathType Leaf)) {
            throw "PortfolioPython '$resolvedPython' does not exist."
        }
    } elseif ($env:OPENBB_PORTFOLIO_PYTHON) {
        $resolvedPython = [System.IO.Path]::GetFullPath(
            $env:OPENBB_PORTFOLIO_PYTHON
        )
        if (-not (Test-Path -LiteralPath $resolvedPython -PathType Leaf)) {
            throw "OPENBB_PORTFOLIO_PYTHON '$resolvedPython' does not exist."
        }
    } else {
        $pythonCandidates = @(
            (Join-Path $OpenBBRoot ".venv_portfolio\Scripts\python.exe")
        )
        $gitCommonDir = (& git -C $OpenBBRoot rev-parse --path-format=absolute `
            --git-common-dir 2>$null)
        if ($LASTEXITCODE -eq 0 -and $gitCommonDir) {
            $mainCheckout = Split-Path $gitCommonDir.Trim() -Parent
            $pythonCandidates += Join-Path $mainCheckout `
                ".venv_portfolio\Scripts\python.exe"
        }
        $resolvedPython = $pythonCandidates |
            ForEach-Object { [System.IO.Path]::GetFullPath($_) } |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
            Select-Object -First 1
        if (-not $resolvedPython) {
            throw "Portfolio profile requires .venv_portfolio. Pass -PortfolioPython or set OPENBB_PORTFOLIO_PYTHON."
        }
    }

    $repositoryRoot = if ($PortfolioRoot) {
        [System.IO.Path]::GetFullPath($PortfolioRoot)
    } else {
        [System.IO.Path]::GetFullPath(
            (Join-Path (Split-Path $resolvedPython -Parent) "..\..")
        )
    }
    if (-not (Test-Path -LiteralPath (
        Join-Path $repositoryRoot "openbb_platform\pyproject.toml"
    ))) {
        throw "PortfolioRoot '$repositoryRoot' is not an OpenBB checkout."
    }

    return [pscustomobject]@{
        Python = $resolvedPython
        RepositoryRoot = $repositoryRoot
    }
}

function Get-McpLockTimestamp {
    param([string]$LockPath)

    if (-not (Test-Path -LiteralPath $LockPath -PathType Leaf)) {
        throw "Dependency lock '$LockPath' is missing. Run python scripts/lock_mcp_envs.py."
    }
    $match = [regex]::Match(
        (Get-Content -LiteralPath $LockPath -Raw),
        '(?m)^# locked-at: (\S+)\s*$'
    )
    if (-not $match.Success) {
        throw "Dependency lock '$LockPath' has no locked-at header."
    }
    return $match.Groups[1].Value
}

function Get-LockedUvArguments {
    param([string]$OpenBBRoot, [string]$LockName)

    # --exclude-newer bounds any requirement the lock does not yet pin.
    $lockPath = Join-Path $OpenBBRoot "scripts\mcp_locks\$LockName"
    return @(
        "run",
        "--no-project",
        "--python", "3.13",
        "--exclude-newer", (Get-McpLockTimestamp -LockPath $lockPath),
        "--with-requirements", $lockPath
    )
}

function Get-PlatformUvArguments {
    param([string]$OpenBBRoot)

    # FastMCP 3.4.6 requires Starlette >=1.0.1, which conflicts with Platform
    # FastAPI; platform-mcp.txt keeps the Platform on FastMCP 3.4.0.
    $arguments = Get-LockedUvArguments -OpenBBRoot $OpenBBRoot -LockName "platform-mcp.txt"
    foreach ($editable in @(
        "openbb_platform",
        "openbb_platform\core",
        "openbb_platform\extensions\platform_api",
        "openbb_platform\extensions\mcp_server"
    )) {
        $arguments += @("--with-editable", (Join-Path $OpenBBRoot $editable))
    }
    return $arguments
}

function Get-WorkspaceUvArguments {
    param([string]$OpenBBRoot, [string]$WorkspaceBackend)

    return (Get-LockedUvArguments -OpenBBRoot $OpenBBRoot -LockName "workspace-mcp.txt") +
        @("--directory", $WorkspaceBackend)
}

Export-ModuleMember -Function @(
    "Clear-StaleProcessState",
    "ConvertTo-NativeArguments",
    "Get-DescendantProcessIds",
    "Get-McpLockTimestamp",
    "Get-PlatformUvArguments",
    "Get-ProcessIdentity",
    "Get-ServerAuthHeader",
    "Get-WorkspaceUvArguments",
    "Read-ProcessState",
    "Resolve-PortfolioEnvironment",
    "Stop-PartialStack",
    "Stop-ProcessTree",
    "Test-PortListening",
    "Test-ProcessIdentity",
    "Wait-ForOwnedListener"
)
