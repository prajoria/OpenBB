using System.Net;
using Microsoft.Extensions.Options;

namespace OpenBB.ServiceHost.Configuration;

public sealed class ServiceHostOptionsValidator : IValidateOptions<ServiceHostOptions>
{
    public ValidateOptionsResult Validate(string? name, ServiceHostOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);

        var failures = new List<string>();
        if (options.SchemaVersion != ServiceHostOptions.CurrentSchemaVersion)
        {
            failures.Add(
                $"schemaVersion must be {ServiceHostOptions.CurrentSchemaVersion}; received {options.SchemaVersion}.");
        }

        if (options.Components is null || options.Components.Count == 0)
        {
            failures.Add("components must contain at least one component.");
            return ValidateOptionsResult.Fail(failures);
        }

        ValidateAbsolutePath(options.LogDirectory, nameof(options.LogDirectory), failures);
        if (!string.IsNullOrWhiteSpace(options.EnvironmentFile))
        {
            ValidateAbsolutePath(
                options.EnvironmentFile,
                nameof(options.EnvironmentFile),
                failures);
        }

        ValidateUniqueValues(options.Components, failures);
        for (var index = 0; index < options.Components.Count; index++)
        {
            ValidateComponent(options.Components[index], index, failures);
        }

        return failures.Count == 0
            ? ValidateOptionsResult.Success
            : ValidateOptionsResult.Fail(failures);
    }

    private static void ValidateUniqueValues(
        IReadOnlyCollection<ComponentOptions> components,
        ICollection<string> failures)
    {
        var duplicateNames = components
            .Where(component => !string.IsNullOrWhiteSpace(component.Name))
            .GroupBy(component => component.Name, StringComparer.OrdinalIgnoreCase)
            .Where(group => group.Count() > 1)
            .Select(group => group.Key);
        foreach (var duplicateName in duplicateNames)
        {
            failures.Add($"Component Name '{duplicateName}' must be unique.");
        }

        var duplicatePorts = components
            .Where(component => component.Port.HasValue)
            .GroupBy(component => component.Port!.Value)
            .Where(group => group.Count() > 1)
            .Select(group => group.Key);
        foreach (var duplicatePort in duplicatePorts)
        {
            failures.Add($"Component Port {duplicatePort} must be unique.");
        }

        var duplicateStartupOrders = components
            .GroupBy(component => component.StartupOrder)
            .Where(group => group.Count() > 1)
            .Select(group => group.Key);
        foreach (var duplicateStartupOrder in duplicateStartupOrders)
        {
            failures.Add($"Component StartupOrder {duplicateStartupOrder} must be unique.");
        }
    }

    private static void ValidateComponent(
        ComponentOptions component,
        int index,
        ICollection<string> failures)
    {
        var prefix = $"components[{index}]";
        if (string.IsNullOrWhiteSpace(component.Name))
        {
            failures.Add($"{prefix}.Name is required.");
        }

        ValidateAbsolutePath(component.ExecutablePath, $"{prefix}.ExecutablePath", failures);
        ValidateAbsolutePath(component.WorkingDirectory, $"{prefix}.WorkingDirectory", failures);

        if (component.Port is < 1 or > 65535)
        {
            failures.Add($"{prefix}.Port must be between 1 and 65535.");
        }

        if (component.Port.HasValue &&
            (!IPAddress.TryParse(component.BindAddress, out var address) ||
             !IPAddress.IsLoopback(address)))
        {
            failures.Add($"{prefix}.BindAddress must be a loopback IP address.");
        }

        if (component.Arguments.Any(
                argument => string.Equals(
                    argument,
                    "--reload",
                    StringComparison.OrdinalIgnoreCase)))
        {
            failures.Add($"{prefix}.Arguments cannot contain --reload.");
        }

        ValidatePositive(component.ReadinessTimeout, $"{prefix}.ReadinessTimeout", failures);
        ValidatePositive(
            component.GracefulShutdownTimeout,
            $"{prefix}.GracefulShutdownTimeout",
            failures);
        ValidatePositive(component.RestartWindow, $"{prefix}.RestartWindow", failures);

        if (component.MaxRestarts < 0)
        {
            failures.Add($"{prefix}.MaxRestarts cannot be negative.");
        }

        if (component.RestartDelays is null ||
            component.RestartDelays.Count != component.MaxRestarts)
        {
            failures.Add(
                $"{prefix}.RestartDelays must contain exactly MaxRestarts entries.");
        }
        else if (component.RestartDelays.Any(delay => delay <= TimeSpan.Zero))
        {
            failures.Add($"{prefix}.RestartDelays entries must be positive.");
        }
    }

    private static void ValidateAbsolutePath(
        string? value,
        string propertyName,
        ICollection<string> failures)
    {
        if (string.IsNullOrWhiteSpace(value) || !Path.IsPathFullyQualified(value))
        {
            failures.Add($"{propertyName} must be an absolute path.");
        }
    }

    private static void ValidatePositive(
        TimeSpan value,
        string propertyName,
        ICollection<string> failures)
    {
        if (value <= TimeSpan.Zero)
        {
            failures.Add($"{propertyName} must be positive.");
        }
    }
}
