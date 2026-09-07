using OpenBB.ServiceHost.Configuration;

namespace OpenBB.ServiceHost.Processes;

public sealed class ComponentDefinition
{
    public ComponentDefinition(ComponentOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);

        Name = options.Name;
        ExecutablePath = options.ExecutablePath;
        Arguments = [.. options.Arguments];
        WorkingDirectory = options.WorkingDirectory;
        Required = options.Required;
        StartupOrder = options.StartupOrder;
        ReadinessTimeout = options.ReadinessTimeout;
        GracefulShutdownTimeout = options.GracefulShutdownTimeout;
        RestartWindow = options.RestartWindow;
        MaxRestarts = options.MaxRestarts;
        RestartDelays = [.. options.RestartDelays];
        Environment = new Dictionary<string, string>(
            options.Environment,
            StringComparer.OrdinalIgnoreCase);
    }

    public string Name { get; }

    public string ExecutablePath { get; }

    public IReadOnlyList<string> Arguments { get; }

    public string WorkingDirectory { get; }

    public bool Required { get; }

    public int StartupOrder { get; }

    public TimeSpan ReadinessTimeout { get; }

    public TimeSpan GracefulShutdownTimeout { get; }

    public TimeSpan RestartWindow { get; }

    public int MaxRestarts { get; }

    public IReadOnlyList<TimeSpan> RestartDelays { get; }

    public IReadOnlyDictionary<string, string> Environment { get; }
}

public interface IComponentReadinessProbe
{
    Task WaitUntilReadyAsync(
        ComponentDefinition definition,
        IChildProcess process,
        CancellationToken cancellationToken);
}

public sealed class ProcessStartedReadinessProbe : IComponentReadinessProbe
{
    public async Task WaitUntilReadyAsync(
        ComponentDefinition definition,
        IChildProcess process,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        await Task.Yield();
        if (process.HasExited)
        {
            throw new InvalidOperationException(
                $"Component '{definition.Name}' exited before becoming ready.");
        }
    }
}
