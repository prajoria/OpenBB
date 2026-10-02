Set-StrictMode -Version Latest

function Get-CopilotApiProcessIdentitySnapshot {
    param([Parameter(Mandatory)][pscustomobject]$State)

    try {
        $process = Get-Process -Id ([int]$State.Pid) -ErrorAction Stop
    } catch {
        if (
            $_.FullyQualifiedErrorId -like
                "NoProcessFoundForGivenId,*"
        ) {
            return [pscustomobject]@{
                Status = "Missing"
                Process = $null
            }
        }
        throw "Copilot API process identity could not be inspected."
    }
    try {
        $null = $process.SafeHandle
        $startTimeUtcTicks =
            $process.StartTime.ToUniversalTime().Ticks
    } catch {
        $process.Dispose()
        throw "Copilot API process identity could not be inspected."
    }
    if ($startTimeUtcTicks -eq [long]$State.StartTimeUtcTicks) {
        return [pscustomobject]@{
            Status = "Match"
            Process = $process
        }
    }
    $process.Dispose()
    return [pscustomobject]@{
        Status = "Mismatch"
        Process = $null
    }
}

function Get-CopilotApiProcessIdentityStatus {
    param([Parameter(Mandatory)][pscustomobject]$State)

    $snapshot = Get-CopilotApiProcessIdentitySnapshot -State $State
    try {
        return $snapshot.Status
    } finally {
        if ($null -ne $snapshot.Process) {
            $snapshot.Process.Dispose()
        }
    }
}

function Read-CopilotApiPidState {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$InvalidMessage
    )

    try {
        $state = Get-Content $Path -Raw | ConvertFrom-Json
        $pidValue = [int]$state.Pid
        $startTicks = [long]$state.StartTimeUtcTicks
    } catch {
        throw $InvalidMessage
    }
    if ($pidValue -le 0 -or $startTicks -le 0) {
        throw $InvalidMessage
    }

    return [pscustomobject]@{
        Pid = $pidValue
        StartTimeUtcTicks = $startTicks
    }
}
