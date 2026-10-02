Describe "Workspace development setup preflight" {
    BeforeAll {
        $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        $ScriptPath = Join-Path $RepoRoot "scripts\setup_workspace_dev.ps1"
        $ScriptText = Get-Content $ScriptPath -Raw
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
        Mock Get-Command { [pscustomobject]@{ Name = $Name } }
        Mock Test-Path { $true }
        Mock Get-NetTCPConnection {
            [pscustomobject]@{
                LocalAddress = "127.0.0.1"
                LocalPort = 3306
                State = "Listen"
            }
        }
        Mock Invoke-ExternalProcess { 0 }
        Mock Push-Location {}
        Mock Pop-Location {}
        Mock Write-Host {}
        Mock Write-Warning {}
    }

    It "is valid PowerShell" {
        $ParseErrors.Count | Should Be 0
    }

    It "exposes browser installation and package-install skip switches" {
        $parameters = $ScriptAst.ParamBlock.Parameters.Name.VariablePath.UserPath

        ($parameters -contains "InstallBrowser") | Should Be $true
        ($parameters -contains "SkipPackageInstall") | Should Be $true
    }

    It "initializes only the three Workspace development submodules" {
        $ScriptText | Should Match "third_party[\\/]backends-for-openbb"
        $ScriptText | Should Match "third_party[\\/]agents-for-openbb"
        $ScriptText | Should Match "third_party[\\/]openbb-workspace-bench"
        $ScriptText | Should Match '"submodule",\s*"update",\s*"--init",\s*"--recursive"'
    }

    It "guards package installation with SkipPackageInstall" {
        $ScriptText | Should Match 'if\s*\(\s*-not\s+\$SkipPackageInstall\s*\)'
        $ScriptText | Should Match '"-e"'
        $ScriptText | Should Match "browser_test_harness\[workspace,test\]"
    }

    It "avoids the portfolio-intel and editable techtrade resolver conflict" {
        $ScriptText | Should Match '\$portfolioIntelArgs\s*=\s*@\(\s*"-m",\s*"pip",\s*"install",\s*"--no-deps",\s*"-e"'
    }

    It "checks MySQL and synchronizes Workspace Bench dependencies" {
        $ScriptText | Should Match "Get-NetTCPConnection"
        $ScriptText | Should Match "LocalPort\s+3306"
        $ScriptText | Should Match 'LocalAddress\s+-eq\s+"127\.0\.0\.1"'
        $ScriptText | Should Match '"sync",\s*"--extra",\s*"dev",\s*"--extra",\s*"live"'
    }

    It "rejects a MySQL listener bound only to 0.0.0.0" {
        Mock Get-NetTCPConnection {
            [pscustomobject]@{
                LocalAddress = "0.0.0.0"
                LocalPort = 3306
                State = "Listen"
            }
        }

        { Invoke-WorkspaceDevSetup -SkipPackageInstall } |
            Should Throw "MySQL is not listening on 127.0.0.1:3306"
    }

    It "accepts a MySQL listener bound to 127.0.0.1" {
        { Invoke-WorkspaceDevSetup -SkipPackageInstall } | Should Not Throw
    }

    It "installs Chromium with the virtual environment Python when requested" {
        $expectedPython = Join-Path $RepoRoot ".venv_portfolio\Scripts\python.exe"

        Invoke-WorkspaceDevSetup -SkipPackageInstall -InstallBrowser

        Assert-MockCalled Invoke-ExternalProcess -Times 1 -Exactly -ParameterFilter {
            $FilePath -eq $expectedPython -and
            ($ArgumentList -join " ") -eq "-m playwright install chromium"
        }
    }

    It "fails loudly when Chromium installation exits nonzero" {
        $expectedPython = Join-Path $RepoRoot ".venv_portfolio\Scripts\python.exe"
        Mock Invoke-ExternalProcess {
            23
        } -ParameterFilter {
            $FilePath -eq $expectedPython -and
            ($ArgumentList -join " ") -eq "-m playwright install chromium"
        }

        { Invoke-WorkspaceDevSetup -SkipPackageInstall -InstallBrowser } |
            Should Throw "Playwright Chromium installation failed"
    }

    It "never creates or populates a root environment file" {
        $ScriptText | Should Not Match "New-Item.+\.env"
        $ScriptText | Should Not Match "Set-Content.+\.env"
        $ScriptText | Should Not Match "Add-Content.+\.env"
    }
}
