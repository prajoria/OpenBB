using System.Text.RegularExpressions;

namespace OpenBB.ServiceHost.Logging;

public sealed partial class SecretRedactor
{
    public const string Redacted = "[REDACTED]";
    private static readonly string[] SecretVariableMarkers =
        ["KEY", "TOKEN", "SECRET", "PASSWORD"];

    private readonly string[] _secretValues;

    public SecretRedactor(IEnumerable<string> secretValues)
    {
        ArgumentNullException.ThrowIfNull(secretValues);
        _secretValues = secretValues
            .Where(value => !string.IsNullOrEmpty(value))
            .Distinct(StringComparer.Ordinal)
            .OrderByDescending(value => value.Length)
            .ToArray();
    }

    public string Redact(string? value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return value ?? string.Empty;
        }

        var redacted = BearerTokenRegex().Replace(value, $"Bearer {Redacted}");
        redacted = UrlQueryRegex().Replace(redacted, $"${{url}}?{Redacted}");
        foreach (var secret in _secretValues)
        {
            redacted = redacted.Replace(secret, Redacted, StringComparison.Ordinal);
        }

        return redacted;
    }

    public static SecretRedactor FromEnvironmentFile(string path)
        => new(LoadEnvironmentFile(path).Values);

    public static bool IsSecretVariableName(string name)
    {
        ArgumentNullException.ThrowIfNull(name);
        return SecretVariableMarkers.Any(
            marker => name.Contains(marker, StringComparison.OrdinalIgnoreCase));
    }

    public static IReadOnlyDictionary<string, string> LoadEnvironmentFile(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new ArgumentException(
                "Environment file path is required.",
                nameof(path));
        }

        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var rawLine in File.ReadLines(path))
        {
            var line = rawLine.Trim();
            if (line.Length == 0 || line.StartsWith('#'))
            {
                continue;
            }

            var separator = line.IndexOf('=');
            if (separator <= 0)
            {
                continue;
            }

            var name = line[..separator].Trim();
            var value = line[(separator + 1)..].Trim();
            if (value.Length >= 2 &&
                ((value[0] == '"' && value[^1] == '"') ||
                 (value[0] == '\'' && value[^1] == '\'')))
            {
                value = value[1..^1];
            }

            if (name.Length > 0 && value.Length > 0)
            {
                values[name] = value;
            }
        }

        return values;
    }

    [GeneratedRegex(
        @"\bBearer\s+[^\s,;""']+",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex BearerTokenRegex();

    [GeneratedRegex(
        @"(?<url>https?://[^\s?""']+)\?[^\s""']+",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex UrlQueryRegex();
}
