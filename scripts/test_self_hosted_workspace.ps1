#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Verify the running self-hosted Workspace without changing its state.
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Join-Path $repoRoot "third_party\workspace"
$backendRoot = Join-Path $workspaceRoot "backend-api"
$frontendRoot = Join-Path $workspaceRoot "terminalpro"
$composeFile = Join-Path $backendRoot "docker-compose-local-dev-sqlite.yml"
$composeOverride = Join-Path $backendRoot "backend\workspace-compose.secrets"
$adminCredentials = Join-Path $backendRoot "backend\workspace-admin-credentials.secrets"
$composeProject = "openbb-workspace-2110"
$expectedServices = @("fastapi", "redis", "rq_worker")

if (-not ("WorkspaceVerifier.ProcessJob" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Win32.SafeHandles;

namespace WorkspaceVerifier
{
    public sealed class CommandResult
    {
        public string[] Output { get; set; }
        public int ExitCode { get; set; }
        public bool TimedOut { get; set; }
        public bool CleanupSucceeded { get; set; }
    }

    public sealed class ProcessJob : IDisposable
    {
        private const uint CreateSuspended = 0x00000004;
        private const uint CreateNoWindow = 0x08000000;
        private const uint StartfUseStdHandles = 0x00000100;
        private const uint HandleFlagInherit = 0x00000001;
        private const uint GenericRead = 0x80000000;
        private const uint GenericWrite = 0x40000000;
        private const uint FileShareRead = 0x00000001;
        private const uint FileShareWrite = 0x00000002;
        private const uint OpenExisting = 3;
        private const uint WaitObject0 = 0;
        private const uint WaitTimeout = 258;
        private const uint JobObjectLimitKillOnJobClose = 0x00002000;
        private const int JobObjectBasicAccountingInformation = 1;
        private const int JobObjectExtendedLimitInformation = 9;
        private IntPtr handle;

        [StructLayout(LayoutKind.Sequential)]
        private struct SecurityAttributes
        {
            public int Length;
            public IntPtr SecurityDescriptor;
            [MarshalAs(UnmanagedType.Bool)]
            public bool InheritHandle;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct StartupInfo
        {
            public int Size;
            public string Reserved;
            public string Desktop;
            public string Title;
            public uint X;
            public uint Y;
            public uint XSize;
            public uint YSize;
            public uint XCountChars;
            public uint YCountChars;
            public uint FillAttribute;
            public uint Flags;
            public short ShowWindow;
            public short Reserved2Length;
            public IntPtr Reserved2;
            public IntPtr StandardInput;
            public IntPtr StandardOutput;
            public IntPtr StandardError;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct ProcessInformation
        {
            public IntPtr Process;
            public IntPtr Thread;
            public uint ProcessId;
            public uint ThreadId;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct BasicLimitInformation
        {
            public long PerProcessUserTimeLimit;
            public long PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass;
            public uint SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct IoCounters
        {
            public ulong ReadOperationCount;
            public ulong WriteOperationCount;
            public ulong OtherOperationCount;
            public ulong ReadTransferCount;
            public ulong WriteTransferCount;
            public ulong OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct ExtendedLimitInformation
        {
            public BasicLimitInformation BasicLimitInformation;
            public IoCounters IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct BasicAccountingInformation
        {
            public long TotalUserTime;
            public long TotalKernelTime;
            public long ThisPeriodTotalUserTime;
            public long ThisPeriodTotalKernelTime;
            public uint TotalPageFaultCount;
            public uint TotalProcesses;
            public uint ActiveProcesses;
            public uint TotalTerminatedProcesses;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr CreateJobObject(
            IntPtr jobAttributes,
            string name
        );

        [DllImport(
            "kernel32.dll",
            CharSet = CharSet.Unicode,
            SetLastError = true
        )]
        private static extern bool CreateProcess(
            string applicationName,
            StringBuilder commandLine,
            ref SecurityAttributes processAttributes,
            ref SecurityAttributes threadAttributes,
            bool inheritHandles,
            uint creationFlags,
            IntPtr environment,
            string currentDirectory,
            ref StartupInfo startupInfo,
            out ProcessInformation processInformation
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CreatePipe(
            out IntPtr readPipe,
            out IntPtr writePipe,
            ref SecurityAttributes pipeAttributes,
            uint size
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetHandleInformation(
            IntPtr handle,
            uint mask,
            uint flags
        );

        [DllImport(
            "kernel32.dll",
            CharSet = CharSet.Unicode,
            SetLastError = true
        )]
        private static extern IntPtr CreateFile(
            string fileName,
            uint desiredAccess,
            uint shareMode,
            ref SecurityAttributes securityAttributes,
            uint creationDisposition,
            uint flagsAndAttributes,
            IntPtr templateFile
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint ResumeThread(IntPtr thread);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint WaitForSingleObject(
            IntPtr handle,
            uint milliseconds
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetExitCodeProcess(
            IntPtr process,
            out uint exitCode
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateProcess(
            IntPtr process,
            uint exitCode
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetInformationJobObject(
            IntPtr job,
            int informationClass,
            IntPtr information,
            uint informationLength
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(
            IntPtr job,
            IntPtr process
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateJobObject(
            IntPtr job,
            uint exitCode
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool QueryInformationJobObject(
            IntPtr job,
            int informationClass,
            IntPtr information,
            uint informationLength,
            IntPtr returnLength
        );

        [DllImport("kernel32.dll")]
        private static extern bool CloseHandle(IntPtr handle);

        public ProcessJob()
        {
            handle = CreateJobObject(IntPtr.Zero, null);
            if (handle == IntPtr.Zero)
            {
                throw new Win32Exception();
            }

            ExtendedLimitInformation information =
                new ExtendedLimitInformation();
            information.BasicLimitInformation.LimitFlags =
                JobObjectLimitKillOnJobClose;
            int length = Marshal.SizeOf(information);
            IntPtr buffer = Marshal.AllocHGlobal(length);
            try
            {
                Marshal.StructureToPtr(information, buffer, false);
                if (!SetInformationJobObject(
                    handle,
                    JobObjectExtendedLimitInformation,
                    buffer,
                    (uint)length
                ))
                {
                    throw new Win32Exception();
                }
            }
            catch
            {
                CloseHandle(handle);
                handle = IntPtr.Zero;
                throw;
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }

        public CommandResult Run(
            string filePath,
            string[] arguments,
            int timeoutMilliseconds,
            int maximumOutputCharacters
        )
        {
            IntPtr outputRead = IntPtr.Zero;
            IntPtr outputWrite = IntPtr.Zero;
            IntPtr nullInput = IntPtr.Zero;
            IntPtr nullError = IntPtr.Zero;
            ProcessInformation processInformation =
                new ProcessInformation();
            FileStream outputStream = null;
            Task<string[]> outputTask = null;
            bool assignedToJob = false;
            SecurityAttributes inheritable = new SecurityAttributes
            {
                Length = Marshal.SizeOf<SecurityAttributes>(),
                InheritHandle = true
            };

            try
            {
                if (!CreatePipe(
                    out outputRead,
                    out outputWrite,
                    ref inheritable,
                    0
                ))
                {
                    throw new Win32Exception();
                }
                if (!SetHandleInformation(
                    outputRead,
                    HandleFlagInherit,
                    0
                ))
                {
                    throw new Win32Exception();
                }

                nullInput = CreateFile(
                    "NUL",
                    GenericRead,
                    FileShareRead | FileShareWrite,
                    ref inheritable,
                    OpenExisting,
                    0,
                    IntPtr.Zero
                );
                nullError = CreateFile(
                    "NUL",
                    GenericWrite,
                    FileShareRead | FileShareWrite,
                    ref inheritable,
                    OpenExisting,
                    0,
                    IntPtr.Zero
                );
                if (
                    nullInput == new IntPtr(-1) ||
                    nullError == new IntPtr(-1)
                )
                {
                    throw new Win32Exception();
                }

                StartupInfo startupInfo = new StartupInfo
                {
                    Size = Marshal.SizeOf<StartupInfo>(),
                    Flags = StartfUseStdHandles,
                    StandardInput = nullInput,
                    StandardOutput = outputWrite,
                    StandardError = nullError
                };
                SecurityAttributes processAttributes =
                    new SecurityAttributes
                {
                    Length = Marshal.SizeOf<SecurityAttributes>()
                };
                SecurityAttributes threadAttributes =
                    new SecurityAttributes
                {
                    Length = Marshal.SizeOf<SecurityAttributes>()
                };
                StringBuilder commandLine = new StringBuilder(
                    BuildCommandLine(filePath, arguments)
                );

                if (!CreateProcess(
                    filePath,
                    commandLine,
                    ref processAttributes,
                    ref threadAttributes,
                    true,
                    CreateSuspended | CreateNoWindow,
                    IntPtr.Zero,
                    null,
                    ref startupInfo,
                    out processInformation
                ))
                {
                    throw new Win32Exception();
                }
                if (!AssignProcessToJobObject(
                    handle,
                    processInformation.Process
                ))
                {
                    throw new Win32Exception();
                }
                assignedToJob = true;

                SafeFileHandle safeOutputRead = new SafeFileHandle(
                    outputRead,
                    true
                );
                outputRead = IntPtr.Zero;
                outputStream = new FileStream(
                    safeOutputRead,
                    FileAccess.Read,
                    4096,
                    false
                );
                outputTask = ReadOutput(
                    outputStream,
                    maximumOutputCharacters
                );
                CloseHandle(outputWrite);
                outputWrite = IntPtr.Zero;

                if (ResumeThread(processInformation.Thread) == uint.MaxValue)
                {
                    throw new Win32Exception();
                }
                CloseHandle(processInformation.Thread);
                processInformation.Thread = IntPtr.Zero;

                uint waitResult = WaitForSingleObject(
                    processInformation.Process,
                    (uint)timeoutMilliseconds
                );
                bool timedOut = waitResult == WaitTimeout;
                if (!timedOut && waitResult != WaitObject0)
                {
                    throw new Win32Exception();
                }

                int exitCode = -1;
                if (!timedOut)
                {
                    uint nativeExitCode;
                    if (!GetExitCodeProcess(
                        processInformation.Process,
                        out nativeExitCode
                    ))
                    {
                        throw new Win32Exception();
                    }
                    exitCode = unchecked((int)nativeExitCode);
                }

                bool cleanupSucceeded = TerminateAndWait(5000);
                if (!outputTask.Wait(5000))
                {
                    cleanupSucceeded = false;
                }

                return new CommandResult
                {
                    Output = outputTask.IsCompletedSuccessfully
                        ? outputTask.Result
                        : Array.Empty<string>(),
                    ExitCode = exitCode,
                    TimedOut = timedOut,
                    CleanupSucceeded = cleanupSucceeded
                };
            }
            catch
            {
                if (assignedToJob)
                {
                    bool cleanupSucceeded = false;
                    try
                    {
                        cleanupSucceeded = TerminateAndWait(5000);
                    }
                    catch
                    {
                        cleanupSucceeded = false;
                    }
                    if (!cleanupSucceeded)
                    {
                        throw new InvalidOperationException(
                            "External command cleanup failed."
                        );
                    }
                }
                throw;
            }
            finally
            {
                if (
                    processInformation.Process != IntPtr.Zero &&
                    !assignedToJob
                )
                {
                    TerminateProcess(processInformation.Process, 1);
                    WaitForSingleObject(
                        processInformation.Process,
                        5000
                    );
                }
                if (processInformation.Thread != IntPtr.Zero)
                {
                    CloseHandle(processInformation.Thread);
                }
                if (processInformation.Process != IntPtr.Zero)
                {
                    CloseHandle(processInformation.Process);
                }
                if (outputWrite != IntPtr.Zero)
                {
                    CloseHandle(outputWrite);
                }
                if (outputRead != IntPtr.Zero)
                {
                    CloseHandle(outputRead);
                }
                if (
                    nullInput != IntPtr.Zero &&
                    nullInput != new IntPtr(-1)
                )
                {
                    CloseHandle(nullInput);
                }
                if (
                    nullError != IntPtr.Zero &&
                    nullError != new IntPtr(-1)
                )
                {
                    CloseHandle(nullError);
                }
                if (outputStream != null)
                {
                    outputStream.Dispose();
                }
            }
        }

        private static string BuildCommandLine(
            string filePath,
            string[] arguments
        )
        {
            StringBuilder result = new StringBuilder(Quote(filePath));
            foreach (string argument in arguments)
            {
                result.Append(' ');
                result.Append(Quote(argument));
            }
            return result.ToString();
        }

        private static string Quote(string argument)
        {
            if (argument.Length > 0 && argument.IndexOfAny(
                new[] { ' ', '\t', '\n', '\v', '"' }
            ) < 0)
            {
                return argument;
            }

            StringBuilder result = new StringBuilder("\"");
            int backslashes = 0;
            foreach (char character in argument)
            {
                if (character == '\\')
                {
                    backslashes++;
                }
                else if (character == '"')
                {
                    result.Append('\\', backslashes * 2 + 1);
                    result.Append(character);
                    backslashes = 0;
                }
                else
                {
                    result.Append('\\', backslashes);
                    result.Append(character);
                    backslashes = 0;
                }
            }
            result.Append('\\', backslashes * 2);
            result.Append('"');
            return result.ToString();
        }

        private static async Task<string[]> ReadOutput(
            Stream output,
            int maximumCharacters
        )
        {
            StringBuilder captured = new StringBuilder();
            char[] buffer = new char[4096];
            using (StreamReader reader = new StreamReader(
                output,
                new UTF8Encoding(false, false),
                true,
                4096,
                true
            ))
            {
                int count;
                while ((count = await reader.ReadAsync(
                    buffer,
                    0,
                    buffer.Length
                ).ConfigureAwait(false)) > 0)
                {
                    int remaining = maximumCharacters - captured.Length;
                    if (remaining > 0)
                    {
                        captured.Append(
                            buffer,
                            0,
                            Math.Min(remaining, count)
                        );
                    }
                }
            }

            return captured
                .ToString()
                .Replace("\r\n", "\n")
                .Replace('\r', '\n')
                .Split(
                    new[] { '\n' },
                    StringSplitOptions.RemoveEmptyEntries
                );
        }

        public bool TerminateAndWait(int timeoutMilliseconds)
        {
            if (handle == IntPtr.Zero)
            {
                return true;
            }

            bool terminated = TerminateJobObject(handle, 1);
            Stopwatch stopwatch = Stopwatch.StartNew();
            while (
                terminated &&
                stopwatch.ElapsedMilliseconds < timeoutMilliseconds
            )
            {
                if (GetActiveProcessCount() == 0)
                {
                    return true;
                }
                Thread.Sleep(25);
            }
            return terminated && GetActiveProcessCount() == 0;
        }

        private uint GetActiveProcessCount()
        {
            int length = Marshal.SizeOf<BasicAccountingInformation>();
            IntPtr buffer = Marshal.AllocHGlobal(length);
            try
            {
                if (!QueryInformationJobObject(
                    handle,
                    JobObjectBasicAccountingInformation,
                    buffer,
                    (uint)length,
                    IntPtr.Zero
                ))
                {
                    throw new Win32Exception();
                }
                BasicAccountingInformation information =
                    Marshal.PtrToStructure<BasicAccountingInformation>(buffer);
                return information.ActiveProcesses;
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }

        public void Dispose()
        {
            if (handle != IntPtr.Zero)
            {
                CloseHandle(handle);
                handle = IntPtr.Zero;
            }
        }
    }
}
'@
}

function Invoke-WorkspaceVerificationCommand {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [Parameter(Mandatory)][string]$FailureMessage,
        [ValidateRange(1, 300)][int]$TimeoutSeconds = 30
    )

    $processJob = $null
    try {
        $resolvedCommand = @(
            Get-Command -Name $FilePath -CommandType Application `
                -ErrorAction Stop
        )[0]
        $resolvedPath = $resolvedCommand.Path
        $processJob = [WorkspaceVerifier.ProcessJob]::new()
        $result = $processJob.Run(
            $resolvedPath,
            $ArgumentList,
            $TimeoutSeconds * 1000,
            65536
        )
        if (
            $result.TimedOut -or
            $result.ExitCode -ne 0 -or
            -not $result.CleanupSucceeded
        ) {
            throw $FailureMessage
        }
        return @($result.Output)
    } catch {
        throw $FailureMessage
    } finally {
        if ($null -ne $processJob) {
            $processJob.Dispose()
        }
    }
}

function Assert-WorkspaceExactServices {
    param([Parameter(Mandatory)][AllowEmptyCollection()][string[]]$Actual)

    $expected = @($expectedServices | Sort-Object)
    $observed = @($Actual | Where-Object { $_ } | Sort-Object -Unique)
    if (
        $observed.Count -ne $expected.Count -or
        (Compare-Object -ReferenceObject $expected -DifferenceObject $observed)
    ) {
        throw "Workspace Compose services do not exactly match the expected running set."
    }
}

function Assert-WorkspaceComposeState {
    foreach ($requiredPath in @($composeFile, $composeOverride)) {
        if (-not (Test-Path $requiredPath -PathType Leaf)) {
            throw "Workspace setup is incomplete."
        }
    }
    $baseArguments = @(
        "compose", "--project-name", $composeProject,
        "--file", $composeFile, "--file", $composeOverride
    )
    $configured = Invoke-WorkspaceVerificationCommand -FilePath "docker" `
        -ArgumentList ($baseArguments + @("config", "--services")) `
        -FailureMessage "Unable to inspect Workspace Compose configuration." `
        -TimeoutSeconds 30
    Assert-WorkspaceExactServices -Actual $configured

    $running = Invoke-WorkspaceVerificationCommand -FilePath "docker" `
        -ArgumentList ($baseArguments + @(
            "ps", "--status", "running", "--services"
        )) -FailureMessage "Unable to inspect running Workspace services." `
        -TimeoutSeconds 30
    Assert-WorkspaceExactServices -Actual $running
}

function Assert-WorkspaceLoopbackListeners {
    $listeners = @(
        Get-NetTCPConnection -State Listen -ErrorAction Stop |
            Where-Object { $_.LocalPort -in 8000, 1420 }
    )
    foreach ($port in @(8000, 1420)) {
        $portListeners = @($listeners | Where-Object { $_.LocalPort -eq $port })
        if (
            $portListeners.Count -eq 0 -or
            @($portListeners | Where-Object {
                $_.LocalAddress -ne "127.0.0.1"
            }).Count -gt 0
        ) {
            throw "Workspace listener validation failed."
        }
    }
}

function Assert-WorkspaceHealth {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Uri,
        [ValidateRange(1, 30)][int]$Attempts = 3
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Uri `
                -ConnectionTimeoutSeconds 3 -OperationTimeoutSeconds 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                return
            }
        } catch {
            if ($attempt -eq $Attempts) {
                throw "$Name health check failed after $Attempts attempts."
            }
        }
        Start-Sleep -Milliseconds 250
    }
    throw "$Name health check failed after $Attempts attempts."
}

function Assert-WorkspaceManagedAdminLogin {
    param([Parameter(Mandatory)][pscustomobject]$Credential)

    $requestBody = @{
        email = $Credential.Email
        password = $Credential.Password
        remember = $false
    } | ConvertTo-Json -Compress
    try {
        $response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:8000/pro/login" -Method Post `
            -ContentType "application/json" -Body $requestBody `
            -ConnectionTimeoutSeconds 3 -OperationTimeoutSeconds 10
        if ($response.StatusCode -ne 200) {
            throw "Unexpected status."
        }
    } catch {
        throw "Workspace managed administrator login check failed."
    }
}

function Get-WorkspaceHeaderValue {
    param(
        [Parameter(Mandatory)][object]$Headers,
        [Parameter(Mandatory)][string]$Name
    )

    $value = $Headers[$Name]
    if ($null -eq $value) {
        return ""
    }
    return [string]($value -join ",")
}

function Assert-WorkspaceCorsContractCore {
    $preflightHeaders = @{
        "Access-Control-Request-Method" = "POST"
        "Access-Control-Request-Headers" = "content-type"
    }
    $allowedOrigin = "http://127.0.0.1:1420"
    $allowedResponse = Invoke-WebRequest `
        -Uri "http://127.0.0.1:8000/pro/login" -Method Options `
        -Headers ($preflightHeaders + @{ Origin = $allowedOrigin }) `
        -SkipHttpErrorCheck -ConnectionTimeoutSeconds 3 `
        -OperationTimeoutSeconds 5
    if (
        $allowedResponse.StatusCode -ne 200 -or
        (Get-WorkspaceHeaderValue -Headers $allowedResponse.Headers `
            -Name "Access-Control-Allow-Origin") -ne $allowedOrigin
    ) {
        throw "Workspace allowed-origin CORS check failed."
    }

    $rejectedResponse = Invoke-WebRequest `
        -Uri "http://127.0.0.1:8000/pro/login" -Method Options `
        -Headers ($preflightHeaders + @{ Origin = "http://localhost:1420" }) `
        -SkipHttpErrorCheck -ConnectionTimeoutSeconds 3 `
        -OperationTimeoutSeconds 5
    if (
        $rejectedResponse.StatusCode -ne 400 -or
        (Get-WorkspaceHeaderValue -Headers $rejectedResponse.Headers `
            -Name "Access-Control-Allow-Origin")
    ) {
        throw "Workspace rejected-origin CORS check failed."
    }
}

function Assert-WorkspaceCorsContract {
    try {
        Assert-WorkspaceCorsContractCore
    } catch {
        throw "Workspace CORS verification failed."
    }
}

function Assert-WorkspaceSourceAndRuntimeState {
    $gitlink = Invoke-WorkspaceVerificationCommand -FilePath "git" `
        -ArgumentList @(
            "-C", $repoRoot, "ls-tree", "HEAD", "third_party/workspace"
        ) -FailureMessage "Unable to inspect the pinned Workspace source." `
        -TimeoutSeconds 15
    if (
        ($gitlink -join "") -notmatch
            '^160000 commit ([0-9a-f]{40})\s+third_party/workspace$'
    ) {
        throw "Workspace gitlink validation failed."
    }
    $expectedCommit = $Matches[1]
    $actualCommitOutput = @(
        Invoke-WorkspaceVerificationCommand -FilePath "git" -ArgumentList @(
            "-C", $workspaceRoot, "rev-parse", "HEAD"
        ) -FailureMessage "Unable to inspect the Workspace source commit." `
            -TimeoutSeconds 15
    )
    $actualCommit = ([string]$actualCommitOutput[0]).Trim()
    if ($actualCommit -ne $expectedCommit) {
        throw "Workspace source does not match the pinned commit."
    }
    $sourceChanges = @(
        Invoke-WorkspaceVerificationCommand -FilePath "git" -ArgumentList @(
            "-C", $workspaceRoot, "status", "--short",
            "--untracked-files=all"
        ) -FailureMessage "Unable to inspect Workspace source cleanliness." `
            -TimeoutSeconds 15
    )
    if ($sourceChanges.Count -gt 0) {
        throw (
            "Workspace submodule contains tracked or unexpected " +
            "untracked changes."
        )
    }

    foreach ($runtimePath in @(
        "backend-api/backend/envs/.env.sqlite",
        "backend-api/backend/workspace-compose.secrets",
        "backend-api/backend/workspace-admin-config.secrets",
        "backend-api/backend/workspace-admin-credentials.secrets",
        "backend-api/backend/local_storage/",
        "terminalpro/.env.local"
    )) {
        $null = Invoke-WorkspaceVerificationCommand -FilePath "git" `
            -ArgumentList @(
                "-C", $workspaceRoot, "check-ignore", "-q", "--", $runtimePath
            ) -FailureMessage "A Workspace runtime path is not ignored." `
                -TimeoutSeconds 15
    }

    if (-not (Test-Path (Join-Path $frontendRoot "bun.lock") -PathType Leaf)) {
        throw "Workspace Bun lockfile is missing."
    }
    if (Test-Path (Join-Path $frontendRoot "package-lock.json")) {
        throw "Generated package-lock.json must be absent."
    }
}

function Invoke-SelfHostedWorkspaceTest {
    Assert-WorkspaceComposeState
    Assert-WorkspaceLoopbackListeners
    Assert-WorkspaceHealth -Name "backend" `
        -Uri "http://127.0.0.1:8000/health"
    Assert-WorkspaceHealth -Name "frontend" `
        -Uri "http://127.0.0.1:1420"
    Assert-WorkspaceSourceAndRuntimeState

    $null = Invoke-WorkspaceVerificationCommand -FilePath "git" `
        -ArgumentList @(
            "-C", $workspaceRoot, "check-ignore", "-q", "--",
            "backend-api/backend/workspace-admin-credentials.secrets"
        ) -FailureMessage "Workspace administrator credentials are not ignored." `
            -TimeoutSeconds 15
    if (-not (Test-Path $adminCredentials -PathType Leaf)) {
        throw "Workspace setup is incomplete."
    }
    try {
        $credential = Get-Content $adminCredentials -Raw | ConvertFrom-Json
    } catch {
        throw "Workspace administrator credential file is invalid."
    }
    Assert-WorkspaceManagedAdminLogin -Credential $credential
    Assert-WorkspaceCorsContract
    Write-Host (
        "Self-hosted Workspace verification passed: exact services, " +
        "loopback listeners, health, login, CORS, and source state."
    )
}

if ($MyInvocation.InvocationName -ne ".") {
    try {
        Invoke-SelfHostedWorkspaceTest
    } catch {
        Write-Error "Verification failed: $($_.Exception.Message)"
        exit 1
    }
}
