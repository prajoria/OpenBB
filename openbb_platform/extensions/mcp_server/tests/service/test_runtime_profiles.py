"""Deterministic installation/runtime profile tests."""

import json
from pathlib import Path

import pytest
from openbb_mcp_server.models.settings import MCPSettings
from openbb_mcp_server.service.mcp_service import MCPService
from openbb_mcp_server.service.runtime_profiles import (
    load_runtime_profiles,
    resolve_runtime_profile,
    write_runtime_resolution_artifact,
)


def _test_distribution_version(name):
    return "3.4.0" if name == "fastmcp" else "1.2.3"


def test_all_three_profiles_have_explicit_install_app_and_policy():
    """Every profile resolves installation, app composition and policy."""
    document = load_runtime_profiles()
    assert set(document.profiles) == {
        "platform-standard",
        "portfolio-read",
        "portfolio-ops",
    }
    standard = document.profiles["platform-standard"]
    read = document.profiles["portfolio-read"]
    ops = document.profiles["portfolio-ops"]
    assert standard.installation == "isolated_uv"
    assert standard.app.kind == "core"
    assert "openbb" in standard.required_distributions
    assert standard.distribution_sources["openbb"] == "openbb_platform"
    assert read.installation == ops.installation == "portfolio_venv"
    assert read.app.kind == ops.app.kind == "custom"
    assert "openbb-platform-api" in read.required_distributions
    assert "openbb-platform-api" in ops.required_distributions
    assert "openbb_platform_api" in read.required_modules
    assert "openbb_platform_api" in ops.required_modules
    assert read.policy_profile == "portfolio-read"
    assert ops.policy_profile == "portfolio-ops"
    assert ops.operator_access is True
    assert read.operator_access is False
    assert ops.maintenance_enabled is False


def test_profile_json_points_to_runtime_manifest():
    """The existing Portfolio profile declares its runtime profile identity."""
    profile = (
        Path(__file__).parents[2]
        / "openbb_mcp_server"
        / "assets"
        / "profiles"
        / "portfolio.json"
    )
    payload = json.loads(profile.read_text(encoding="utf-8"))
    assert payload["OPENBB_MCP_RUNTIME_PROFILE"] == "portfolio-read"
    assert payload["OPENBB_MCP_CAPABILITY_PROFILE"] == "portfolio-read"


def test_ready_resolution_with_explicit_components():
    """A complete matching installation resolves ready."""
    resolution = resolve_runtime_profile(
        "portfolio-read",
        settings=MCPSettings(
            runtime_profile="portfolio-read",
            capability_profile="portfolio-read",
            app_target="openbb_platform/extensions/portfolio/launch.py",
            installation_kind="portfolio_venv",
        ),
        distribution_available=lambda _name: True,
        module_available=lambda _name: True,
    )
    assert resolution.ready is True
    assert resolution.missing_distributions == ()
    assert resolution.missing_modules == ()
    assert resolution.conflicts == ()


def test_missing_required_components_are_explicit():
    """Missing fork packages cannot become success-shaped readiness."""
    resolution = resolve_runtime_profile(
        "portfolio-read",
        distribution_available=lambda name: name != "openbb-fmp-cached",
        module_available=lambda name: name != "openbb_fmp_cached",
        active_installation="portfolio_venv",
    )
    assert resolution.ready is False
    assert resolution.missing_distributions == ("openbb-fmp-cached",)
    assert resolution.missing_modules == ("openbb_fmp_cached",)


def test_optional_analytics_do_not_block_read_profile():
    """Optional analytical packages remain separately selectable."""
    resolution = resolve_runtime_profile(
        "portfolio-read",
        distribution_available=lambda name: name != "openbb-financialtoolkit",
        module_available=lambda _name: True,
        active_installation="portfolio_venv",
    )
    assert resolution.ready is True
    assert "openbb-financialtoolkit" in resolution.profile.optional_analytics
    assert resolution.optional_missing == ("openbb-financialtoolkit",)


def test_conflicting_policy_runtime_app_and_maintenance_are_rejected():
    """Selected configuration must agree with one manifest."""
    resolution = resolve_runtime_profile(
        "portfolio-read",
        settings=MCPSettings(
            runtime_profile="platform-standard",
            capability_profile="portfolio-ops",
            app_target="other.module:app",
            enable_maintenance_operations=True,
            installation_kind="portfolio_venv",
        ),
        distribution_available=lambda _name: True,
        module_available=lambda _name: True,
    )
    assert resolution.ready is False
    assert set(resolution.conflicts) == {
        "app_target:other.module:app!=openbb_platform/extensions/portfolio/launch.py",
        "capability_profile:portfolio-ops!=portfolio-read",
        "maintenance_not_enabled_by_profile",
        "runtime_profile:platform-standard!=portfolio-read",
    }


