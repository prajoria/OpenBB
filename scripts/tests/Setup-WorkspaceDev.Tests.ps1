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
        $ScriptText | Should Match "submodule update --init --recursive"
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
        $ScriptText | Should Match "uv sync --extra dev --extra live"
    }

    It "never creates or populates a root environment file" {
        $ScriptText | Should Not Match "New-Item.+\.env"
        $ScriptText | Should Not Match "Set-Content.+\.env"
        $ScriptText | Should Not Match "Add-Content.+\.env"
    }
}
