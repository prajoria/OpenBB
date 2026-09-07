using OpenBB.ServiceHost.Configuration;

namespace OpenBB.ServiceHost.Processes;

public static class OpenBBComponents
{
    private static readonly TimeSpan[] RestartDelays =
    [
        TimeSpan.FromSeconds(2),
        TimeSpan.FromSeconds(10),
        TimeSpan.FromSeconds(30)
    ];

    public static IReadOnlyList<ComponentOptions> Create(
        string pythonExecutable,
        string workingDirectory,
        IReadOnlyDictionary<string, string>? environment = null)
    {
        if (!Path.IsPathFullyQualified(pythonExecutable))
        {
            throw new ArgumentException(
                "The Python executable must be an absolute path.",
                nameof(pythonExecutable));
        }

        if (!Path.IsPathFullyQualified(workingDirectory))
        {
            throw new ArgumentException(
                "The working directory must be an absolute path.",
                nameof(workingDirectory));
        }

        var childEnvironment = environment is null
            ? new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            : new Dictionary<string, string>(environment, StringComparer.OrdinalIgnoreCase);
        childEnvironment["OPENBB_INSTALLED_SERVICE"] = "true";

        return
        [
            Component(
                "jobs-worker",
                pythonExecutable,
                workingDirectory,
                [
                    "-m",
                    "openbb_core.app.jobs.worker",
                    "worker",
                    "--poll-seconds",
                    "5"
                ],
                childEnvironment,
                startupOrder: 10,
                gracefulShutdownTimeout: TimeSpan.FromMinutes(10)),
            Component(
                "portfolio-api",
                pythonExecutable,
                workingDirectory,
                [
                    "-m",
                    "openbb_platform_api.main",
                    "--app",
                    "openbb_platform/extensions/portfolio/launch.py",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "6902"
                ],
                childEnvironment,
                startupOrder: 20,
                bindAddress: "127.0.0.1",
                port: 6902),
            Component(
                "portfolio-intel-ux",
                pythonExecutable,
                workingDirectory,
                [
                    "-m",
                    "uvicorn",
                    "openbb_portfolio_intel.widget_backend.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "6120"
                ],
                childEnvironment,
                startupOrder: 30,
                bindAddress: "127.0.0.1",
                port: 6120)
        ];
    }

    public static void EnsureInstalledServiceArguments(
        IReadOnlyCollection<string> arguments)
    {
        ArgumentNullException.ThrowIfNull(arguments);
        if (arguments.Any(
                argument => string.Equals(
                    argument,
                    "--reload",
                    StringComparison.OrdinalIgnoreCase)))
        {
            throw new ArgumentException(
                "--reload is not allowed in installed-service mode.",
                nameof(arguments));
        }
    }

    private static ComponentOptions Component(
        string name,
        string executable,
        string workingDirectory,
        IReadOnlyCollection<string> arguments,
        IReadOnlyDictionary<string, string> environment,
        int startupOrder,
        string? bindAddress = null,
        int? port = null,
        TimeSpan? gracefulShutdownTimeout = null)
    {
        EnsureInstalledServiceArguments(arguments);
        return new ComponentOptions
        {
            Name = name,
            ExecutablePath = executable,
            Arguments = [.. arguments],
            WorkingDirectory = workingDirectory,
            BindAddress = bindAddress,
            Port = port,
            StartupOrder = startupOrder,
            Required = true,
            ReadinessTimeout = TimeSpan.FromSeconds(60),
            GracefulShutdownTimeout =
                gracefulShutdownTimeout ?? TimeSpan.FromSeconds(30),
            RestartWindow = TimeSpan.FromMinutes(5),
            MaxRestarts = RestartDelays.Length,
            RestartDelays = [.. RestartDelays],
            Environment = new Dictionary<string, string>(
                environment,
                StringComparer.OrdinalIgnoreCase)
        };
    }
}
