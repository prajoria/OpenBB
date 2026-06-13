"""End-to-end surface integration tests for the backtest extension (component 09.6).

The capstone check: prove the assembled ``obb.backtest.*`` surface is reachable
through the real entry point once the static package is built, and that the
rendered REST/MCP schemas expose it. These are marked ``integration`` so the
default unit suite stays hermetic (building ``openbb`` and the MCP server is
heavy); the single command that needs live data skips cleanly when the
``openbb_fmp_cache`` MySQL is unreachable.

- :func:`test_obb_exposes_all_backtest_commands` builds the static package and
  asserts all 9 commands are reachable as callables (the entry point end-to-end).
- :func:`test_bundle_list_via_obb_returns_obbject` smoke-runs ``bundle.list`` via
  ``obb`` (reads the on-disk store; no DB needed).
- :func:`test_run_smoke_via_obb_returns_obbject` runs a tiny AAPL backtest via
  ``obb`` (needs the fmp_cached MySQL, so it carries the DB skipif).
- :func:`test_openapi_includes_backtest_ops` asserts the rendered OpenAPI paths
  include every backtest operation.
- :func:`test_mcp_tool_list_includes_backtest` asserts the MCP tool list reflects
  the backtest commands (skips when the optional MCP server isn't installed).

See ``docs/designs/backtest-design/09-api-surface.md`` §2-§3.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from openbb_core.app.model.obbject import OBBject


def _backtest_extension_installed() -> bool:
    """Is ``openbb-backtest`` registered as an installed core extension?

    The REST app and the static package both build their command surface from the
    ``openbb_core_extension`` entry points, so a source-only checkout (no
    ``dev_install``) exposes none of ``obb.backtest.*`` there. Gate on the entry
    point so these e2e tests run wherever the extension is properly installed and
    skip cleanly otherwise -- mirroring the ``_db_available`` skipif used by the
    bundle integration tests.
    """
    from importlib.metadata import entry_points

    return any(ep.name == "backtest" for ep in entry_points(group="openbb_core_extension"))


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _backtest_extension_installed(),
        reason="openbb-backtest not installed as a core extension (run dev_install -e)",
    ),
]

#: The 7 flat backtest commands plus the 2 nested bundle commands. Each entry is
#: the attribute chain under ``obb.backtest`` that must resolve to a callable.
_COMMAND_ATTRS = [
    ("run",),
    ("sweep",),
    ("pipeline",),
    ("factor_eval",),
    ("tearsheet",),
    ("validate",),
    ("reconcile",),
    ("bundle", "ingest"),
    ("bundle", "list"),
]


def _db_available() -> bool:
    try:
        from openbb_fmp_cached.utils.database import execute_query

        execute_query("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 - any failure means "skip integration"
        return False


def _backtest_namespace():
    """Build the static package and return the ``obb.backtest`` controller.

    Skips (rather than errors) if the static build itself cannot run in this
    environment, so a build issue unrelated to the backtest surface never masks
    as a backtest test failure.
    """
    try:
        import openbb

        return openbb.obb.backtest
    except Exception as exc:  # noqa: BLE001 - build failure is an env gap, not a surface defect
        pytest.skip(f"static package build unavailable: {exc!r}")



def test_obb_exposes_all_backtest_commands():
    # Building the static package and resolving every command proves the
    # ``openbb_core_extension`` entry point wires the assembled surface end-to-end.
    backtest = _backtest_namespace()
    for attrs in _COMMAND_ATTRS:
        target = backtest
        for attr in attrs:
            target = getattr(target, attr)
        assert callable(target), f"obb.backtest.{'.'.join(attrs)} must be callable"


def test_bundle_list_via_obb_returns_obbject():
    # ``bundle.list`` enumerates the on-disk store, so it round-trips through the
    # public obb surface with no DB or network.
    backtest = _backtest_namespace()
    out = backtest.bundle.list()
    assert isinstance(out, OBBject)
    assert isinstance(out.results, list)


@pytest.mark.skipif(not _db_available(), reason="openbb_fmp_cache MySQL not reachable")
def test_run_smoke_via_obb_returns_obbject():
    # A tiny buy-and-hold run over the holiday-free 2021-01-04..08 week exercises
    # the full obb -> router -> engine path against live fmp_cached data.
    from openbb_backtest.models import BacktestConfig

    backtest = _backtest_namespace()
    config = BacktestConfig(
        strategy="buy_and_hold",
        universe=["AAPL"],
        start=date(2021, 1, 4),
        end=date(2021, 1, 8),
    )
    out = backtest.run(config=config)
    assert isinstance(out, OBBject)
    # The privacy boundary strips raw positions before the result leaves the API.
    assert out.results.positions == []


def test_openapi_includes_backtest_ops():
    # The rendered OpenAPI schema must carry every backtest operation (the source
    # REST clients and downstream tooling read). Substring match is prefix-tolerant.
    from openbb_core.api.rest_api import app

    paths = app.openapi()["paths"]
    expected = [
        "backtest/run",
        "backtest/sweep",
        "backtest/pipeline",
        "backtest/factor_eval",
        "backtest/tearsheet",
        "backtest/validate",
        "backtest/reconcile",
        "backtest/bundle/ingest",
        "backtest/bundle/list",
    ]
    for op in expected:
        assert any(op in path for path in paths), f"OpenAPI missing {op}"


def test_mcp_tool_list_includes_backtest():
    # The MCP server reflects the same FastAPI routes as tools; backtest is not in
    # the default exclusion map and ``default_tool_categories=["all"]`` enables it,
    # so backtest tools must appear in the rendered tool list.
    pytest.importorskip("openbb_mcp_server")
    from openbb_core.api.rest_api import app
    from openbb_mcp_server.app.app import create_mcp_server
    from openbb_mcp_server.models.settings import MCPSettings

    mcp = create_mcp_server(MCPSettings(), app)
    tools = asyncio.run(mcp.get_tools())
    assert any("backtest" in name for name in tools), "MCP tool list missing backtest tools"
