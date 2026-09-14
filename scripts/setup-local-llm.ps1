#!/usr/bin/env pwsh
<#!
.SYNOPSIS
    Preflight the OpenBB local LLM development environment.

.DESCRIPTION
    Defines the supported Ollama and Qwen hardware profiles. This initial
    bootstrap slice is offline-safe: -NoDownload never installs Ollama or a
    model, making it suitable for CI and workstation capability checks.
#>
[CmdletBinding()]
param(
    [ValidateSet(
        "nvidia-3080",
        "nvidia-3080-12gb",
        "nvidia-3090",
        "nvidia-24gb",
        "nvidia-48gb",
        "nvidia-80gb-plus"
    )]
    [string]$Profile = "nvidia-3080",
    [switch]$NoDownload,
    [switch]$Verify
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:OpenBBLocalLlmProfiles = @{
    "nvidia-3080" = [pscustomobject]@{
        Name = "nvidia-3080"
        Model = "qwen2.5-coder:7b"
        Quantization = "Q4_K_M"
        ContextTokens = 8192
        MinimumVramGB = 10
        MinimumDiskGB = 8
    }
    "nvidia-3080-12gb" = [pscustomobject]@{
        Name = "nvidia-3080-12gb"
        Model = "qwen2.5-coder:7b"
        Quantization = "Q4_K_M"
        ContextTokens = 8192
        MinimumVramGB = 12
        MinimumDiskGB = 9
    }
    "nvidia-3090" = [pscustomobject]@{
        Name = "nvidia-3090"
        Model = "qwen2.5-coder:14b"
        Quantization = "Q4_K_M"
        ContextTokens = 16384
        MinimumVramGB = 24
        MinimumDiskGB = 14
    }
    "nvidia-24gb" = [pscustomobject]@{
        Name = "nvidia-24gb"
        Model = "qwen2.5-coder:14b"
        Quantization = "Q4_K_M"
        ContextTokens = 16384
        MinimumVramGB = 24
        MinimumDiskGB = 15
    }
    "nvidia-48gb" = [pscustomobject]@{
        Name = "nvidia-48gb"
        Model = "qwen2.5-coder:32b"
        Quantization = "Q4_K_M"
        ContextTokens = 32768
        MinimumVramGB = 48
        MinimumDiskGB = 28
    }
    "nvidia-80gb-plus" = [pscustomobject]@{
        Name = "nvidia-80gb-plus"
        Model = "qwen2.5-coder:32b"
        Quantization = "Q4_K_M"
        ContextTokens = 32768
        MinimumVramGB = 80
        MinimumDiskGB = 72
    }
}

function Get-OpenBBLocalLlmProfile {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Name)

    if (-not $script:OpenBBLocalLlmProfiles.ContainsKey($Name)) {
        $supported = $script:OpenBBLocalLlmProfiles.Keys | Sort-Object
        throw "Unsupported profile '$Name'. Supported profiles: $($supported -join ', ')."
    }

    return $script:OpenBBLocalLlmProfiles[$Name]
}

function Test-OpenBBLocalLlmPrerequisites {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$SelectedProfile,
        [Nullable[int]]$AvailableVramGB,
        [Nullable[int]]$AvailableDiskGB
    )

    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if ($null -eq $AvailableVramGB) {
        $vramMiB = & nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>$null |
            ForEach-Object { [int]$_.Trim() } |
            Measure-Object -Maximum |
            Select-Object -ExpandProperty Maximum
        $AvailableVramGB = if ($null -eq $vramMiB) { 0 } else { [math]::Floor($vramMiB / 1024) }
    }
    if ($null -eq $AvailableDiskGB) {
        $cacheRoot = [Environment]::GetFolderPath("LocalApplicationData")
        $driveName = (Get-Item -LiteralPath $cacheRoot).PSDrive.Name
        $AvailableDiskGB = [math]::Floor((Get-PSDrive -Name $driveName).Free / 1GB)
    }

    $failureReasons = @()
    if ($AvailableVramGB -lt $SelectedProfile.MinimumVramGB) {
        $failureReasons += "requires $($SelectedProfile.MinimumVramGB) GB VRAM; detected $AvailableVramGB GB"
    }
    if ($AvailableDiskGB -lt $SelectedProfile.MinimumDiskGB) {
        $failureReasons += "requires $($SelectedProfile.MinimumDiskGB) GB free disk; detected $AvailableDiskGB GB"
    }

    return [pscustomobject]@{
        Profile = $SelectedProfile.Name
        Model = $SelectedProfile.Model
        OllamaInstalled = $null -ne $ollama
        AvailableVramGB = $AvailableVramGB
        AvailableDiskGB = $AvailableDiskGB
        IsCompatible = $failureReasons.Count -eq 0
        FailureReasons = $failureReasons
        DownloadsSkipped = $NoDownload.IsPresent
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    $selectedProfile = Get-OpenBBLocalLlmProfile -Name $Profile
    $preflight = Test-OpenBBLocalLlmPrerequisites -SelectedProfile $selectedProfile
    $preflight | Format-List

    if (-not $preflight.IsCompatible) {
        throw "Profile '$Profile' is not supported on this machine: $($preflight.FailureReasons -join '; ')."
    }
    if ($Verify) {
        if (-not $preflight.OllamaInstalled) {
            throw "Ollama is not installed, so verification cannot run."
        }
        throw "Verification-only mode is not implemented yet."
    } elseif ($NoDownload) {
        Write-Host "NoDownload selected; no runtime or model was installed."
    } elseif (-not $preflight.OllamaInstalled) {
        throw "Ollama is not installed. Re-run with -NoDownload for preflight only."
    } else {
        throw "Model installation is not implemented yet. Re-run with -NoDownload for preflight only."
    }
}