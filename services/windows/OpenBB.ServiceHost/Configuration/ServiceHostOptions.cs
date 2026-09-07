namespace OpenBB.ServiceHost.Configuration;

public sealed class ServiceHostOptions
{
    public const string SectionName = "serviceHost";
    public const int CurrentSchemaVersion = 1;

    public int SchemaVersion { get; set; }

    public string? EnvironmentFile { get; set; }

    public string LogDirectory { get; set; } =
        Path.Combine(AppContext.BaseDirectory, "logs");

    public List<ComponentOptions> Components { get; set; } = [];
}

public sealed class ComponentOptions
{
    public string Name { get; set; } = string.Empty;

    public string ExecutablePath { get; set; } = string.Empty;

    public List<string> Arguments { get; set; } = [];

    public string WorkingDirectory { get; set; } = string.Empty;

    public string? BindAddress { get; set; }

    public int? Port { get; set; }

    public int StartupOrder { get; set; }

    public bool Required { get; set; } = true;

    public TimeSpan ReadinessTimeout { get; set; } = TimeSpan.FromSeconds(60);

    public TimeSpan GracefulShutdownTimeout { get; set; } = TimeSpan.FromSeconds(30);

    public TimeSpan RestartWindow { get; set; } = TimeSpan.FromMinutes(5);

    public int MaxRestarts { get; set; } = 3;

    public List<TimeSpan> RestartDelays { get; set; } = [];

    public Dictionary<string, string> Environment { get; set; } =
        new(StringComparer.OrdinalIgnoreCase);
}
