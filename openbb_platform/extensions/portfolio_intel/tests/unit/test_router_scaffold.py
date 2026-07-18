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


# ---------------------------------------------------------------------------
# PR #466 review hardening (below)
# ---------------------------------------------------------------------------


def test_pyproject_entry_point_key_matches_documented_namespace() -> None:
    """Entry-point key must be `portfolio_intel` (underscore) so the runtime
    namespace `obb.portfolio_intel.*` matches what README / router docstring
    promise.

    Addresses PR #466 review finding 1: OpenBB's plugin loader does NOT
    dot-split entry-point keys. A key `portfolio_intel` produces
    `obb.portfolio_intel.*`, NOT `obb.portfolio.intel.*`. This test locks
    the current (documented) shape so nobody silently changes it back.
    """
    from pathlib import Path

    import openbb_portfolio_intel

    pkg_dir = Path(openbb_portfolio_intel.__file__).parent
    pyproject = pkg_dir.parent / "pyproject.toml"
    body = pyproject.read_text(encoding="utf-8")
    # The plugin-declaration line format is:
    #   portfolio_intel = "openbb_portfolio_intel.portfolio_intel_router:router"
    assert (
        'portfolio_intel = "openbb_portfolio_intel.portfolio_intel_router:router"'
        in body
    ), (
        "openbb_core_extension entry-point must be `portfolio_intel = "
        '"openbb_portfolio_intel.portfolio_intel_router:router"` '
        "(underscore, matches the obb.portfolio_intel.* namespace)"
    )


def test_docs_advertise_underscore_namespace_not_dot_namespace() -> None:
    """README / docstrings must not promise the wrong namespace.

    PR #466 review finding 1: several places advertised `obb.portfolio.intel.*`
    which would silently be `obb.portfolio_intel.*`. Grep every doc-adjacent
    file in this extension for the WRONG form and fail if any survives.
    """
    from pathlib import Path

    import openbb_portfolio_intel

    ext_root = Path(openbb_portfolio_intel.__file__).parent.parent
    wrong = "obb.portfolio.intel."
    right = "obb.portfolio_intel."

    for f in list(ext_root.rglob("*.py")) + list(ext_root.rglob("*.md")):
        # Skip this test file itself; its docstring names both forms.
        if f == Path(__file__):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if wrong in text:
            pytest.fail(
                f"{f.relative_to(ext_root)} advertises {wrong!r} — "
                f"the actual runtime namespace is {right!r}. Update the "
                "doc/comment. See PR #466 review finding 1."
            )


def test_about_command_uses_return_annotation_not_model_string() -> None:
    """`@router.command` must NOT pass model=<str> for an extension-local model.

    PR #466 review finding 4: passing ``model="ExtensionAbout"`` triggers
    OpenBB's standard-models registry lookup, which fails for a locally-
    defined `BaseModel` never registered anywhere. Backtest's `about`
    uses ``@router.command(methods=["GET"])`` and relies on the
    ``OBBject[BacktestAbout]`` return annotation instead. Match that.
    """
    from pathlib import Path

    import openbb_portfolio_intel.portfolio_intel_router as pim_router

    src = Path(pim_router.__file__).read_text(encoding="utf-8")
    # Find the @router.command block immediately preceding `def about(`.
    import re

    m = re.search(r"@router\.command\(([^)]*)\)\s*\ndef about\(", src)
    assert m, "could not locate @router.command(...) preceding `def about(`"
    decorator_args = m.group(1)
    assert 'model="' not in decorator_args and "model='" not in decorator_args, (
        "@router.command for about() must not pass model=<string> for "
        "an extension-local BaseModel — use the return-type annotation "
        "instead (matches openbb_backtest.backtest_router.about)"
    )


def test_include_subrouters_only_swallows_own_missing_modules() -> None:
    """`_include_subrouters` must narrow ImportError to expected paths.

    PR #466 review finding 2: a blanket ``except ImportError`` would
    silently drop a sub-router when a TRANSITIVE import inside that
    sub-router failed (e.g. a typo in `from openbb_core.something import
    X`). Assert the current implementation is the narrower
    ``ModuleNotFoundError`` guard.

    Issue #802 fix: the guard now accepts both the exact ``module_path``
    AND any ancestor package (``module_path.startswith(exc.name + ".")``),
    because ``ModuleNotFoundError.name`` reports the deepest missing
    ancestor, not the target module. Prior guard (``exc.name ==
    module_path`` only) crashed the extension load when the parent
    ``openbb_portfolio_intel.routers`` package didn't exist yet.
    """
    from pathlib import Path

    import openbb_portfolio_intel.portfolio_intel_router as pim_router

    src = Path(pim_router.__file__).read_text(encoding="utf-8")
    assert "except ModuleNotFoundError" in src, (
        "must narrow to ModuleNotFoundError, not blanket ImportError, "
        "so real typos in sub-router deps surface (PR #466 review)"
    )
    # The fix widens acceptance to any ancestor. Assert BOTH exact-match
    # and ancestor-match branches are present so a future refactor can't
    # regress to the old too-narrow guard without failing this test.
    assert "missing == module_path" in src, (
        "must accept the exact-leaf-missing case (all sub-routers not yet "
        "implemented — original PR #466 intent)"
    )
    assert 'module_path.startswith(missing + ".")' in src, (
        "must also accept any-ancestor-missing case (parent `routers` "
        "package not yet created — issue #802 root cause). Without this "
        "branch, a missing intermediate package re-raises and crashes "
        "the extension load."
    )
    assert "missing is not None" in src, (
        "must guard against exc.name being None (bare "
        "`raise ModuleNotFoundError()` sets .name to None per typeshed) "
        "— otherwise the ancestor-check would crash with TypeError on "
        "None + '.'."
    )


