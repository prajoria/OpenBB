using System.Diagnostics;
using System.Text.Json;

namespace OpenBB.ServiceHost.Health;

public sealed record ProbeResult(
    string Component,
    bool IsHealthy,
    string? Detail = null,
    TimeSpan? Duration = null,
    double? WorkerHeartbeatAgeSeconds = null,
    JsonElement? Payload = null);

public interface IComponentProbe
{
    string Component { get; }

    Task<ProbeResult> CheckAsync(bool startup, CancellationToken cancellationToken);
}

public sealed class HttpComponentProbe(
    string component,
    HttpClient httpClient,
    IReadOnlyList<Uri> endpoints,
    TimeSpan timeout,
    int startupAttempts = 3,
    TimeSpan? startupRetryDelay = null,
    bool requireJson = false) : IComponentProbe
{
    private readonly TimeSpan _startupRetryDelay = startupRetryDelay ?? TimeSpan.FromSeconds(1);

    public string Component { get; } =
        !string.IsNullOrWhiteSpace(component)
            ? component
            : throw new ArgumentException("Component is required.", nameof(component));

    public async Task<ProbeResult> CheckAsync(
        bool startup,
        CancellationToken cancellationToken)
    {
        if (endpoints.Count == 0)
        {
            return new ProbeResult(Component, false, "No health endpoints are configured.");
        }

        var attempts = startup ? Math.Max(1, startupAttempts) : 1;
        ProbeResult? lastResult = null;
        for (var attempt = 1; attempt <= attempts; attempt++)
        {
            lastResult = await CheckOnceAsync(cancellationToken).ConfigureAwait(false);
            if (lastResult.IsHealthy || attempt == attempts)
            {
                return lastResult;
            }

            if (_startupRetryDelay > TimeSpan.Zero)
            {
                await Task.Delay(_startupRetryDelay, cancellationToken).ConfigureAwait(false);
            }
        }

        return lastResult!;
    }

    private async Task<ProbeResult> CheckOnceAsync(CancellationToken cancellationToken)
    {
        var started = Stopwatch.GetTimestamp();
        using var timeoutSource = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutSource.CancelAfter(timeout);

        try
        {
            JsonElement? payload = null;
            foreach (var endpoint in endpoints)
            {
                using var response = await httpClient
                    .GetAsync(endpoint, HttpCompletionOption.ResponseHeadersRead, timeoutSource.Token)
                    .ConfigureAwait(false);
                if (!response.IsSuccessStatusCode)
                {
                    return Failed(
                        $"GET {endpoint} returned HTTP {(int)response.StatusCode}.",
                        started);
                }

                if (requireJson)
                {
                    var content = await response.Content
                        .ReadAsStringAsync(timeoutSource.Token)
                        .ConfigureAwait(false);
                    try
                    {
                        using var document = JsonDocument.Parse(content);
                        payload = document.RootElement.Clone();
                    }
                    catch (JsonException exception)
                    {
                        return Failed(
                            $"GET {endpoint} returned malformed JSON: {exception.Message}",
                            started);
                    }
                }
            }

            return new ProbeResult(
                Component,
                true,
                Duration: Stopwatch.GetElapsedTime(started),
                Payload: payload);
        }
        catch (OperationCanceledException) when (
            timeoutSource.IsCancellationRequested && !cancellationToken.IsCancellationRequested)
        {
            return Failed($"Probe timed out after {timeout}.", started);
        }
        catch (HttpRequestException exception)
        {
            return Failed(exception.Message, started);
        }
    }

    private ProbeResult Failed(string detail, long started) =>
        new(Component, false, detail, Stopwatch.GetElapsedTime(started));
}
