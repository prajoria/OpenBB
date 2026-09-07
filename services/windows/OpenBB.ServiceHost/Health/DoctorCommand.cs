using System.Text.Json;
using OpenBB.ServiceHost.Configuration;

namespace OpenBB.ServiceHost.Health;

public sealed class DoctorCommand(
    IReadOnlyCollection<IComponentProbe> probes,
    TextWriter output)
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true
    };

    public async Task<int> ExecuteAsync(bool json, CancellationToken cancellationToken)
    {
        var results = new Dictionary<string, ProbeResult>(StringComparer.OrdinalIgnoreCase);
        foreach (var probe in probes)
        {
            results[probe.Component] = await probe
                .CheckAsync(startup: false, cancellationToken)
                .ConfigureAwait(false);
        }

        var healthy = results.Values.All(result => result.IsHealthy);
        if (json)
        {
            var payload = new
            {
                healthy,
                checkedAt = DateTimeOffset.UtcNow,
                components = results.ToDictionary(
                    pair => pair.Key,
                    pair => new
                    {
                        healthy = pair.Value.IsHealthy,
                        detail = pair.Value.Detail,
                        durationMilliseconds = pair.Value.Duration?.TotalMilliseconds,
                        workerHeartbeatAgeSeconds = pair.Value.WorkerHeartbeatAgeSeconds
                    },
                    StringComparer.OrdinalIgnoreCase)
            };
            await output.WriteLineAsync(JsonSerializer.Serialize(payload, JsonOptions))
                .ConfigureAwait(false);
        }
        else
        {
            foreach (var result in results.Values)
            {
                await output.WriteLineAsync(
                        $"{result.Component}: {(result.IsHealthy ? "healthy" : "unhealthy")}" +
                        (result.Detail is null ? string.Empty : $" - {result.Detail}"))
                    .ConfigureAwait(false);
            }
        }

        return healthy ? 0 : 1;
    }
}

public static class ComponentProbeFactory
{
    private const string PortfolioApi = "portfolio-api";
    private const string PortfolioIntel = "portfolio-intel-ux";
    private const string JobsWorker = "jobs-worker";

    public static IReadOnlyList<IComponentProbe> Create(
        ServiceHostOptions options,
        HttpClient httpClient)
    {
        ArgumentNullException.ThrowIfNull(options);
        ArgumentNullException.ThrowIfNull(httpClient);

        var probes = new List<IComponentProbe>();
        var api = Find(options, PortfolioApi);
        if (api?.Port is { } apiPort)
        {
            var apiBase = BaseUri(api, apiPort);
            probes.Add(new HttpComponentProbe(
                PortfolioApi,
                httpClient,
                [new Uri(apiBase, "/api/v1/coverage/commands")],
                TimeSpan.FromSeconds(5),
                requireJson: true));

            if (Find(options, JobsWorker) is not null)
            {
                probes.Add(new JobsHeartbeatProbe(
                    JobsWorker,
                    httpClient,
                    new Uri(apiBase, "/api/v1/jobs/health"),
                    TimeSpan.FromSeconds(90),
                    TimeSpan.FromSeconds(5)));
            }
        }

        var web = Find(options, PortfolioIntel);
        if (web?.Port is { } webPort)
        {
            var webBase = BaseUri(web, webPort);
            probes.Add(new HttpComponentProbe(
                PortfolioIntel,
                httpClient,
                [
                    new Uri(webBase, "/widgets.json"),
                    new Uri(webBase, "/viewer")
                ],
                TimeSpan.FromSeconds(5)));
        }

        return probes;
    }

    private static ComponentOptions? Find(ServiceHostOptions options, string name) =>
        options.Components.FirstOrDefault(
            component => string.Equals(
                component.Name,
                name,
                StringComparison.OrdinalIgnoreCase));

    private static Uri BaseUri(ComponentOptions options, int port)
    {
        var host = string.IsNullOrWhiteSpace(options.BindAddress)
            ? "127.0.0.1"
            : options.BindAddress;
        return new Uri($"http://{host}:{port}/");
    }
}
