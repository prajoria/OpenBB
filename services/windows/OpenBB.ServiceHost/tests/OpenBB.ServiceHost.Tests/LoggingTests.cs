using System.Text;
using Microsoft.Extensions.Logging;
using OpenBB.ServiceHost.Logging;

namespace OpenBB.ServiceHost.Tests;

public sealed class LoggingTests
{
    [Fact]
    public void Redacts_environment_values_bearer_tokens_queries_and_exceptions()
    {
        using var directory = new TestLogDirectory();
        var environmentPath = Path.Combine(directory.Path, "secrets.env");
        File.WriteAllText(
            environmentPath,
            """
            # protected settings
            FMP_API_KEY=fixture-api-secret
            PI_WIDGET_BACKEND_TOKEN="fixture-widget-secret"
            """,
            Encoding.UTF8);
        var redactor = SecretRedactor.FromEnvironmentFile(environmentPath);
        var exception = new InvalidOperationException(
            "request failed for fixture-api-secret");

        var value = redactor.Redact(
            $"Authorization: Bearer abc.def.ghi " +
            $"https://localhost/path?token=fixture-widget-secret " +
            exception);

        Assert.DoesNotContain("fixture-api-secret", value);
        Assert.DoesNotContain("fixture-widget-secret", value);
        Assert.DoesNotContain("abc.def.ghi", value);
        Assert.DoesNotContain("token=", value);
        Assert.Contains(SecretRedactor.Redacted, value);
    }

    [Fact]
    public async Task Writes_bounded_utf8_daily_component_logs_without_secrets()
    {
        using var directory = new TestLogDirectory();
        var clock = new MutableTimeProvider(
            new DateTimeOffset(2026, 9, 6, 10, 0, 0, TimeSpan.Zero));
        var writer = new ComponentLogWriter(
            directory.Path,
            new SecretRedactor(["fixture-secret"]),
            clock,
            maxLineLength: 512);

        await writer.WriteAsync(
            "portfolio-intel-ux",
            LogLevel.Information,
            "stdout",
            $"café Δ fixture-secret {new string('x', 2_000)}",
            processId: 42);
        clock.UtcNow = clock.UtcNow.AddDays(1);
        await writer.WriteAsync(
            "portfolio-intel-ux",
            LogLevel.Warning,
            "stderr",
            "second day");

        var firstPath = Path.Combine(
            directory.Path,
            "portfolio-intel-ux-20260906.log");
        var secondPath = Path.Combine(
            directory.Path,
            "portfolio-intel-ux-20260907.log");
        Assert.True(File.Exists(firstPath));
        Assert.True(File.Exists(secondPath));

        var bytes = await File.ReadAllBytesAsync(firstPath);
        var text = new UTF8Encoding(false, true).GetString(bytes);
        var line = Assert.Single(text.Split(Environment.NewLine, StringSplitOptions.RemoveEmptyEntries));
        Assert.True(line.Length <= 512);
        Assert.True(
            Encoding.UTF8.GetByteCount(line) <= 512,
            "UTF-8 encoded log line exceeded the configured bound.");
        Assert.Contains("café Δ", line);
        Assert.DoesNotContain("fixture-secret", line);
        Assert.DoesNotContain(Encoding.UTF8.GetPreamble(), bytes);
    }

    [Fact]
    public async Task Retention_counts_only_bytes_for_files_it_keeps()
    {
        using var directory = new TestLogDirectory();
        var component = "jobs-worker";
        var clock = new MutableTimeProvider(
            new DateTimeOffset(2026, 9, 6, 10, 0, 0, TimeSpan.Zero));
        var writer = new ComponentLogWriter(
            directory.Path,
            new SecretRedactor([]),
            clock,
            maxLineLength: 512,
            retentionDays: 2,
            maximumComponentBytes: 700);
        var futurePath = Path.Combine(directory.Path, $"{component}-20260907.log");
        var currentPath = Path.Combine(directory.Path, $"{component}-20260906.log");
        var expiredPath = Path.Combine(directory.Path, $"{component}-20260904.log");

        await File.WriteAllBytesAsync(futurePath, new byte[750]);
        await File.WriteAllBytesAsync(currentPath, new byte[100]);
        await File.WriteAllBytesAsync(expiredPath, new byte[50]);

        await writer.WriteAsync(component, LogLevel.Information, "stdout", "ok");

        Assert.False(File.Exists(futurePath));
        Assert.False(File.Exists(expiredPath));
        Assert.True(File.Exists(currentPath));
    }

    [Fact]
    public void Logger_provider_routes_structured_child_output_to_component_file()
    {
        using var directory = new TestLogDirectory();
        var writer = new ComponentLogWriter(
            directory.Path,
            new SecretRedactor(["fixture-secret"]),
            new MutableTimeProvider(
                new DateTimeOffset(2026, 9, 6, 10, 0, 0, TimeSpan.Zero)));
        using var provider = new ComponentFileLoggerProvider(writer);
        using var factory = LoggerFactory.Create(builder => builder.AddProvider(provider));
        var logger = factory.CreateLogger("OpenBB.ServiceHost.Processes.ChildProcess");

        logger.LogInformation(
            "[{Component}] {Output}",
            "jobs-worker",
            "connected with fixture-secret");

        var componentLog = File.ReadAllText(
            Path.Combine(directory.Path, "jobs-worker-20260906.log"),
            Encoding.UTF8);
        Assert.Contains("connected with", componentLog);
        Assert.DoesNotContain("fixture-secret", componentLog);
    }

    private sealed class MutableTimeProvider(DateTimeOffset utcNow) : TimeProvider
    {
        public DateTimeOffset UtcNow { get; set; } = utcNow;

        public override DateTimeOffset GetUtcNow() => UtcNow;
    }

    private sealed class TestLogDirectory : IDisposable
    {
        public TestLogDirectory()
        {
            Path = System.IO.Path.Combine(
                Environment.CurrentDirectory,
                "TestResults",
                Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path);
        }

        public string Path { get; }

        public void Dispose()
        {
            if (Directory.Exists(Path))
            {
                Directory.Delete(Path, recursive: true);
            }
        }
    }
}
