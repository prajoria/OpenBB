using Microsoft.Extensions.Configuration;

namespace OpenBB.ServiceHost.Configuration;

public sealed class ServiceHostOptions
{
    public const string SectionName = "serviceHost";
    public const int CurrentSchemaVersion = 1;

    [ConfigurationKeyName("schemaVersion")]
    public int SchemaVersion { get; set; }

    [ConfigurationKeyName("environmentFile")]
    public string? EnvironmentFile { get; set; }

    [ConfigurationKeyName("logDirectory")]
    public string LogDirectory { get; set; } =
        Path.Combine(AppContext.BaseDirectory, "logs");

    [ConfigurationKeyName("components")]
    public List<ComponentOptions> Components { get; set; } = [];
}

public sealed class ComponentOptions
{
    [ConfigurationKeyName("name")]
    public string Name { get; set; } = string.Empty;

    [ConfigurationKeyName("executablePath")]
    public string ExecutablePath { get; set; } = string.Empty;

    [ConfigurationKeyName("arguments")]
    public List<string> Arguments { get; set; } = [];

    [ConfigurationKeyName("workingDirectory")]
    public string WorkingDirectory { get; set; } = string.Empty;

    [ConfigurationKeyName("bindAddress")]
    public string? BindAddress { get; set; }

    [ConfigurationKeyName("port")]
    public int? Port { get; set; }

    [ConfigurationKeyName("startupOrder")]
    public int StartupOrder { get; set; }

    [ConfigurationKeyName("required")]
    public bool Required { get; set; } = true;

    [ConfigurationKeyName("readinessTimeout")]
    public TimeSpan ReadinessTimeout { get; set; } = TimeSpan.FromSeconds(60);

    [ConfigurationKeyName("gracefulShutdownTimeout")]
    public TimeSpan GracefulShutdownTimeout { get; set; } = TimeSpan.FromSeconds(30);

    [ConfigurationKeyName("restartWindow")]
    public TimeSpan RestartWindow { get; set; } = TimeSpan.FromMinutes(5);

    [ConfigurationKeyName("maxRestarts")]
    public int MaxRestarts { get; set; } = 3;

    [ConfigurationKeyName("restartDelays")]
    public List<TimeSpan> RestartDelays { get; set; } = [];

    [ConfigurationKeyName("environment")]
    public Dictionary<string, string> Environment { get; set; } =
        new(StringComparer.OrdinalIgnoreCase);
}
