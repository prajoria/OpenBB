using Microsoft.Extensions.Options;
using Microsoft.Extensions.Logging.EventLog;
using System.Runtime.Versioning;
using OpenBB.ServiceHost.Configuration;
using OpenBB.ServiceHost.Health;
using OpenBB.ServiceHost.Logging;
using OpenBB.ServiceHost.Processes;

namespace OpenBB.ServiceHost;

public static class Program
{
    public static Task<int> Main(string[] args) => ServiceHostApplication.RunAsync(args);
}

public static class ServiceHostApplication
{
    public static async Task<int> RunAsync(
        string[] args,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(args);

        var validateOnly = args.Contains("--validate-config", StringComparer.OrdinalIgnoreCase);
        var doctor = args.Any(
            argument => string.Equals(argument, "doctor", StringComparison.OrdinalIgnoreCase));
        var configurationPath = ReadConfigurationPath(args);
        var builder = Host.CreateApplicationBuilder(args);
        builder.Configuration.AddJsonFile(
            configurationPath,
            optional: false,
            reloadOnChange: false);
        builder.Services.AddServiceHostOptions(
            builder.Configuration.GetSection(ServiceHostOptions.SectionName));
        builder.Services.AddSingleton(serviceProvider =>
        {
            var options = serviceProvider
                .GetRequiredService<IOptions<ServiceHostOptions>>()
                .Value;
            var configuredValues = options.Components
                .SelectMany(component => component.Environment)
                .Where(variable => SecretRedactor.IsSecretVariableName(variable.Key))
                .Select(variable => variable.Value)
                .ToList();
            if (!string.IsNullOrWhiteSpace(options.EnvironmentFile) &&
                File.Exists(options.EnvironmentFile))
            {
                configuredValues.AddRange(
                    SecretRedactor.LoadEnvironmentFile(options.EnvironmentFile).Values);
            }

            return new SecretRedactor(configuredValues);
        });
        builder.Services.AddSingleton(serviceProvider =>
        {
            var options = serviceProvider
                .GetRequiredService<IOptions<ServiceHostOptions>>()
                .Value;
            return new ComponentLogWriter(
                options.LogDirectory,
                serviceProvider.GetRequiredService<SecretRedactor>());
        });
        builder.Services.AddSingleton<ILoggerProvider, ComponentFileLoggerProvider>();
        builder.Services.AddSingleton<HttpClient>();
        builder.Services.AddSingleton<IReadOnlyList<IComponentProbe>>(serviceProvider =>
            ComponentProbeFactory.Create(
                serviceProvider.GetRequiredService<IOptions<ServiceHostOptions>>().Value,
                serviceProvider.GetRequiredService<HttpClient>()));

        if (!validateOnly && !doctor)
        {
            builder.Services.AddWindowsService(options =>
                options.ServiceName = "OpenBB Portfolio");
            builder.Services.AddSingleton<IChildProcessFactory, ChildProcessFactory>();
            builder.Services.AddSingleton<IComponentReadinessProbe, ConfiguredComponentReadinessProbe>();
            builder.Services.AddHostedService<ComponentSupervisor>();
            if (OperatingSystem.IsWindows())
            {
                AddWindowsEventLog(builder);
            }
        }

        using var host = builder.Build();
        var options = host.Services.GetRequiredService<IOptions<ServiceHostOptions>>().Value;
        ApplyEnvironmentFile(options);
        if (validateOnly)
        {
            return 0;
        }

        if (doctor)
        {
            var probes = host.Services.GetRequiredService<IReadOnlyList<IComponentProbe>>();
            var command = new DoctorCommand(probes, Console.Out);
            return await command
                .ExecuteAsync(
                    args.Contains("--json", StringComparer.OrdinalIgnoreCase),
                    cancellationToken)
                .ConfigureAwait(false);
        }

        await host.RunAsync(cancellationToken).ConfigureAwait(false);
        return Environment.ExitCode;
    }

    private static string ReadConfigurationPath(IReadOnlyList<string> args)
    {
        for (var index = 0; index < args.Count; index++)
        {
            if (!string.Equals(args[index], "--config", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            if (index + 1 >= args.Count || string.IsNullOrWhiteSpace(args[index + 1]))
            {
                throw new ArgumentException("--config requires a file path.", nameof(args));
            }

            return Path.GetFullPath(args[index + 1]);
        }

        return Path.Combine(AppContext.BaseDirectory, "service.json");
    }

    [SupportedOSPlatform("windows")]
    private static void AddWindowsEventLog(HostApplicationBuilder builder)
    {
        builder.Logging.AddEventLog(settings =>
            settings.SourceName = "OpenBB Portfolio");
        builder.Logging.AddFilter<EventLogLoggerProvider>(
            (category, _) => !string.Equals(
                category,
                typeof(ChildProcess).FullName,
                StringComparison.Ordinal));
    }

    private static void ApplyEnvironmentFile(ServiceHostOptions options)
    {
        if (string.IsNullOrWhiteSpace(options.EnvironmentFile))
        {
            return;
        }

        var environment = SecretRedactor.LoadEnvironmentFile(options.EnvironmentFile);
        foreach (var component in options.Components)
        {
            foreach (var (name, value) in environment)
            {
                component.Environment[name] = value;
            }
        }
    }
}
