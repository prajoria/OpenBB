"""Regression tests for browser-safe Workspace discovery responses."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _load_launcher_app() -> FastAPI:
    launch_path = Path(__file__).resolve().parents[1] / "launch.py"
    spec = spec_from_file_location(
        "_openbb_portfolio_discovery_headers_launch",
        launch_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load Portfolio launcher from {launch_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


def test_discovery_manifests_are_not_cacheable() -> None:
    """A TLS trust visit must not be reused later without CORS response headers."""
    client = TestClient(_load_launcher_app())
    for path in ("/widgets.json", "/apps.json"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-store"
