Describe "Portfolio Intelligence launcher" {
    BeforeAll {
        $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        $ScriptPath = Join-Path $RepoRoot "scripts\run_widget_backend.ps1"
        $Tokens = $null
        $ParseErrors = $null
        $ScriptAst = [System.Management.Automation.Language.Parser]::ParseFile(
            $ScriptPath,
            [ref]$Tokens,
            [ref]$ParseErrors
        )
        . $ScriptPath
    }

    BeforeEach {
        $env:PI_WIDGET_BACKEND_AUTH_MODE = $null
        $env:PI_WIDGET_BACKEND_TOKEN = $null
        Mock Test-Path { $true }
        Mock Get-NetTCPConnection { @() }
        Mock Push-Location {}
        Mock Pop-Location {}
        Mock Invoke-WidgetBackendProcess { 0 }
    }

    AfterEach {
        $env:PI_WIDGET_BACKEND_AUTH_MODE = $null
        $env:PI_WIDGET_BACKEND_TOKEN = $null
    }

    It "is valid PowerShell" {
        $ParseErrors.Count | Should Be 0
    }

    It "defaults to port 6120 and explicit loopback development mode" {
        $parameters = @{}
        foreach ($parameter in $ScriptAst.ParamBlock.Parameters) {
            $parameters[$parameter.Name.VariablePath.UserPath] = $parameter
        }

        $parameters["Port"].DefaultValue.Value | Should Be 6120
        $parameters["AuthMode"].DefaultValue.Value | Should Be "loopback-dev"
        $validateSet = $parameters["AuthMode"].Attributes |
            Where-Object { $_.TypeName.Name -eq "ValidateSet" }
        ($validateSet.PositionalArguments.Value -join ",") |
            Should Be "loopback-dev,required"
    }

    It "binds uvicorn only to 127.0.0.1 and port 6120" {
        Invoke-PortfolioIntelligenceBackend

        Assert-MockCalled Invoke-WidgetBackendProcess -Times 1 -Exactly -ParameterFilter {
            ($ArgumentList -join " ") -eq (
                "-m uvicorn " +
                "openbb_portfolio_intel.widget_backend.main:app " +
                "--host 127.0.0.1 --port 6120"
            )
        }
        $env:PI_WIDGET_BACKEND_AUTH_MODE | Should Be "loopback-dev"
    }

    It "adds uvicorn reload when requested" {
        Invoke-PortfolioIntelligenceBackend -Reload

        Assert-MockCalled Invoke-WidgetBackendProcess -Times 1 -Exactly -ParameterFilter {
            ($ArgumentList -join " ") -match "--port 6120 --reload$"
        }
    }

    It "requires a token in required authentication mode" {
        { Invoke-PortfolioIntelligenceBackend -AuthMode required } |
            Should Throw "-Token is required when -AuthMode required."
    }

    It "sets the required authentication token for the child process" {
        Invoke-PortfolioIntelligenceBackend -AuthMode required -Token "test-token"

        $env:PI_WIDGET_BACKEND_AUTH_MODE | Should Be "required"
        $env:PI_WIDGET_BACKEND_TOKEN | Should Be "test-token"
    }

    It "clears inherited tokens in loopback development mode" {
        $env:PI_WIDGET_BACKEND_TOKEN = "stale-token"

        Invoke-PortfolioIntelligenceBackend -AuthMode "loopback-dev"

        $env:PI_WIDGET_BACKEND_TOKEN | Should BeNullOrEmpty
    }

    It "rejects a port that already has a listener" {
        Mock Get-NetTCPConnection {
            [pscustomobject]@{ LocalPort = 6120; State = "Listen" }
        }

        { Invoke-PortfolioIntelligenceBackend } |
            Should Throw "Port 6120 is already in use."
        Assert-MockCalled Invoke-WidgetBackendProcess -Times 0 -Scope It
    }

    It "fails with setup guidance when the shared environment is absent" {
        Mock Test-Path { $false }

        { Invoke-PortfolioIntelligenceBackend } |
            Should Throw ".venv_portfolio is absent. Run scripts/setup_workspace_dev.ps1 first."
        Assert-MockCalled Invoke-WidgetBackendProcess -Times 0 -Scope It
    }
}
