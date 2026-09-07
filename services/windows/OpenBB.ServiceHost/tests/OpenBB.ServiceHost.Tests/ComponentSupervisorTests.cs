using System.Collections.Concurrent;
using System.Diagnostics;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using OpenBB.ServiceHost.Configuration;
using OpenBB.ServiceHost.Processes;

namespace OpenBB.ServiceHost.Tests;

[Collection(nameof(ProcessSupervisorCollection))]
public sealed class ComponentSupervisorTests
{
    [Fact]
    public async Task Starts_components_in_configured_order()
    {
        var events = new ConcurrentQueue<string>();
        var factory = new FakeChildProcessFactory(events);
        var supervisor = CreateSupervisor(
            [Component("web", 30), Component("worker", 10), Component("api", 20)],
            factory,
            new ImmediateReadinessProbe(),
            new FakeHostApplicationLifetime());

        await supervisor.StartAsync(CancellationToken.None);
        await supervisor.StopAsync(CancellationToken.None);

        Assert.Equal(
            ["start:worker", "start:api", "start:web"],
            events.Where(entry => entry.StartsWith("start:", StringComparison.Ordinal)));
    }

    [Fact]
    public async Task Readiness_timeout_stops_every_started_component()
    {
        var events = new ConcurrentQueue<string>();
        var factory = new FakeChildProcessFactory(events);
        var supervisor = CreateSupervisor(
            [Component("worker", 10), Component("api", 20, readinessMilliseconds: 25)],
            factory,
            new BlockingReadinessProbe("api"),
            new FakeHostApplicationLifetime());

        await Assert.ThrowsAsync<TimeoutException>(
            () => supervisor.StartAsync(CancellationToken.None));

        Assert.Equal(
            ["stop:api", "stop:worker"],
            events.Where(entry => entry.StartsWith("stop:", StringComparison.Ordinal)));
    }

    [Fact]
    public async Task Restarts_only_the_failed_component()
    {
        var factory = new FakeChildProcessFactory();
        var supervisor = CreateSupervisor(
            [Component("worker", 10), Component("api", 20)],
            factory,
            new ImmediateReadinessProbe(),
            new FakeHostApplicationLifetime());
        await supervisor.StartAsync(CancellationToken.None);

        factory.Created("api")[0].Exit(17);
        await WaitUntilAsync(() => factory.Created("api").Count == 2);

        Assert.Single(factory.Created("worker"));
        Assert.Equal(2, factory.Created("api").Count);
        await supervisor.StopAsync(CancellationToken.None);
    }

    [Fact]
    public async Task Applies_configured_restart_backoff()
    {
        var factory = new FakeChildProcessFactory();
        var supervisor = CreateSupervisor(
            [Component("api", 10, restartDelays: [TimeSpan.FromMilliseconds(120)])],
            factory,
            new ImmediateReadinessProbe(),
            new FakeHostApplicationLifetime());
        await supervisor.StartAsync(CancellationToken.None);
        var failedAt = Stopwatch.GetTimestamp();

        factory.Created("api")[0].Exit(17);
        await WaitUntilAsync(() => factory.Created("api").Count == 2);

        Assert.True(
            Stopwatch.GetElapsedTime(failedAt) >= TimeSpan.FromMilliseconds(90),
            $"Restart occurred after only {Stopwatch.GetElapsedTime(failedAt)}.");
        await supervisor.StopAsync(CancellationToken.None);
    }

    [Fact]
    public async Task Exhausting_required_restart_budget_stops_host_nonzero()
    {
        var originalExitCode = Environment.ExitCode;
        Environment.ExitCode = 0;
        try
        {
            var lifetime = new FakeHostApplicationLifetime();
            var factory = new FakeChildProcessFactory();
            var supervisor = CreateSupervisor(
                [Component("api", 10, restartDelays: [TimeSpan.FromMilliseconds(1)])],
                factory,
                new ImmediateReadinessProbe(),
                lifetime);
            await supervisor.StartAsync(CancellationToken.None);
            factory.Created("api")[0].Exit(17);
            await WaitUntilAsync(() => factory.Created("api").Count == 2);

            factory.Created("api")[1].Exit(17);
            await WaitUntilAsync(() => lifetime.ApplicationStopping.IsCancellationRequested);

            Assert.NotEqual(0, Environment.ExitCode);
            await supervisor.StopAsync(CancellationToken.None);
        }
        finally
        {
            Environment.ExitCode = originalExitCode;
        }
    }

