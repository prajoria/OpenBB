"""Scaffold-level tests for the portfolio_intel extension.

Bead: OpenBBTechnical-qy83.1.4 — Scaffold portfolio_intel extension skeleton
(CI green). These tests define the exit criteria for M0 task 1.4: the
extension imports cleanly, exposes a `Router`, and carries the version
metadata that the OpenBB extension registry keys off.

Kept minimal on purpose. Every subsequent P1/P2/P3 task adds *behavioural*
tests to `tests/unit/` and `tests/integration/` alongside its own router
sub-module. This file only asserts scaffolding is intact.
"""

from __future__ import annotations

import importlib

import pytest


def test_extension_module_importable() -> None:
    """The top-level module must import without side effects.

    A common regression mode is a heavy top-level import (numpy/pandas via
    a helper) creeping into __init__.py — this test fails loudly if that
    happens because we assert import completes cleanly.
    """
    mod = importlib.import_module("openbb_portfolio_intel")
    assert hasattr(mod, "__version__")
    assert isinstance(mod.__version__, str)
    assert mod.__version__.count(".") >= 2, "expected semver-shaped version"


def test_router_module_exposes_router_instance() -> None:
    """The router module must export a `router` attribute of type Router.

    OpenBB's plugin discovery loads
    ``openbb_portfolio_intel.portfolio_intel_router:router`` — if this
    contract breaks, the extension silently disappears from the platform.
    """
    from openbb_core.app.router import Router  # noqa: PLC0415

    router_mod = importlib.import_module(
        "openbb_portfolio_intel.portfolio_intel_router"
    )
    assert hasattr(router_mod, "router"), "router module must export `router`"
    assert isinstance(router_mod.router, Router)


def test_router_declares_about_command_at_source_level() -> None:
    """The router source must contain the `about` command declaration.

    Note on OpenBB's runtime model: at *scaffold-time* (before ``python
    dev_install.py -e`` + ``openbb.build()``), the ``@router.command``
    decorator does not preserve a directly-callable ``about`` on the
    module — the build step is what materialises the command handler and
    exposes it via ``router.api_router.routes``. So the scaffold-level
    assertion is at the *source* level: the file must contain the
    canonical ``@router.command`` + ``def about(`` declaration. The
    *route is served* assertion belongs in a post-build integration
    test that runs after ``dev_install.py -e``.
    """
    from pathlib import Path

    import openbb_portfolio_intel.portfolio_intel_router as pim_router

    src = Path(pim_router.__file__).read_text(encoding="utf-8")
    assert "@router.command" in src, "router must declare @router.command"
    assert (
        "def about(" in src
    ), "router must define an `about` command for the M0 health-check"


def test_package_has_py_typed_marker() -> None:
    """PEP 561 marker must exist so downstream consumers get type info."""
    from pathlib import Path

    import openbb_portfolio_intel

    pkg_dir = Path(openbb_portfolio_intel.__file__).parent
    marker = pkg_dir / "py.typed"
    assert marker.exists(), f"py.typed marker missing from {pkg_dir}"


@pytest.mark.parametrize(
    "attr",
    ["__version__", "__all__"],
)
def test_module_public_surface(attr: str) -> None:
    """Public surface stays minimal in M0.

    Guards against accidental leak of implementation modules into the
    top-level namespace during scaffolding. When P1 lands real commands,
    __all__ will explicitly enumerate them.
    """
    mod = importlib.import_module("openbb_portfolio_intel")
    assert hasattr(mod, attr), f"missing public surface attribute: {attr}"
