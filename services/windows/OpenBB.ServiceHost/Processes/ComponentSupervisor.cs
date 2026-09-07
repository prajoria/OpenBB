using System.Runtime.ExceptionServices;
using Microsoft.Extensions.Options;
using OpenBB.ServiceHost.Configuration;

namespace OpenBB.ServiceHost.Processes;

public sealed class ComponentSupervisor(
    IOptions<ServiceHostOptions> options,
    IChildProcessFactory processFactory,
    IComponentReadinessProbe readinessProbe,
    IHostApplicationLifetime applicationLifetime,
    ILogger<ComponentSupervisor> logger,
    TimeProvider? timeProvider = null) : BackgroundService
{
    private readonly IReadOnlyList<ComponentDefinition> _definitions = options.Value.Components
        .OrderBy(component => component.StartupOrder)
        .Select(component => new ComponentDefinition(component))
        .ToArray();
    private readonly List<ComponentState> _states = [];
    private readonly TimeProvider _timeProvider = timeProvider ?? TimeProvider.System;
    private bool _baseServiceStarted;
    private bool _stopped;

    public override async Task StartAsync(CancellationToken cancellationToken)
    {
        try
        {
            foreach (var definition in _definitions)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var state = new ComponentState(definition, processFactory.Create(definition));
                _states.Add(state);
                await state.Process.StartAsync(cancellationToken).ConfigureAwait(false);
                await WaitUntilReadyAsync(state, cancellationToken).ConfigureAwait(false);
                logger.LogInformation("Component {Component} is ready.", definition.Name);
            }

            await base.StartAsync(cancellationToken).ConfigureAwait(false);
            _baseServiceStarted = true;
        }
        catch
        {
            await StopChildrenAsync().ConfigureAwait(false);
            throw;
        }
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var monitors = _states
            .Select(state => MonitorAsync(state, stoppingToken))
            .ToArray();
        await Task.WhenAll(monitors).ConfigureAwait(false);
    }

    public override async Task StopAsync(CancellationToken cancellationToken)
    {
        if (_stopped)
        {
            return;
        }

        _stopped = true;
        OperationCanceledException? cancellationException = null;
        if (_baseServiceStarted)
        {
            try
            {
                await base.StopAsync(cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException exception) when (cancellationToken.IsCancellationRequested)
            {
                cancellationException = exception;
            }
        }

        await StopChildrenAsync().ConfigureAwait(false);

        if (cancellationException is not null)
        {
            ExceptionDispatchInfo.Capture(cancellationException).Throw();
        }
    }

    private async Task MonitorAsync(
        ComponentState state,
        CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            int exitCode;
            try
            {
                exitCode = await state.Process
                    .WaitForExitAsync(stoppingToken)
                    .ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                return;
            }

            logger.LogWarning(
                "Component {Component} exited with code {ExitCode}.",
                state.Definition.Name,
                exitCode);

            while (!stoppingToken.IsCancellationRequested)
            {
                if (!TryReserveRestart(state, out var restartDelay))
                {
                    HandleExhaustedBudget(state.Definition);
                    return;
                }

                try
                {
                    await Task.Delay(restartDelay, _timeProvider, stoppingToken)
                        .ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
                {
                    return;
                }

                await state.Process.DisposeAsync().ConfigureAwait(false);
                state.Process = processFactory.Create(state.Definition);
                try
                {
                    await state.Process.StartAsync(stoppingToken).ConfigureAwait(false);
                    await WaitUntilReadyAsync(state, stoppingToken).ConfigureAwait(false);
                    logger.LogInformation(
                        "Restarted component {Component}.",
                        state.Definition.Name);
                    break;
                }
                catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
                {
                    return;
                }
                catch (Exception exception)
                {
                    logger.LogError(
                        exception,
                        "Restart of component {Component} failed.",
                        state.Definition.Name);
                    await state.Process.StopAsync(CancellationToken.None).ConfigureAwait(false);
                }
            }
        }
    }

    private async Task WaitUntilReadyAsync(
        ComponentState state,
        CancellationToken cancellationToken)
    {
        try
        {
            await readinessProbe.WaitUntilReadyAsync(
                    state.Definition,
                    state.Process,
                    cancellationToken)
                .WaitAsync(state.Definition.ReadinessTimeout, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (TimeoutException exception)
        {
            throw new TimeoutException(
                $"Component '{state.Definition.Name}' did not become ready within " +
                $"{state.Definition.ReadinessTimeout}.",
                exception);
        }
    }

    private bool TryReserveRestart(
        ComponentState state,
        out TimeSpan restartDelay)
    {
        var now = _timeProvider.GetUtcNow();
        while (state.Restarts.Count > 0 &&
               now - state.Restarts.Peek() >= state.Definition.RestartWindow)
        {
            state.Restarts.Dequeue();
        }

        if (state.Restarts.Count >= state.Definition.MaxRestarts)
        {
            restartDelay = default;
            return false;
        }

        restartDelay = state.Definition.RestartDelays[state.Restarts.Count];
        state.Restarts.Enqueue(now);
        return true;
    }

    private void HandleExhaustedBudget(ComponentDefinition definition)
    {
        logger.LogCritical(
            "Component {Component} exhausted its restart budget.",
            definition.Name);
        if (!definition.Required)
        {
            return;
        }

        if (Environment.ExitCode == 0)
        {
            Environment.ExitCode = 1;
        }

        applicationLifetime.StopApplication();
    }

    private async Task StopChildrenAsync()
    {
        for (var index = _states.Count - 1; index >= 0; index--)
        {
            var state = _states[index];
            try
            {
                await state.Process.StopAsync(CancellationToken.None).ConfigureAwait(false);
                await state.Process.DisposeAsync().ConfigureAwait(false);
            }
            catch (Exception exception)
            {
                logger.LogError(
                    exception,
                    "Failed to stop component {Component}.",
                    state.Definition.Name);
            }
        }
    }

    private sealed class ComponentState(
        ComponentDefinition definition,
        IChildProcess process)
    {
        public ComponentDefinition Definition { get; } = definition;

        public IChildProcess Process { get; set; } = process;

        public Queue<DateTimeOffset> Restarts { get; } = new();
    }
}
