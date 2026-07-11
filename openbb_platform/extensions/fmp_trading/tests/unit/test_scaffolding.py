"""Unit tests for fmp_trading scaffolding: package + router imports, command surface."""

from __future__ import annotations


def test_package_imports():
    import openbb_fmp_trading

    assert openbb_fmp_trading.__version__ == "0.1.0"


def test_router_exposes_doctor():
    from openbb_fmp_trading.fmp_trading_router import router

    paths = {getattr(route, "path", None) for route in router.api_router.routes}
    assert "/doctor" in paths
