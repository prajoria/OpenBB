using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace OpenBB.ServiceHost.Logging;

public sealed partial class ComponentLogWriter : IDisposable
{
    public const int DefaultMaxLineLength = 16_384;
    public const int DefaultRetentionDays = 14;
    public const long DefaultMaximumComponentBytes = 250L * 1024 * 1024;

    private static readonly UTF8Encoding Utf8NoBom = new(false);
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase
    };

    private readonly string _logDirectory;
    private readonly SecretRedactor _redactor;
    private readonly TimeProvider _timeProvider;
    private readonly int _maxLineLength;
    private readonly int _retentionDays;
    private readonly long _maximumComponentBytes;
    private readonly object _writeLock = new();
    private bool _disposed;

    public ComponentLogWriter(
        string logDirectory,
        SecretRedactor redactor,
        TimeProvider? timeProvider = null,
        int maxLineLength = DefaultMaxLineLength,
        int retentionDays = DefaultRetentionDays,
        long maximumComponentBytes = DefaultMaximumComponentBytes)
    {
        if (string.IsNullOrWhiteSpace(logDirectory))
        {
            throw new ArgumentException("Log directory is required.", nameof(logDirectory));
        }

        if (maxLineLength < 256)
        {
            throw new ArgumentOutOfRangeException(
                nameof(maxLineLength),
                "Maximum line length must be at least 256.");
        }

        _logDirectory = Path.GetFullPath(logDirectory);
        _redactor = redactor ?? throw new ArgumentNullException(nameof(redactor));
        _timeProvider = timeProvider ?? TimeProvider.System;
        _maxLineLength = maxLineLength;
        _retentionDays = retentionDays;
        _maximumComponentBytes = maximumComponentBytes;
        Directory.CreateDirectory(_logDirectory);
    }

    public Task WriteAsync(
        string component,
        LogLevel level,
        string eventName,
        string message,
        int? processId = null,
        int? restartCount = null,
        string? correlationId = null,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ObjectDisposedException.ThrowIf(_disposed, this);
        var timestamp = _timeProvider.GetUtcNow();
        var safeComponent = NormalizeComponent(component);
        var safeMessage = _redactor.Redact(message);
        var line = SerializeBounded(
            timestamp,
            level,
            safeComponent,
            eventName,
            safeMessage,
            processId,
            restartCount,
            correlationId);
        var path = Path.Combine(
            _logDirectory,
            $"{safeComponent}-{timestamp:yyyyMMdd}.log");

        lock (_writeLock)
        {
            cancellationToken.ThrowIfCancellationRequested();
            File.AppendAllText(path, line + Environment.NewLine, Utf8NoBom);
            ApplyRetention(safeComponent, timestamp);
        }

        return Task.CompletedTask;
    }

    public void Dispose() => _disposed = true;

    private string SerializeBounded(
        DateTimeOffset timestamp,
        LogLevel level,
        string component,
        string eventName,
        string message,
        int? processId,
        int? restartCount,
        string? correlationId)
    {
        var candidate = message;
        while (true)
        {
            var line = SerializeRecord(
                timestamp,
                level,
                component,
                eventName,
                candidate,
                processId,
                restartCount,
                correlationId);
            var byteCount = Utf8NoBom.GetByteCount(line);
            if (byteCount <= _maxLineLength)
            {
                return line;
            }

            if (candidate.Length == 0)
            {
                return SerializeFallbackRecord(timestamp, level);
            }

            var overflow = byteCount - _maxLineLength;
            var keep = Math.Max(0, candidate.Length - overflow - 1);
            candidate = keep > 0
                ? candidate[..keep] + "…"
                : string.Empty;
        }
    }

    private static string SerializeRecord(
        DateTimeOffset timestamp,
        LogLevel level,
        string component,
        string eventName,
        string message,
        int? processId,
        int? restartCount,
        string? correlationId) =>
        JsonSerializer.Serialize(
            new
            {
                timestamp,
                level = level.ToString(),
                component,
                processId,
                @event = eventName,
                restartCount,
                correlationId,
                message
            },
            JsonOptions);

    private static string SerializeFallbackRecord(
        DateTimeOffset timestamp,
        LogLevel level) =>
        JsonSerializer.Serialize(
            new
            {
                timestamp,
                level = level.ToString(),
                truncated = true
            },
            JsonOptions);

    private void ApplyRetention(string component, DateTimeOffset now)
    {
        var files = new DirectoryInfo(_logDirectory)
            .GetFiles($"{component}-????????.log")
            .OrderByDescending(file => file.Name, StringComparer.Ordinal)
            .ToList();
        var oldestAllowed = now.UtcDateTime.Date.AddDays(-_retentionDays + 1);
        long retainedBytes = 0;
        foreach (var file in files)
        {
            var dateText = file.Name.Substring(component.Length + 1, 8);
            var keepByDate = DateTime.TryParseExact(
                dateText,
                "yyyyMMdd",
                System.Globalization.CultureInfo.InvariantCulture,
                System.Globalization.DateTimeStyles.AssumeUniversal,
                out var date) && date >= oldestAllowed;
            var nextRetainedBytes = retainedBytes + file.Length;
            if (!keepByDate || nextRetainedBytes > _maximumComponentBytes)
            {
                file.Delete();
                continue;
            }

            retainedBytes = nextRetainedBytes;
        }
    }

    private static string NormalizeComponent(string component)
    {
        if (string.IsNullOrWhiteSpace(component))
        {
            return "service-host";
        }

        var normalized = InvalidComponentCharacterRegex().Replace(component, "-");
        return normalized.Trim('-') is { Length: > 0 } value
            ? value
            : "service-host";
    }

    [GeneratedRegex(@"[^A-Za-z0-9._-]+", RegexOptions.CultureInvariant)]
    private static partial Regex InvalidComponentCharacterRegex();
}

