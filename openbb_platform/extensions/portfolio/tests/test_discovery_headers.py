"""Regression tests for browser-safe Workspace discovery responses."""

import asyncio

from launch import root_apps, root_widgets


def test_discovery_manifests_are_not_cacheable() -> None:
    """A TLS trust visit must not be reused later without CORS response headers."""
    for endpoint in (root_widgets, root_apps):
        response = asyncio.run(endpoint())
        assert response.headers.get("cache-control") == "no-store"
