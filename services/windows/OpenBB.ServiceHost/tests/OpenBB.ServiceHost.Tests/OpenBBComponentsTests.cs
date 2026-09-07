using OpenBB.ServiceHost.Processes;

namespace OpenBB.ServiceHost.Tests;

public sealed class OpenBBComponentsTests
{
    [Fact]
    public void Builds_exact_secret_free_commands_for_all_components()
    {
        var components = OpenBBComponents.Create(
            @"C:\OpenBB\venv\Scripts\python.exe",
            @"C:\OpenBB\app",
            new Dictionary<string, string>
            {
                ["FMP_API_KEY"] = "fixture-secret",
                ["PI_WIDGET_BACKEND_TOKEN"] = "widget-secret"
            });

        Assert.Collection(
            components.OrderBy(component => component.StartupOrder),
            worker =>
            {
                Assert.Equal("jobs-worker", worker.Name);
                Assert.Equal(
                    [
                        "-m",
                        "openbb_core.app.jobs.worker",
                        "worker",
                        "--poll-seconds",
                        "5"
                    ],
                    worker.Arguments);
                Assert.Equal(TimeSpan.FromMinutes(10), worker.GracefulShutdownTimeout);
            },
            api =>
            {
                Assert.Equal("portfolio-api", api.Name);
                Assert.Equal(
                    [
                        "-m",
                        "openbb_platform_api.main",
                        "--app",
                        "openbb_platform/extensions/portfolio/launch.py",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "6902"
                    ],
                    api.Arguments);
            },
            web =>
            {
                Assert.Equal("portfolio-intel-ux", web.Name);
                Assert.Equal(
                    [
                        "-m",
                        "uvicorn",
                        "openbb_portfolio_intel.widget_backend.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "6120"
                    ],
                    web.Arguments);
            });

        Assert.All(
            components,
            component =>
            {
                Assert.DoesNotContain("fixture-secret", string.Join(" ", component.Arguments));
                Assert.DoesNotContain("widget-secret", string.Join(" ", component.Arguments));
            });
    }

    [Fact]
    public void Installed_service_rejects_uvicorn_reload()
    {
        var error = Assert.Throws<ArgumentException>(
            () => OpenBBComponents.EnsureInstalledServiceArguments(
                ["-m", "uvicorn", "module:app", "--reload"]));

        Assert.Contains("--reload", error.Message);
    }
}
