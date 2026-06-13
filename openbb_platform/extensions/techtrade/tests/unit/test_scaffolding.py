"""Unit tests for techtrade scaffolding: package + router imports, command surface."""

from __future__ import annotations


def test_package_imports():
    import openbb_techtrade

    assert openbb_techtrade.__version__


def test_core_modules_import():
    # Leaf modules must import without heavy/optional dependencies.
    import openbb_techtrade.helpers  # noqa: F401
    import openbb_techtrade.models  # noqa: F401


def test_subpackages_import():
    import openbb_techtrade.engine  # noqa: F401
    import openbb_techtrade.reporting  # noqa: F401
    import openbb_techtrade.strategies  # noqa: F401
    import openbb_techtrade.validation  # noqa: F401


def test_router_exposes_about():
    from openbb_techtrade.techtrade_router import router

    # Verified Router API in this checkout: commands are FastAPI routes on
    # `router.api_router.routes`, each with a `.path` like "/about".
    paths = {getattr(route, "path", None) for route in router.api_router.routes}
    assert "/about" in paths
