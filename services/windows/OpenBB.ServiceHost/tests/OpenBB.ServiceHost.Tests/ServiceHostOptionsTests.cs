using System.Text.Json;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using OpenBB.ServiceHost.Configuration;

namespace OpenBB.ServiceHost.Tests;

public sealed class ServiceHostOptionsTests
{
    private readonly ServiceHostOptionsValidator _validator = new();

    [Fact]
    public void Accepts_valid_versioned_configuration()
    {
        var result = Validate(ValidOptions());

        Assert.True(result.Succeeded);
    }

    [Fact]
    public void Rejects_unsupported_schema_version()
    {
        var options = ValidOptions();
        options.SchemaVersion = ServiceHostOptions.CurrentSchemaVersion + 1;

        var result = Validate(options);

        AssertFailure(result, "schemaVersion");
    }

    [Theory]
    [InlineData("ExecutablePath")]
    [InlineData("WorkingDirectory")]
    public void Rejects_relative_paths(string propertyName)
    {
        var options = ValidOptions();
        if (propertyName == "ExecutablePath")
        {
            options.Components[0].ExecutablePath = @".\python.exe";
        }
        else
        {
            options.Components[0].WorkingDirectory = @".\app";
        }

        var result = Validate(options);

        AssertFailure(result, propertyName);
    }

    [Theory]
    [InlineData("0.0.0.0")]
    [InlineData("192.168.1.10")]
    [InlineData("openbb.local")]
    public void Rejects_non_loopback_bindings(string bindAddress)
    {
        var options = ValidOptions();
        options.Components[0].BindAddress = bindAddress;

        var result = Validate(options);

        AssertFailure(result, "BindAddress");
    }

    [Theory]
    [InlineData("127.0.0.1")]
    [InlineData("127.20.30.40")]
    [InlineData("::1")]
    public void Accepts_loopback_bindings(string bindAddress)
    {
        var options = ValidOptions();
        options.Components[0].BindAddress = bindAddress;

        var result = Validate(options);

        Assert.True(result.Succeeded);
    }

    [Fact]
    public void Rejects_duplicate_ports()
    {
        var options = ValidOptions();
        options.Components.Add(ValidComponent("web", 6902, startupOrder: 2));

        var result = Validate(options);

        AssertFailure(result, "Port");
    }

    [Theory]
    [InlineData("ReadinessTimeout")]
    [InlineData("GracefulShutdownTimeout")]
    [InlineData("RestartWindow")]
    public void Rejects_non_positive_timeouts(string propertyName)
    {
        var options = ValidOptions();
        var component = options.Components[0];
        switch (propertyName)
        {
            case "ReadinessTimeout":
                component.ReadinessTimeout = TimeSpan.Zero;
                break;
            case "GracefulShutdownTimeout":
                component.GracefulShutdownTimeout = TimeSpan.Zero;
                break;
            case "RestartWindow":
                component.RestartWindow = TimeSpan.Zero;
                break;
        }

        var result = Validate(options);

        AssertFailure(result, propertyName);
    }

    [Fact]
    public void Rejects_restart_delay_count_that_differs_from_restart_budget()
    {
        var options = ValidOptions();
        options.Components[0].MaxRestarts = 2;

        var result = Validate(options);

        AssertFailure(result, "RestartDelays");
    }

    [Fact]
    public void Rejects_non_positive_restart_delays()
    {
        var options = ValidOptions();
        options.Components[0].RestartDelays[1] = TimeSpan.Zero;

        var result = Validate(options);

        AssertFailure(result, "RestartDelays");
    }

