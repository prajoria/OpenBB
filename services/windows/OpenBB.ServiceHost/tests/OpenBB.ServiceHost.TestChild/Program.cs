using System.Diagnostics;

var arguments = args.ToList();
var childPidPath = ReadOption(arguments, "--spawn-child-pid");
var lifetimeText = ReadOption(arguments, "--lifetime-ms");
var exitCodeText = ReadOption(arguments, "--exit-code");

if (childPidPath is not null)
{
    var child = Process.Start(new ProcessStartInfo
    {
        FileName = Environment.ProcessPath!,
        UseShellExecute = false,
        ArgumentList = { Environment.GetCommandLineArgs()[0], "--sleep" }
    }) ?? throw new InvalidOperationException("Could not start fake descendant.");
    await File.WriteAllTextAsync(childPidPath, child.Id.ToString());
}

if (int.TryParse(lifetimeText, out var lifetimeMilliseconds))
{
    await Task.Delay(lifetimeMilliseconds);
    return int.TryParse(exitCodeText, out var configuredExitCode)
        ? configuredExitCode
        : 0;
}

await Task.Delay(Timeout.InfiniteTimeSpan);
return 0;

static string? ReadOption(IReadOnlyList<string> arguments, string option)
{
    for (var index = 0; index + 1 < arguments.Count; index++)
    {
        if (string.Equals(arguments[index], option, StringComparison.Ordinal))
        {
            return arguments[index + 1];
        }
    }

    return null;
}
