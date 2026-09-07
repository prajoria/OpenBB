Describe "OpenBB service deployment" {
    BeforeAll {
        $DeployRoot = Split-Path -Parent $PSScriptRoot
        $RepoRoot = Split-Path -Parent (Split-Path -Parent $DeployRoot)
        Import-Module (Join-Path $DeployRoot "OpenBBService.Deployment.psm1") `
            -Force -DisableNameChecking
    }

    It "rejects relative deployment paths" {
        $caught = $null
        try {
            Assert-AbsolutePath ".\relative" "InstallRoot"
        } catch {
            $caught = $_
        }
        $caught | Should Not BeNullOrEmpty
    }

    It "generates a secret once without exposing it" {
        $root = Join-Path $TestDrive "data"
        $path = Join-Path $root "secrets.env"
        Ensure-SecretFile -Path $path
        $first = Get-Content -LiteralPath $path -Raw

        Ensure-SecretFile -Path $path

        (Get-Content -LiteralPath $path -Raw) | Should BeExactly $first
        $first | Should Match "^PI_WIDGET_BACKEND_TOKEN=[A-Za-z0-9_-]{43}\r?\n$"
    }

    It "honors WhatIf when generating secrets" {
        $path = Join-Path $TestDrive "whatif\secrets.env"
        Ensure-SecretFile -Path $path -WhatIf
        Test-Path -LiteralPath $path | Should Be $false
    }

    It "writes an idempotent configuration with stable current paths" {
        $release = Join-Path $TestDrive "install\current"
        $data = Join-Path $TestDrive "data"
        New-Item -ItemType Directory -Path $release, $data -Force | Out-Null

        $firstPath = Write-ServiceConfiguration -ReleaseRoot $release -DataRoot $data
        $first = Get-Content -LiteralPath $firstPath -Raw
        $secondPath = Write-ServiceConfiguration -ReleaseRoot $release -DataRoot $data

        (Get-Content -LiteralPath $secondPath -Raw) | Should BeExactly $first
        $config = $first | ConvertFrom-Json
        $config.serviceHost.components.Count | Should Be 3
        $config.serviceHost.components[0].name | Should Be "jobs-worker"
        $config.serviceHost.components[2].port | Should Be 6120
    }

    It "does not write configuration under WhatIf" {
        $release = Join-Path $TestDrive "install\current"
        $data = Join-Path $TestDrive "whatif-data"
        New-Item -ItemType Directory -Path $release, $data -Force | Out-Null

        Write-ServiceConfiguration -ReleaseRoot $release -DataRoot $data -WhatIf

        Test-Path -LiteralPath (Join-Path $data "service.json") | Should Be $false
    }

    It "validates install parameters before making changes" {
        $caught = $null
        try {
            & (Join-Path $DeployRoot "install-openbb-service.ps1") `
                -SourceRoot ".\relative"
        } catch {
            $caught = $_
        }
        $caught | Should Not BeNullOrEmpty
    }

    It "honors WhatIf across the install entry point" {
        $install = Join-Path $TestDrive "install-whatif"
        $data = Join-Path $TestDrive "data-whatif"
        $artifacts = Join-Path $TestDrive "artifacts"
        New-Item -ItemType Directory -Path $artifacts | Out-Null

        & (Join-Path $DeployRoot "install-openbb-service.ps1") `
            -SourceRoot $RepoRoot -InstallRoot $install -DataRoot $data `
            -ArtifactDirectory $artifacts -SkipPythonInstall -WhatIf

        Test-Path -LiteralPath $install | Should Be $false
        Test-Path -LiteralPath $data | Should Be $false
    }
}