def test_unknown_profile_is_rejected():
    """Unknown labels never fall back to the broadest profile."""
    with pytest.raises(KeyError, match="Unknown runtime profile"):
        resolve_runtime_profile("unknown")  # type: ignore[arg-type]


def test_settings_aliases_parse_without_implicit_maintenance():
    """Environment-style settings remain explicit and maintenance defaults off."""
    settings = MCPSettings.model_validate(
        {
            "OPENBB_MCP_RUNTIME_PROFILE": "portfolio-ops",
            "OPENBB_MCP_CAPABILITY_PROFILE": "portfolio-ops",
            "OPENBB_MCP_APP_TARGET": "openbb_platform/extensions/portfolio/launch.py",
            "OPENBB_MCP_INSTALLATION_KIND": "portfolio_venv",
        }
    )
    assert settings.runtime_profile == "portfolio-ops"
    assert settings.capability_profile == "portfolio-ops"
    assert settings.installation_kind == "portfolio_venv"
    assert settings.enable_maintenance_operations is False


def test_python_and_installation_are_enforced():
    """Unsupported Python and wrong environment cannot resolve ready."""
    resolution = resolve_runtime_profile(
        "platform-standard",
        active_installation="portfolio_venv",
        python_version="3.14.0",
        distribution_version=_test_distribution_version,
        distribution_available=lambda _name: True,
        module_available=lambda _name: True,
    )
    assert resolution.ready is False
    assert resolution.python_compatible is False
    assert resolution.installation_matches is False
    assert set(resolution.conflicts) == {
        "installation_kind:portfolio_venv!=isolated_uv",
        "python_version:3.14.0!=>=3.10,<3.14",
    }


def test_selected_optional_analytics_become_required():
    """Selecting an unavailable optional package fails readiness explicitly."""
    resolution = resolve_runtime_profile(
        "portfolio-read",
        settings=MCPSettings(
            installation_kind="portfolio_venv",
            selected_analytics=["openbb-financialtoolkit"],
        ),
        distribution_available=lambda name: name != "openbb-financialtoolkit",
        module_available=lambda _name: True,
    )
    assert resolution.ready is False
    assert resolution.conflicts == (
        "selected_analytics_missing:openbb-financialtoolkit",
    )


def test_alias_settings_cannot_bypass_maintenance_conflicts():
    """Alias-parsed configuration cannot bypass maintenance conflicts."""
    resolution = resolve_runtime_profile(
        "portfolio-read",
        settings=MCPSettings.model_validate(
            {
                "OPENBB_MCP_INSTALLATION_KIND": "portfolio_venv",
                "OPENBB_MCP_ENABLE_MAINTENANCE_OPERATIONS": "true",
            }
        ),
        distribution_available=lambda _name: True,
        module_available=lambda _name: True,
    )
    assert "maintenance_not_enabled_by_profile" in resolution.conflicts


def test_alias_selected_analytics_are_parsed():
    """Comma-separated alias selections use settings list parsing."""
    resolution = resolve_runtime_profile(
        "portfolio-read",
        settings=MCPSettings.model_validate(
            {"OPENBB_MCP_SELECTED_ANALYTICS": "openbb-financialtoolkit"}
        ),
        distribution_available=lambda name: name != "openbb-financialtoolkit",
        module_available=lambda _name: True,
        active_installation="portfolio_venv",
    )
    assert resolution.selected_analytics == ("openbb-financialtoolkit",)
    assert resolution.conflicts == (
        "selected_analytics_missing:openbb-financialtoolkit",
    )


@pytest.mark.parametrize("python_version", ["3.12.10", "3.13.9"])
def test_supported_python_profiles_are_compatible(python_version):
    """Both supported interpreter minors satisfy the standard profile."""
    resolution = resolve_runtime_profile(
        "platform-standard",
        settings=MCPSettings(),
        active_installation="isolated_uv",
        python_version=python_version,
        distribution_version=_test_distribution_version,
        distribution_available=lambda _name: True,
        module_available=lambda _name: True,
    )
    assert resolution.python_compatible is True
    assert resolution.ready is True


