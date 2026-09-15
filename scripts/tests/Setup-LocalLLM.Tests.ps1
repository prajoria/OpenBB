Describe "OpenBB local LLM bootstrap profiles" {
    BeforeAll {
        $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        . (Join-Path $RepoRoot "scripts\setup-local-llm.ps1") -NoDownload
    }

    It "selects Qwen 7B for an RTX 3080" {
        $profile = Get-OpenBBLocalLlmProfile -Name "nvidia-3080"

        $profile.Model | Should Be "qwen2.5-coder:7b"
        $profile.ContextTokens | Should Be 8192
        $profile.MinimumVramGB | Should Be 10
    }

    It "selects Qwen 14B for an RTX 3090" {
        $profile = Get-OpenBBLocalLlmProfile -Name "nvidia-3090"

        $profile.Model | Should Be "qwen2.5-coder:14b"
        $profile.ContextTokens | Should Be 16384
        $profile.MinimumVramGB | Should Be 24
    }

    It "reports a resource-gate failure for an undersized machine" {
        $profile = Get-OpenBBLocalLlmProfile -Name "nvidia-3090"
        $preflight = Test-OpenBBLocalLlmPrerequisites -SelectedProfile $profile -AvailableVramGB 10 -AvailableDiskGB 100

        $preflight.IsCompatible | Should Be $false
        $preflight.FailureReasons | Should Match "requires 24 GB VRAM"
    }

    It "reports a resource-gate success at the profile minimum" {
        $profile = Get-OpenBBLocalLlmProfile -Name "nvidia-3090"
        $preflight = Test-OpenBBLocalLlmPrerequisites -SelectedProfile $profile -AvailableVramGB 24 -AvailableDiskGB 14

        $preflight.IsCompatible | Should Be $true
    }

    It "plans a Windows Ollama install and model pull without executing either" {
        $profile = Get-OpenBBLocalLlmProfile -Name "nvidia-3090"
        $plan = Get-OpenBBLocalLlmInstallPlan -SelectedProfile $profile -Platform "Windows" -OllamaInstalled $false

        $plan.RuntimeCommand | Should Match "winget install --id Ollama.Ollama"
        $plan.ModelCommand | Should Be "ollama pull qwen2.5-coder:14b"
    }

    It "does not plan a runtime install when Ollama is already installed" {
        $profile = Get-OpenBBLocalLlmProfile -Name "nvidia-3090"
        $plan = Get-OpenBBLocalLlmInstallPlan -SelectedProfile $profile -Platform "Windows" -OllamaInstalled $true

        $plan.RuntimeCommand | Should BeNullOrEmpty
        $plan.ModelCommand | Should Be "ollama pull qwen2.5-coder:14b"
    }

    It "locates Ollama at its standard per-user Windows installation path" {
        Mock Get-Command {
            param([string]$Name)
            if ($Name -eq "ollama") { return $null }
            return [pscustomobject]@{ Source = (Join-Path $PSHOME "pwsh.exe") }
        }
        Mock Test-Path { $true }

        $command = Get-OpenBBLocalLlmCommand

        $command | Should Match "Ollama\\ollama.exe$"
    }

    It "does not let no-download mode mask a verification request" {
        $script = Join-Path $RepoRoot "scripts\setup-local-llm.ps1"
        $pwsh = (Get-Command pwsh).Source
        $output = & $pwsh -NoProfile -File $script -Profile "nvidia-3090" -NoDownload -Verify 2>&1

        $LASTEXITCODE | Should Not Be 0
        ($output -join "`n") | Should Match "verification cannot run|Verification-only mode"
    }

    It "rejects unknown profiles with an actionable error" {
        $caught = $null
        try {
            Get-OpenBBLocalLlmProfile -Name "unsupported"
        } catch {
            $caught = $_
        }

        $caught | Should Not BeNullOrEmpty
        $caught.Exception.Message | Should Match "Supported profiles"
    }
}