using System.Net;
using System.Text;
using OpenBB.ServiceHost.Health;

namespace OpenBB.ServiceHost.Tests;

public sealed class HealthProbeTests
{
    [Fact]
    public async Task Http_probe_reports_healthy_json_response()
    {
        var handler = new StubHttpHandler(
            _ => JsonResponse(HttpStatusCode.OK, """{"status":"ok"}"""));
        var probe = HttpProbe(handler);

        var result = await probe.CheckAsync(startup: false, CancellationToken.None);

        Assert.True(result.IsHealthy);
        Assert.Equal(1, handler.RequestCount);
    }

    [Fact]
    public async Task Http_probe_reports_failed_status_without_retrying_liveness()
    {
        var handler = new StubHttpHandler(
            _ => JsonResponse(HttpStatusCode.ServiceUnavailable, """{"status":"down"}"""));
        var probe = HttpProbe(handler);

        var result = await probe.CheckAsync(startup: false, CancellationToken.None);

        Assert.False(result.IsHealthy);
        Assert.Contains("503", result.Detail);
        Assert.Equal(1, handler.RequestCount);
    }

    [Fact]
    public async Task Http_probe_reports_timeout()
    {
        var handler = new StubHttpHandler(async request =>
        {
            await Task.Delay(Timeout.InfiniteTimeSpan, request.GetCancellationToken());
            return JsonResponse(HttpStatusCode.OK, "{}");
        });
        var probe = HttpProbe(handler, timeout: TimeSpan.FromMilliseconds(20));

        var result = await probe.CheckAsync(startup: false, CancellationToken.None);

        Assert.False(result.IsHealthy);
        Assert.Contains("timed out", result.Detail, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Http_probe_rejects_malformed_json()
    {
        var handler = new StubHttpHandler(
            _ => JsonResponse(HttpStatusCode.OK, "{not-json"));
        var probe = HttpProbe(handler);

        var result = await probe.CheckAsync(startup: false, CancellationToken.None);

        Assert.False(result.IsHealthy);
        Assert.Contains("JSON", result.Detail, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Http_probe_retries_only_during_startup()
    {
        var handler = new StubHttpHandler(request =>
            request.GetRequestNumber() < 3
                ? JsonResponse(HttpStatusCode.ServiceUnavailable, "{}")
                : JsonResponse(HttpStatusCode.OK, """{"status":"ok"}"""));
        var probe = HttpProbe(handler, startupAttempts: 3);

        var startup = await probe.CheckAsync(startup: true, CancellationToken.None);
        var liveness = await probe.CheckAsync(startup: false, CancellationToken.None);

        Assert.True(startup.IsHealthy);
        Assert.True(liveness.IsHealthy);
        Assert.Equal(4, handler.RequestCount);
    }

    [Theory]
    [InlineData(12, 30, true)]
    [InlineData(31, 30, false)]
    public async Task Jobs_probe_checks_worker_heartbeat_age(
        double heartbeatAge,
        double maximumAge,
        bool expectedHealthy)
    {
        var handler = new StubHttpHandler(
            _ => JsonResponse(
                HttpStatusCode.OK,
                $"{{\"queue_depth\":2,\"worker_heartbeat_age_seconds\":{heartbeatAge}," +
                "\"last_successful_run_by_job\":{}}"));
        var probe = new JobsHeartbeatProbe(
            "jobs-worker",
            new HttpClient(handler),
            new Uri("http://127.0.0.1:6902/jobs/health"),
            TimeSpan.FromSeconds(maximumAge),
            TimeSpan.FromSeconds(1));

        var result = await probe.CheckAsync(startup: false, CancellationToken.None);

        Assert.Equal(expectedHealthy, result.IsHealthy);
        Assert.Equal(heartbeatAge, result.WorkerHeartbeatAgeSeconds);
    }

    [Fact]
    public async Task Doctor_json_reports_every_probe_and_returns_nonzero_when_unhealthy()
    {
        var output = new StringWriter();
        var command = new DoctorCommand(
            [
                new FixedProbe(new ProbeResult("portfolio-api", true)),
                new FixedProbe(new ProbeResult(
                    "jobs-worker",
                    false,
                    "Worker heartbeat is stale.",
                    WorkerHeartbeatAgeSeconds: 120))
            ],
            output);

        var exitCode = await command.ExecuteAsync(json: true, CancellationToken.None);
        using var document = System.Text.Json.JsonDocument.Parse(output.ToString());

        Assert.Equal(1, exitCode);
        Assert.False(document.RootElement.GetProperty("healthy").GetBoolean());
        Assert.Equal(
            120,
            document.RootElement
                .GetProperty("components")
                .GetProperty("jobs-worker")
                .GetProperty("workerHeartbeatAgeSeconds")
                .GetDouble());
    }

    private static HttpComponentProbe HttpProbe(
        HttpMessageHandler handler,
        TimeSpan? timeout = null,
        int startupAttempts = 3) =>
        new(
            "portfolio-api",
            new HttpClient(handler),
            [new Uri("http://127.0.0.1:6902/health")],
            timeout ?? TimeSpan.FromSeconds(1),
            startupAttempts,
            TimeSpan.Zero,
            requireJson: true);

    private static HttpResponseMessage JsonResponse(HttpStatusCode status, string content) =>
        new(status)
        {
            Content = new StringContent(content, Encoding.UTF8, "application/json")
        };

    private sealed class FixedProbe(ProbeResult result) : IComponentProbe
    {
        public string Component => result.Component;

        public Task<ProbeResult> CheckAsync(
            bool startup,
            CancellationToken cancellationToken) =>
            Task.FromResult(result);
    }

    private sealed class StubHttpHandler(
        Func<HttpRequestMessage, HttpResponseMessage> responseFactory)
        : HttpMessageHandler
    {
        private int _requestCount;

        public StubHttpHandler(
            Func<HttpRequestMessage, Task<HttpResponseMessage>> responseFactory)
            : this(request => responseFactory(request).GetAwaiter().GetResult())
        {
        }

        public int RequestCount => _requestCount;

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            request.Options.Set(
                new HttpRequestOptionsKey<int>("request-number"),
                Interlocked.Increment(ref _requestCount));
            request.Options.Set(
                new HttpRequestOptionsKey<CancellationToken>("cancellation-token"),
                cancellationToken);
            return Task.FromResult(responseFactory(request));
        }
    }
}

internal static class HttpRequestMessageTestExtensions
{
    public static int GetRequestNumber(this HttpRequestMessage request) =>
        request.Options.TryGetValue(
            new HttpRequestOptionsKey<int>("request-number"),
            out var value)
            ? value
            : 0;

    public static CancellationToken GetCancellationToken(this HttpRequestMessage request) =>
        request.Options.TryGetValue(
            new HttpRequestOptionsKey<CancellationToken>("cancellation-token"),
            out var value)
            ? value
            : CancellationToken.None;
}
