"""Deterministic installation/runtime profile tests."""

import json
from pathlib import Path

import pytest
from openbb_mcp_server.models.settings import MCPSettings
from openbb_mcp_server.service.runtime_profiles import (
    load_runtime_profiles,
    resolve_runtime_profile,
)


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
    assert read.installation == ops.installation == "portfolio_venv"
    assert read.app.kind == ops.app.kind == "custom"
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


def test_environment_settings_are_honored_when_not_injected(monkeypatch):
    """Environment configuration cannot bypass maintenance conflicts."""
    monkeypatch.setenv("OPENBB_MCP_INSTALLATION_KIND", "portfolio_venv")
    monkeypatch.setenv("OPENBB_MCP_ENABLE_MAINTENANCE_OPERATIONS", "true")
    resolution = resolve_runtime_profile(
        "portfolio-read",
        distribution_available=lambda _name: True,
        module_available=lambda _name: True,
    )
    assert "maintenance_not_enabled_by_profile" in resolution.conflicts


def test_environment_selected_analytics_are_parsed(monkeypatch):
    """Comma-separated environment selections use settings list parsing."""
    monkeypatch.setenv("OPENBB_MCP_SELECTED_ANALYTICS", "openbb-financialtoolkit")
    resolution = resolve_runtime_profile(
        "portfolio-read",
        distribution_available=lambda name: name != "openbb-financialtoolkit",
        module_available=lambda _name: True,
        active_installation="portfolio_venv",
    )
    assert resolution.selected_analytics == ("openbb-financialtoolkit",)
    assert resolution.conflicts == (
        "selected_analytics_missing:openbb-financialtoolkit",
    )