def test_local_sources_from_selected_checkout_are_accepted(tmp_path):
    """Editable distributions and modules must resolve inside declared roots."""
    core = tmp_path / "openbb_platform" / "core"
    mcp = tmp_path / "openbb_platform" / "extensions" / "mcp_server"
    platform_api = tmp_path / "openbb_platform" / "extensions" / "platform_api"
    origins = {
        "openbb-core": core,
        "openbb-platform-api": platform_api,
        "openbb-mcp-server": mcp,
        "openbb": core / "openbb",
        "openbb_core": core / "openbb_core",
        "openbb_platform_api": platform_api / "openbb_platform_api",
        "openbb_mcp_server": mcp / "openbb_mcp_server",
    }
    resolution = resolve_runtime_profile(
        "platform-standard",
        settings=MCPSettings(),
        active_installation="isolated_uv",
        repository_root=tmp_path,
        distribution_origin=origins.get,
        distribution_version=_test_distribution_version,
        module_origin=origins.get,
        distribution_available=lambda _name: True,
        module_available=lambda _name: True,
    )
    assert resolution.source_conflicts == ()
    assert resolution.ready is True


def test_sibling_worktree_distribution_is_rejected(tmp_path):
    """An installed editable from another checkout cannot pass readiness."""
    sibling = tmp_path.parent / "other-worktree" / "openbb_platform" / "core"
    core = tmp_path / "openbb_platform" / "core"
    mcp = tmp_path / "openbb_platform" / "extensions" / "mcp_server"
    platform_api = tmp_path / "openbb_platform" / "extensions" / "platform_api"
    origins = {
        "openbb-core": sibling,
        "openbb-platform-api": platform_api,
        "openbb-mcp-server": mcp,
        "openbb": core,
        "openbb_core": core,
        "openbb_platform_api": platform_api,
        "openbb_mcp_server": mcp,
    }
    resolution = resolve_runtime_profile(
        "platform-standard",
        settings=MCPSettings(),
        active_installation="isolated_uv",
        repository_root=tmp_path,
        distribution_origin=origins.get,
        distribution_version=_test_distribution_version,
        module_origin=origins.get,
        distribution_available=lambda _name: True,
        module_available=lambda _name: True,
    )
    assert resolution.ready is False
    assert resolution.source_conflicts == ("distribution:openbb-core",)


def test_resolution_artifact_uses_repository_relative_origins(tmp_path):
    """Replay evidence does not persist machine-specific checkout paths."""
    core = tmp_path / "openbb_platform" / "core"
    mcp = tmp_path / "openbb_platform" / "extensions" / "mcp_server"
    platform_api = tmp_path / "openbb_platform" / "extensions" / "platform_api"
    origins = {
        "openbb-core": core,
        "openbb-platform-api": platform_api,
        "openbb-mcp-server": mcp,
        "openbb": core,
        "openbb_core": core,
        "openbb_platform_api": platform_api,
        "openbb_mcp_server": mcp,
    }
    resolution = resolve_runtime_profile(
        "platform-standard",
        settings=MCPSettings(),
        active_installation="isolated_uv",
        repository_root=tmp_path,
        distribution_origin=origins.get,
        distribution_version=_test_distribution_version,
        module_origin=origins.get,
        distribution_available=lambda _name: True,
        module_available=lambda _name: True,
    )
    artifact = tmp_path / "resolution.json"
    write_runtime_resolution_artifact(
        resolution,
        artifact,
    )
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["profile"] == "platform-standard"
    assert payload["python"] == resolution.python_version
    assert payload["ready"] is True
    assert payload["distribution_versions"]["openbb-core"] == "1.2.3"
    assert payload["distribution_origins"]["openbb-core"] == "openbb_platform/core"
    assert payload["configuration"]["source"] == "explicit"
    assert payload["configuration"]["maintenance_requested"] is False
    assert payload["provenance_checked"] is True
    assert str(tmp_path) not in artifact.read_text(encoding="utf-8")


def test_empty_install_reports_every_required_component():
    """A fresh unresolved environment fails with complete missing evidence."""
    profile = load_runtime_profiles().profiles["platform-standard"]
    resolution = resolve_runtime_profile(
        "platform-standard",
        active_installation="isolated_uv",
        distribution_available=lambda _name: False,
        distribution_version=lambda _name: None,
        module_available=lambda _name: False,
    )
    assert resolution.ready is False
    assert resolution.missing_distributions == profile.required_distributions
    assert resolution.missing_modules == profile.required_modules
    assert resolution.distribution_versions == {}


