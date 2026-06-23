"""Surface tests for the assembled backtest router (component 09.6).

The capstone of the C09 epic: the four sub-routers (engine 09.2, factor 09.3,
validate 09.4, bundle 09.5) are wired onto the parent ``backtest_router`` and the
``openbb_core_extension`` entry point. These tests lock that surface without any
engine/DB/network -- pure router introspection:

- :func:`test_long_running_commands_are_async` -- the async contract from
  ``09-api-surface.md`` §2: the long-running commands (run / sweep / pipeline /
  validate / tearsheet) are coroutines so the REST layer can stream/poll a
  multi-minute run; the quick orchestration-only commands (factor_eval /
  reconcile / bundle.ingest / bundle.list) stay synchronous.
- :func:`test_all_commands_registered_under_parent` -- every command attaches
  under the parent router (a swallowed ``ImportError`` in ``_include_subrouters``
  would silently drop paths).
- :func:`test_every_command_carries_examples` -- each command carries its
  ``examples`` block, the single source the rendered OpenAPI operations and the
  MCP tool schemas both read from (``route.openapi_extra["examples"]``).

See ``docs/designs/backtest-design/09-api-surface.md`` §1-§3.
"""

from __future__ import annotations

import inspect

# ---- async contract (09-api-surface.md §2) -------------------------------


def test_long_running_commands_are_async():
    # Long-running paths are declared ``async`` so the REST layer can stream/poll
    # a multi-minute backtest/sweep/validation without blocking; quick
    # orchestration-only commands stay synchronous. OpenBB core awaits both
    # transparently (command_runner.maybe_coroutine), so this is invisible to
    # obb.* callers -- it is purely the surface contract from §2.
    from openbb_backtest.routers import (
        bundle_router as br,
        factor_router as fr,
        run_router as rr,
        validate_router as vr,
    )

    long_running = (rr.run, rr.sweep, fr.pipeline, vr.validate, vr.tearsheet)
    quick = (fr.factor_eval, rr.reconcile, br.ingest, br.list)

    for command in long_running:
        assert inspect.iscoroutinefunction(command), f"{command.__name__} must be async"
    for command in quick:
        assert not inspect.iscoroutinefunction(command), f"{command.__name__} must be sync"


# ---- registration under the parent router --------------------------------

#: Every command path the assembled extension must expose (the 9 backtest
#: commands plus the metadata ``/about``). The bundle commands live under the
#: nested ``/bundle`` prefix realized by the sub-router.
_EXPECTED_PATHS = {
    "/run",
    "/sweep",
    "/pipeline",
    "/factor_eval",
    "/tearsheet",
    "/validate",
    "/reconcile",
    "/bundle/ingest",
    "/bundle/list",
    "/about",
}

#: The 9 command paths whose ``examples`` block feeds OpenAPI + MCP (``/about``
#: carries none and is excluded).
_COMMAND_PATHS = _EXPECTED_PATHS - {"/about"}


def _parent_routes() -> dict[str, object]:
    """Map command path -> route on the assembled parent router."""
    from openbb_backtest import backtest_router

    return {
        route.path: route
        for route in backtest_router.router.api_router.routes
        if hasattr(route, "path")
    }


def test_all_commands_registered_under_parent():
    # ``_include_subrouters`` swallows ImportError per sub-router, so a broken
    # sub-router would silently drop its paths. Assert the full surface attaches.
    paths = set(_parent_routes())
    assert paths >= _EXPECTED_PATHS


def test_every_command_carries_examples():
    # ``examples`` is the single source the rendered OpenAPI operations and the
    # MCP tool schemas both read from (stored on ``route.openapi_extra`` by the
    # command decorator -- NOT on ``route.description``, which strips them). Each
    # of the 9 commands must carry at least one ``Example``.
    from openbb_core.app.model.example import Example

    routes = _parent_routes()
    for path in _COMMAND_PATHS:
        route = routes[path]
        examples = (route.openapi_extra or {}).get("examples")
        assert examples, f"{path} must carry examples for OpenAPI/MCP"
        assert all(isinstance(ex, Example) for ex in examples), f"{path} examples must be Example instances"