public sealed class ComponentFileLoggerProvider(ComponentLogWriter writer)
    : ILoggerProvider
{
    public ILogger CreateLogger(string categoryName) =>
        new ComponentFileLogger(writer, categoryName);

    public void Dispose() => writer.Dispose();

    private sealed class ComponentFileLogger(
        ComponentLogWriter writer,
        string categoryName) : ILogger
    {
        public IDisposable? BeginScope<TState>(TState state)
            where TState : notnull => NullScope.Instance;

        public bool IsEnabled(LogLevel logLevel) => logLevel != LogLevel.None;

        public void Log<TState>(
            LogLevel logLevel,
            EventId eventId,
            TState state,
            Exception? exception,
            Func<TState, Exception?, string> formatter)
        {
            if (!IsEnabled(logLevel))
            {
                return;
            }

            var values = state as IEnumerable<KeyValuePair<string, object?>>;
            var component = GetValue(values, "Component") ?? "service-host";
            int? processId = int.TryParse(
                GetValue(values, "ProcessId"),
                out var parsedProcessId)
                ? parsedProcessId
                : null;
            int? restartCount = int.TryParse(
                GetValue(values, "RestartCount"),
                out var parsedRestartCount)
                ? parsedRestartCount
                : null;
            var message = formatter(state, exception);
            if (exception is not null)
            {
                message = $"{message} {exception}";
            }

            writer.WriteAsync(
                    component,
                    logLevel,
                    eventId.Name ?? categoryName,
                    message,
                    processId,
                    restartCount,
                    GetValue(values, "CorrelationId"))
                .GetAwaiter()
                .GetResult();
        }

        private static string? GetValue(
            IEnumerable<KeyValuePair<string, object?>>? values,
            string key) =>
            values?
                .FirstOrDefault(
                    pair => string.Equals(
                        pair.Key,
                        key,
                        StringComparison.OrdinalIgnoreCase))
                .Value?
                .ToString();
    }

    private sealed class NullScope : IDisposable
    {
        public static NullScope Instance { get; } = new();

        public void Dispose()
        {
        }
    }
}