def test_pinned_external_version_mismatch_is_rejected():
    """The standard profile enforces the launcher FastMCP pin."""
    resolution = resolve_runtime_profile(
        "platform-standard",
        settings=MCPSettings(),
        active_installation="isolated_uv",
        distribution_available=lambda _name: True,
        distribution_version=lambda name: ("3.4.6" if name == "fastmcp" else "1.0.0"),
        module_available=lambda _name: True,
    )
    assert resolution.ready is False
    assert resolution.conflicts == ("distribution_version:fastmcp:3.4.6!=3.4.0",)


def test_selected_optional_module_from_sibling_worktree_is_rejected(tmp_path):
    """Selected analytics validate both distribution and import origins."""
    document = load_runtime_profiles()
    profile = document.profiles["portfolio-read"]
    origins = {
        name: tmp_path / relative
        for name, relative in {
            **profile.distribution_sources,
            **profile.module_sources,
        }.items()
    }
    origins["openbb_financialtoolkit"] = (
        tmp_path.parent
        / "sibling-worktree"
        / "openbb_platform"
        / "extensions"
        / "financialtoolkit"
    )
    resolution = resolve_runtime_profile(
        "portfolio-read",
        settings=MCPSettings(selected_analytics=["openbb-financialtoolkit"]),
        active_installation="portfolio_venv",
        repository_root=tmp_path,
        distribution_origin=origins.get,
        distribution_version=lambda _name: "1.0.0",
        module_origin=origins.get,
        distribution_available=lambda _name: True,
        module_available=lambda _name: True,
    )
    assert resolution.ready is False
    assert resolution.source_conflicts == ("module:openbb_financialtoolkit",)


def test_effective_settings_file_conflict_is_rejected(tmp_path, monkeypatch):
    """Default resolution uses the same persisted settings as the server."""
    settings_path = tmp_path / "mcp_settings.json"
    settings_path.write_text(
        MCPSettings(enable_maintenance_operations=True).model_dump_json(),
        encoding="utf-8",
    )
    monkeypatch.setattr(MCPService, "MCP_SETTINGS_PATH", settings_path)
    resolution = resolve_runtime_profile(
        "platform-standard",
        active_installation="isolated_uv",
        distribution_available=lambda _name: True,
        distribution_version=_test_distribution_version,
        module_available=lambda _name: True,
    )
    assert resolution.ready is False
    assert "maintenance_not_enabled_by_profile" in resolution.conflicts
    assert resolution.configuration.source == "effective_service"


def test_effective_settings_read_does_not_create_default_file(tmp_path, monkeypatch):
    """Metadata verification does not mutate a clean user configuration."""
    settings_path = tmp_path / "mcp_settings.json"
    monkeypatch.setattr(MCPService, "MCP_SETTINGS_PATH", settings_path)
    resolve_runtime_profile(
        "platform-standard",
        active_installation="isolated_uv",
        distribution_available=lambda _name: True,
        distribution_version=_test_distribution_version,
        module_available=lambda _name: True,
    )
    assert settings_path.exists() is False


def test_active_installation_rejects_effective_setting_disagreement():
    """Probe identity cannot hide a contradictory persisted installation."""
    resolution = resolve_runtime_profile(
        "platform-standard",
        settings=MCPSettings(installation_kind="portfolio_venv"),
        active_installation="isolated_uv",
        distribution_available=lambda _name: True,
        distribution_version=_test_distribution_version,
        module_available=lambda _name: True,
    )
    assert resolution.ready is False
    assert (
        "installation_kind_override:portfolio_venv!=isolated_uv" in resolution.conflicts
    )


def test_absolute_app_target_is_redacted_from_artifact(tmp_path):
    """Effective configuration cannot leak a machine path into evidence."""
    absolute_target = tmp_path.parent / "private-checkout" / "app.py"
    resolution = resolve_runtime_profile(
        "platform-standard",
        settings=MCPSettings(app_target=str(absolute_target)),
        active_installation="isolated_uv",
        distribution_available=lambda _name: True,
        distribution_version=_test_distribution_version,
        module_available=lambda _name: True,
    )
    artifact = tmp_path / "redacted.json"
    write_runtime_resolution_artifact(resolution, artifact)
    content = artifact.read_text(encoding="utf-8")
    assert str(absolute_target) not in content
    assert resolution.configuration.app_target == "outside_repository"
    assert resolution.provenance_checked is False
