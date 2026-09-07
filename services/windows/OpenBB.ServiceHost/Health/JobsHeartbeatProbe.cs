namespace OpenBB.ServiceHost.Health;

public sealed class JobsHeartbeatProbe : IComponentProbe
{
    private readonly HttpComponentProbe _httpProbe;
    private readonly TimeSpan _maximumHeartbeatAge;

    public JobsHeartbeatProbe(
        string component,
        HttpClient httpClient,
        Uri endpoint,
        TimeSpan maximumHeartbeatAge,
        TimeSpan timeout,
        int startupAttempts = 3,
        TimeSpan? startupRetryDelay = null)
    {
        Component = component;
        _maximumHeartbeatAge = maximumHeartbeatAge;
        _httpProbe = new HttpComponentProbe(
            component,
            httpClient,
            [endpoint],
            timeout,
            startupAttempts,
            startupRetryDelay,
            requireJson: true);
    }

    public string Component { get; }

    public async Task<ProbeResult> CheckAsync(
        bool startup,
        CancellationToken cancellationToken)
    {
        var response = await _httpProbe
            .CheckAsync(startup, cancellationToken)
            .ConfigureAwait(false);
        if (!response.IsHealthy || response.Payload is not { } payload)
        {
            return response;
        }

        if (!payload.TryGetProperty("worker_heartbeat_age_seconds", out var ageElement) ||
            ageElement.ValueKind != System.Text.Json.JsonValueKind.Number ||
            !ageElement.TryGetDouble(out var ageSeconds))
        {
            return response with
            {
                IsHealthy = false,
                Detail = "Jobs health response has no current worker heartbeat age."
            };
        }

        if (ageSeconds > _maximumHeartbeatAge.TotalSeconds)
        {
            return response with
            {
                IsHealthy = false,
                Detail =
                    $"Worker heartbeat age {ageSeconds:F1}s exceeds " +
                    $"{_maximumHeartbeatAge.TotalSeconds:F1}s.",
                WorkerHeartbeatAgeSeconds = ageSeconds
            };
        }

        return response with { WorkerHeartbeatAgeSeconds = ageSeconds };
    }
}
