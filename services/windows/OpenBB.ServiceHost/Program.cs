using Microsoft.Extensions.Options;
using OpenBB.ServiceHost.Configuration;
using OpenBB.ServiceHost.Health;
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

        if (!validateOnly && !doctor)
        {
            builder.Services.AddWindowsService(options =>
                options.ServiceName = "OpenBB Portfolio");
            builder.Services.AddSingleton<IChildProcessFactory, ChildProcessFactory>();
            builder.Services.AddSingleton<IComponentReadinessProbe, ProcessStartedReadinessProbe>();
            builder.Services.AddHostedService<ComponentSupervisor>();
        }

        using var host = builder.Build();
        var options = host.Services.GetRequiredService<IOptions<ServiceHostOptions>>().Value;
        if (validateOnly)
        {
            return 0;
        }

        if (doctor)
        {
            using var httpClient = new HttpClient();
            var probes = ComponentProbeFactory.Create(options, httpClient);
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
}