    [Fact]
    public void Strict_binding_rejects_unknown_configuration_keys()
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["serviceHost:schemaVersion"] = "1",
                ["serviceHost:unknownSetting"] = "not-allowed"
            })
            .Build();
        var services = new ServiceCollection();
        services.AddServiceHostOptions(configuration.GetSection(ServiceHostOptions.SectionName));

        using var provider = services.BuildServiceProvider();

        var exception = Assert.Throws<OptionsValidationException>(
            () => provider.GetRequiredService<IOptions<ServiceHostOptions>>().Value);
        Assert.Contains("unknownSetting", exception.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Validate_config_does_not_launch_components()
    {
        using var directory = new TestDirectory();
        var markerPath = Path.Combine(directory.Path, "launched.txt");
        var configPath = Path.Combine(directory.Path, "service.json");
        var options = ValidOptions();
        options.Components[0].ExecutablePath =
            Path.Combine(Environment.SystemDirectory, "cmd.exe");
        options.Components[0].Arguments = ["/c", $"echo launched>\"{markerPath}\""];
        options.Components[0].WorkingDirectory = directory.Path;
        await File.WriteAllTextAsync(
            configPath,
            JsonSerializer.Serialize(
                new Dictionary<string, object> { [ServiceHostOptions.SectionName] = options }));

        var exitCode = await ServiceHostApplication.RunAsync(
            ["--validate-config", "--config", configPath]);

        Assert.Equal(0, exitCode);
        Assert.False(File.Exists(markerPath));
    }

    [Fact]
    public async Task Run_command_is_accepted_and_stops_children_on_host_cancellation()
    {
        using var directory = new TestDirectory();
        var configPath = Path.Combine(directory.Path, "service.json");
        var options = ValidOptions();
        options.Components[0].ExecutablePath =
            Path.Combine(Environment.SystemDirectory, "cmd.exe");
        options.Components[0].Arguments = ["/c", "ping 127.0.0.1 -n 10 > nul"];
        options.Components[0].WorkingDirectory = directory.Path;
        options.Components[0].GracefulShutdownTimeout = TimeSpan.FromMilliseconds(25);
        await File.WriteAllTextAsync(
            configPath,
            JsonSerializer.Serialize(
                new Dictionary<string, object> { [ServiceHostOptions.SectionName] = options }));
        using var cancellation = new CancellationTokenSource(TimeSpan.FromMilliseconds(250));

        var exitCode = await ServiceHostApplication.RunAsync(
            ["run", "--config", configPath],
            cancellation.Token);

        Assert.Equal(0, exitCode);
    }

    private ValidateOptionsResult Validate(ServiceHostOptions options) =>
        _validator.Validate(Options.DefaultName, options);

    private static void AssertFailure(ValidateOptionsResult result, string expectedText)
    {
        Assert.True(result.Failed);
        Assert.Contains(result.Failures!, failure =>
            failure.Contains(expectedText, StringComparison.OrdinalIgnoreCase));
    }

    private static ServiceHostOptions ValidOptions() =>
        new()
        {
            SchemaVersion = ServiceHostOptions.CurrentSchemaVersion,
            Components = [ValidComponent("api", 6902, startupOrder: 1)]
        };

    private static ComponentOptions ValidComponent(string name, int port, int startupOrder) =>
        new()
        {
            Name = name,
            ExecutablePath = Path.Combine(Path.GetPathRoot(Environment.SystemDirectory)!, "tools", "python.exe"),
            Arguments = ["-m", "openbb"],
            WorkingDirectory = Path.Combine(Path.GetPathRoot(Environment.SystemDirectory)!, "OpenBB", "app"),
            BindAddress = "127.0.0.1",
            Port = port,
            StartupOrder = startupOrder,
            Required = true,
            ReadinessTimeout = TimeSpan.FromSeconds(60),
            GracefulShutdownTimeout = TimeSpan.FromSeconds(30),
            RestartWindow = TimeSpan.FromMinutes(5),
            MaxRestarts = 3,
            RestartDelays =
            [
                TimeSpan.FromSeconds(2),
                TimeSpan.FromSeconds(10),
                TimeSpan.FromSeconds(30)
            ]
        };

    private sealed class TestDirectory : IDisposable
    {
        public TestDirectory()
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