    [Fact]
    public async Task Stops_components_in_reverse_startup_order()
    {
        var events = new ConcurrentQueue<string>();
        var factory = new FakeChildProcessFactory(events);
        var supervisor = CreateSupervisor(
            [Component("worker", 10), Component("api", 20), Component("web", 30)],
            factory,
            new ImmediateReadinessProbe(),
            new FakeHostApplicationLifetime());
        await supervisor.StartAsync(CancellationToken.None);

        await supervisor.StopAsync(CancellationToken.None);

        Assert.Equal(
            ["stop:web", "stop:api", "stop:worker"],
            events.Where(entry => entry.StartsWith("stop:", StringComparison.Ordinal)));
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task Cancelled_service_stop_still_cleans_up_children(bool preCancelStopToken)
    {
        var factory = new ControllableAsyncChildProcessFactory();
        var supervisor = CreateSupervisor(
            [Component("worker", 10)],
            factory,
            new ImmediateReadinessProbe(),
            new FakeHostApplicationLifetime());
        await supervisor.StartAsync(CancellationToken.None);
        var child = Assert.Single(factory.Created("worker"));
        await child.WaitForExitStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));

        using var cancelled = new CancellationTokenSource();
        if (preCancelStopToken)
        {
            cancelled.Cancel();
        }

        var stopTask = supervisor.StopAsync(cancelled.Token);
        if (!preCancelStopToken)
        {
            await Task.Delay(50);
            Assert.False(stopTask.IsCompleted);
            cancelled.Cancel();
        }

        await child.StopStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.Equal(1, child.StopCallCount);

        child.ReleaseStop();

        var exception = await Record.ExceptionAsync(() => stopTask);