def test_include_subrouters_silent_when_all_missing_including_parent() -> None:
    """Reproduces issue #802 root cause and asserts the fix.

    Repro: with no ``openbb_portfolio_intel.routers`` package on disk,
    calling ``_include_subrouters()`` must complete silently (all
    sub-routers are "not yet implemented"). Before the #802 fix, this
    raised ``ModuleNotFoundError: No module named
    'openbb_portfolio_intel.routers'`` at the FIRST iteration of the
    loop because the guard checked ``exc.name == module_path`` (leaf)
    but the actual missing name was the parent package.
    """
    import openbb_portfolio_intel.portfolio_intel_router as pim_router

    # Confirm the fixture: parent package does NOT exist on disk.
    with pytest.raises(ModuleNotFoundError):
        __import__("openbb_portfolio_intel.routers")

    # Post-#802-fix: the call must return None cleanly, not raise.
    result = pim_router._include_subrouters()
    assert result is None


def test_include_subrouters_reraises_unrelated_missing_dep(monkeypatch) -> None:
    """The guard must not swallow a genuine transitive-dep miss.

    If a sub-router IS implemented and its own body imports a genuinely
    missing dependency (e.g. ``from some_missing_pkg import X``), the
    resulting ``ModuleNotFoundError.name == "some_missing_pkg"`` — which
    is neither the leaf nor an ancestor of the sub-router's module_path.
    The guard MUST re-raise so CI surfaces the real bug.

    This is the invariant the PR #466 review demanded and #802's fix
    preserves.
    """
    import sys
    import types

    import openbb_portfolio_intel.portfolio_intel_router as pim_router

    # Inject a fake `openbb_portfolio_intel.routers` parent package so
    # the leaf-import can proceed to the sub-router module body.
    fake_parent = types.ModuleType("openbb_portfolio_intel.routers")
    fake_parent.__path__ = []  # mark as package
    monkeypatch.setitem(sys.modules, "openbb_portfolio_intel.routers", fake_parent)

    # Inject a fake xray_router whose module-body raises on import.
    class _BadFinder:
        """Meta-path finder that makes the xray_router raise on import."""

        def find_spec(self, fullname, path=None, target=None):  # noqa: ARG002
            if fullname == "openbb_portfolio_intel.routers.xray_router":
                # Raise a ModuleNotFoundError naming an *unrelated* package.
                raise ModuleNotFoundError(
                    "No module named 'some_missing_pkg'",
                    name="some_missing_pkg",
                )
            return None

    monkeypatch.setattr(sys, "meta_path", [_BadFinder(), *sys.meta_path])

    with pytest.raises(ModuleNotFoundError) as excinfo:
        pim_router._include_subrouters()
    assert excinfo.value.name == "some_missing_pkg", (
        "the transitive-dep miss must propagate; the guard must not "
        "swallow it just because it happened during a sub-router import"
    )


def test_include_subrouters_reraises_when_exc_name_is_none(monkeypatch) -> None:
    """The guard must not crash — and must re-raise — when exc.name is None.

    A bare ``raise ModuleNotFoundError()`` (or ``ModuleNotFoundError("msg")``
    without the ``name=`` kwarg) leaves ``exc.name`` as ``None`` per
    typeshed. The guard must not attempt string concatenation with None
    (would raise ``TypeError: unsupported operand type(s) for +: 'NoneType'
    and 'str'``), and must re-raise the ModuleNotFoundError untouched
    since we cannot classify its provenance.
    """
    import sys

    import openbb_portfolio_intel.portfolio_intel_router as pim_router

    class _NamelessFinder:
        """Meta-path finder that raises ModuleNotFoundError with name=None."""

        def find_spec(self, fullname, path=None, target=None):  # noqa: ARG002
            if fullname.startswith("openbb_portfolio_intel.routers"):
                raise ModuleNotFoundError("unnamed miss")

    monkeypatch.setattr(sys, "meta_path", [_NamelessFinder(), *sys.meta_path])

    with pytest.raises(ModuleNotFoundError) as excinfo:
        pim_router._include_subrouters()
    assert excinfo.value.name is None
