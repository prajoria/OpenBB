using System.Diagnostics;

namespace OpenBB.ServiceHost.Processes;

public interface IChildProcess : IAsyncDisposable
{
    ComponentDefinition Definition { get; }

    int Id { get; }

    bool HasExited { get; }

    Task StartAsync(CancellationToken cancellationToken);

    Task<int> WaitForExitAsync(CancellationToken cancellationToken);

    Task StopAsync(CancellationToken cancellationToken);
}

public interface IChildProcessFactory
{
    IChildProcess Create(ComponentDefinition definition);
}

public sealed class ChildProcessFactory(ILoggerFactory loggerFactory) : IChildProcessFactory
{
    public IChildProcess Create(ComponentDefinition definition) =>
        new ChildProcess(definition, loggerFactory.CreateLogger<ChildProcess>());
}

public sealed class ChildProcess(
    ComponentDefinition definition,
    ILogger<ChildProcess> logger) : IChildProcess
{
    private static readonly string[] UnsafeInheritedEnvironmentVariables =
    [
        "CORECLR_ENABLE_PROFILING",
        "CORECLR_PROFILER",
        "CORECLR_PROFILER_PATH",
        "COR_ENABLE_PROFILING",
        "COR_PROFILER",
        "COR_PROFILER_PATH",
        "DOTNET_ADDITIONAL_DEPS",
        "DOTNET_SHARED_STORE",
        "DOTNET_STARTUP_HOOKS",
        "PYTHONINSPECT",
        "PYTHONSTARTUP"
    ];

    private Process? _process;
    private bool _disposed;

    public ComponentDefinition Definition { get; } = definition;

    public int Id => GetProcess().Id;

    public bool HasExited
    {
        get
        {
            var process = _process;
            return process is not null && process.HasExited;
        }
    }

    public Task StartAsync(CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        cancellationToken.ThrowIfCancellationRequested();
        if (_process is not null)
        {
            throw new InvalidOperationException(
                $"Component '{Definition.Name}' has already been started.");
        }

        var process = new Process
        {
            StartInfo = CreateStartInfo(),
            EnableRaisingEvents = true
        };
        process.OutputDataReceived += (_, eventArgs) =>
        {
            if (eventArgs.Data is not null)
            {
                logger.LogInformation("[{Component}] {Output}", Definition.Name, eventArgs.Data);
            }
        };
        process.ErrorDataReceived += (_, eventArgs) =>
        {
            if (eventArgs.Data is not null)
            {
                logger.LogWarning("[{Component}] {Output}", Definition.Name, eventArgs.Data);
            }
        };

        try
        {
            if (!process.Start())
            {
                throw new InvalidOperationException(
                    $"Could not start component '{Definition.Name}'.");
            }

            _process = process;
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            logger.LogInformation(
                "Started component {Component} with process id {ProcessId}.",
                Definition.Name,
                process.Id);
            return Task.CompletedTask;
        }
        catch
        {
            process.Dispose();
            throw;
        }
    }

    public async Task<int> WaitForExitAsync(CancellationToken cancellationToken)
    {
        var process = GetProcess();
        await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
        return process.ExitCode;
    }

    public async Task StopAsync(CancellationToken cancellationToken)
    {
        var process = _process;
        if (process is null || process.HasExited)
        {
            return;
        }

        if (process.CloseMainWindow())
        {
            using var gracefulTimeout = new CancellationTokenSource(
                Definition.GracefulShutdownTimeout);
            try
            {
                await process.WaitForExitAsync(gracefulTimeout.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (gracefulTimeout.IsCancellationRequested)
            {
                // Escalate below.
            }
        }

        if (!process.HasExited)
        {
            logger.LogWarning(
                "Forcefully terminating component {Component} process tree.",
                Definition.Name);
            process.Kill(entireProcessTree: true);
            await process.WaitForExitAsync(CancellationToken.None).ConfigureAwait(false);
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }

        await StopAsync(CancellationToken.None).ConfigureAwait(false);
        _process?.Dispose();
        _disposed = true;
    }

    private ProcessStartInfo CreateStartInfo()
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = Definition.ExecutablePath,
            WorkingDirectory = Definition.WorkingDirectory,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };
        foreach (var argument in Definition.Arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        foreach (var variableName in UnsafeInheritedEnvironmentVariables)
        {
            startInfo.Environment.Remove(variableName);
        }

        foreach (var (variableName, value) in Definition.Environment)
        {
            startInfo.Environment[variableName] = value;
        }

        return startInfo;
    }

    private Process GetProcess() =>
        _process
        ?? throw new InvalidOperationException(
            $"Component '{Definition.Name}' has not been started.");
}