        Assert.True(exception is null or OperationCanceledException);
        Assert.True(child.HasExited);
        Assert.True(child.DisposeAsyncCalled);
    }

    [Fact]
    public async Task Forced_stop_terminates_the_entire_process_tree()
    {
        using var directory = new TestDirectory();
        var childPidPath = Path.Combine(directory.Path, "child.pid");
        var testChildDll = GetTestChildDll();
        var definition = new ComponentDefinition(
            Component(
                "tree",
                10,
                gracefulShutdownMilliseconds: 25,
                executablePath: GetDotnetHost(),
                arguments: [testChildDll, "--spawn-child-pid", childPidPath]));
        await using var child = new ChildProcess(
            definition,
            NullLogger<ChildProcess>.Instance);

        await child.StartAsync(CancellationToken.None);
        var descendantPid = 0;
        await WaitUntilAsync(() => TryReadProcessId(childPidPath, out descendantPid));
        var parentPid = child.Id;

        await child.StopAsync(CancellationToken.None);

        await WaitUntilAsync(() => HasExited(parentPid) && HasExited(descendantPid));
        Assert.True(HasExited(parentPid));
        Assert.True(HasExited(descendantPid));
    }

    private static ComponentSupervisor CreateSupervisor(
        IReadOnlyCollection<ComponentOptions> components,
        IChildProcessFactory factory,
        IComponentReadinessProbe readinessProbe,
        IHostApplicationLifetime lifetime) =>
        new(
            Options.Create(
                new ServiceHostOptions
                {
                    SchemaVersion = ServiceHostOptions.CurrentSchemaVersion,
                    Components = [.. components]
                }),
            factory,
            readinessProbe,
            lifetime,
            NullLogger<ComponentSupervisor>.Instance);

    private static ComponentOptions Component(
        string name,
        int startupOrder,
        int readinessMilliseconds = 1_000,
        int gracefulShutdownMilliseconds = 100,
        IReadOnlyList<TimeSpan>? restartDelays = null,
        string? executablePath = null,
        IReadOnlyList<string>? arguments = null)
    {
        var delays = restartDelays ?? [TimeSpan.FromMilliseconds(10), TimeSpan.FromMilliseconds(20)];
        return new ComponentOptions
        {
            Name = name,
            ExecutablePath = executablePath ?? Path.Combine(Environment.SystemDirectory, "cmd.exe"),
            Arguments = arguments is null ? [] : [.. arguments],
            WorkingDirectory = Environment.CurrentDirectory,
            StartupOrder = startupOrder,
            Required = true,
            ReadinessTimeout = TimeSpan.FromMilliseconds(readinessMilliseconds),
            GracefulShutdownTimeout = TimeSpan.FromMilliseconds(gracefulShutdownMilliseconds),
            RestartWindow = TimeSpan.FromMinutes(5),
            MaxRestarts = delays.Count,
            RestartDelays = [.. delays]
        };
    }

    private static async Task WaitUntilAsync(Func<bool> predicate)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        while (!predicate())
        {
            await Task.Delay(10, timeout.Token);
        }
    }

    private static bool HasExited(int processId)
    {
        try
        {
            using var process = Process.GetProcessById(processId);
            return process.HasExited;
        }

        catch (ArgumentException)
        {
            return true;
        }
    }

    private static bool TryReadProcessId(string path, out int processId)
    {
        processId = 0;
        try
        {
            return int.TryParse(File.ReadAllText(path), out processId);
        }
        catch (IOException)
        {
            return false;
        }
    }

    private static string GetDotnetHost() =>
        Environment.GetEnvironmentVariable("DOTNET_HOST_PATH")
        ?? throw new InvalidOperationException("DOTNET_HOST_PATH is not set.");

    private static string GetTestChildDll()
    {
        var outputDirectory = new DirectoryInfo(AppContext.BaseDirectory);
        var configuration = outputDirectory.Parent!.Name;
        var testsDirectory = outputDirectory.Parent.Parent!.Parent!.Parent!;
        return Path.Combine(
            testsDirectory.FullName,
            "OpenBB.ServiceHost.TestChild",
            "bin",
            configuration,
            "net10.0",
            "OpenBB.ServiceHost.TestChild.dll");
    }

    private sealed class FakeChildProcessFactory(
        ConcurrentQueue<string>? events = null,
        bool ignoreMonitorCancellation = false) : IChildProcessFactory
    {
        private readonly ConcurrentDictionary<string, List<FakeChildProcess>> _children = new();

        public IChildProcess Create(ComponentDefinition definition)
        {
            var child = new FakeChildProcess(
                definition,
                events,
                ignoreMonitorCancellation);
            lock (_children)
            {
                if (!_children.TryGetValue(definition.Name, out var children))
                {
                    children = [];
                    _children[definition.Name] = children;
                }

                children.Add(child);
            }

            return child;
        }

        public IReadOnlyList<FakeChildProcess> Created(string name)
        {
            lock (_children)
            {
                return _children.TryGetValue(name, out var children)
                    ? [.. children]
                    : [];
            }
        }
    }

    private sealed class ControllableAsyncChildProcessFactory : IChildProcessFactory
    {
        private readonly ConcurrentDictionary<string, List<ControllableAsyncChildProcess>> _children = new();

        public IChildProcess Create(ComponentDefinition definition)
        {
            var child = new ControllableAsyncChildProcess(definition);
            lock (_children)
            {
                if (!_children.TryGetValue(definition.Name, out var children))
                {
                    children = [];
                    _children[definition.Name] = children;
                }

                children.Add(child);
            }

            return child;
        }

        public IReadOnlyList<ControllableAsyncChildProcess> Created(string name)
        {
            lock (_children)
            {
                return _children.TryGetValue(name, out var children)
                    ? [.. children]
                    : [];
            }
        }
    }

    private sealed class FakeChildProcess(
        ComponentDefinition definition,
        ConcurrentQueue<string>? events,
        bool ignoreMonitorCancellation) : IChildProcess
    {
        private readonly TaskCompletionSource<int> _exit =
            new(TaskCreationOptions.RunContinuationsAsynchronously);

        public ComponentDefinition Definition { get; } = definition;

        public int Id { get; } = Random.Shared.Next(10_000, 99_999);

        public bool HasExited => _exit.Task.IsCompleted;

        public Task StartAsync(CancellationToken cancellationToken)
        {
            events?.Enqueue($"start:{Definition.Name}");
            return Task.CompletedTask;
        }

        public async Task<int> WaitForExitAsync(CancellationToken cancellationToken) =>
            ignoreMonitorCancellation
                ? await _exit.Task
                : await _exit.Task.WaitAsync(cancellationToken);

        public Task StopAsync(CancellationToken cancellationToken)
        {
            events?.Enqueue($"stop:{Definition.Name}");
            _exit.TrySetResult(0);
            return Task.CompletedTask;
        }

        public void Exit(int exitCode) => _exit.TrySetResult(exitCode);

        public ValueTask DisposeAsync()
        {
            _exit.TrySetResult(0);
            return ValueTask.CompletedTask;
        }
    }

    private sealed class ControllableAsyncChildProcess(ComponentDefinition definition) : IChildProcess
    {
        private readonly TaskCompletionSource<int> _exit =
            new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly TaskCompletionSource _allowStop =
            new(TaskCreationOptions.RunContinuationsAsynchronously);

        public ComponentDefinition Definition { get; } = definition;

        public int Id { get; } = Random.Shared.Next(10_000, 99_999);

        public bool DisposeAsyncCalled { get; private set; }

        public bool HasExited => _exit.Task.IsCompleted;

        public int StopCallCount { get; private set; }

        public TaskCompletionSource WaitForExitStarted { get; } =
            new(TaskCreationOptions.RunContinuationsAsynchronously);

        public TaskCompletionSource StopStarted { get; } =
            new(TaskCreationOptions.RunContinuationsAsynchronously);

        public Task StartAsync(CancellationToken cancellationToken) => Task.CompletedTask;

        public Task<int> WaitForExitAsync(CancellationToken cancellationToken)
        {
            WaitForExitStarted.TrySetResult();
            return _exit.Task;
        }

        public async Task StopAsync(CancellationToken cancellationToken)
        {
            StopCallCount++;
            StopStarted.TrySetResult();
            await _allowStop.Task.ConfigureAwait(false);
            _exit.TrySetResult(0);
        }

        public void ReleaseStop() => _allowStop.TrySetResult();

        public ValueTask DisposeAsync()
        {
            DisposeAsyncCalled = true;
            _exit.TrySetResult(0);
            return ValueTask.CompletedTask;
        }
    }

    private sealed class ImmediateReadinessProbe : IComponentReadinessProbe
    {
        public Task WaitUntilReadyAsync(
            ComponentDefinition definition,
            IChildProcess process,
            CancellationToken cancellationToken) => Task.CompletedTask;
    }

    private sealed class BlockingReadinessProbe(string blockedComponent)
        : IComponentReadinessProbe
    {
        public Task WaitUntilReadyAsync(
            ComponentDefinition definition,
            IChildProcess process,
            CancellationToken cancellationToken) =>
            definition.Name == blockedComponent
                ? Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken)
                : Task.CompletedTask;
    }

    private sealed class FakeHostApplicationLifetime : IHostApplicationLifetime
    {
        private readonly CancellationTokenSource _started = new();
        private readonly CancellationTokenSource _stopping = new();
        private readonly CancellationTokenSource _stopped = new();

        public FakeHostApplicationLifetime() => _started.Cancel();

        public CancellationToken ApplicationStarted => _started.Token;

        public CancellationToken ApplicationStopping => _stopping.Token;

        public CancellationToken ApplicationStopped => _stopped.Token;

        public void StopApplication() => _stopping.Cancel();
    }

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

[CollectionDefinition(nameof(ProcessSupervisorCollection), DisableParallelization = true)]
public sealed class ProcessSupervisorCollection;
