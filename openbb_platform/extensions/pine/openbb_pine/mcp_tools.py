"""MCP tool registration hook for openbb-extension-pine bundled indicators.

Per D3 §7: openbb-mcp-server (when installed) discovers each installed
OpenBB extension's optional ``mcp_tools.register(mcp_server)`` entry point
at startup. For openbb-pine, this hook maps every widget in
:func:`openbb_pine._load_bundled_widgets` (bead 0e9.5.53) to a callable
MCP tool with the naming convention ``pine_<widget_id>`` — so an MCP
client can invoke, e.g., ``pine_bollinger_bands(symbol="AAPL")`` and
receive an OHLCV+series payload back from ``/api/v1/pine/run``.

M1 posture (this bead)
----------------------

The MCP server surface itself is a Phase-3 concern (D3 §7.3 -- launches
alongside M4 real-user telemetry). For M1 we ship only the wiring:

* :func:`register` — the entry point openbb-mcp-server looks for. Iterates
  bundled widgets and calls ``mcp_server.register_tool(...)`` for each.
* :func:`_derive_schema_from_widget` — turns a widget's ``params`` dict
  into a JSON schema so MCP clients can pre-validate arguments.
* :func:`_dispatch_via_pine_run` — the callable body each tool wraps.
  Delegates to the compile+run pipeline via ``obb.pine.run(...)`` when the
  full OpenBB Platform is loaded, or raises a clear error when not (dev
  scenarios where only openbb-pine is importable).

A `mock` MCP server (any object with ``.register_tool(name=..., description=...,
handler=..., schema=...)``) is enough to exercise the registration path in
unit tests — see :mod:`openbb_pine.tests.unit.test_mcp_tools`.

Clean-room posture (PRD §2.1): this module is a Phase-1 scaffold; no
external MCP server implementations were consulted.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from openbb_pine import _load_bundled_widgets

__all__ = [
    "MCPServerLike",
    "register",
]


# ---------------------------------------------------------------------------
# Structural type: what the hook needs from openbb-mcp-server.
# ---------------------------------------------------------------------------


class MCPServerLike(Protocol):
    """The minimal MCP-server shape :func:`register` requires.

    :mod:`openbb_mcp_server` supplies a full class; this protocol lets us
    unit-test with a plain :class:`unittest.mock.Mock` and defines the
    contract as narrowly as possible so a version-bump of the MCP surface
    can be evaluated against this signature alone.
    """

    def register_tool(
        self,
        *,
        name: str,
        description: str,
        handler: Callable[..., Any],
        schema: dict[str, Any],
    ) -> None:
        ...  # pragma: no cover -- structural protocol


# ---------------------------------------------------------------------------
# Registration hook — the public surface openbb-mcp-server looks for.
# ---------------------------------------------------------------------------


def register(mcp_server: MCPServerLike) -> None:
    """Register every bundled Pine widget as an MCP tool.

    Called by :mod:`openbb_mcp_server` at startup **if** openbb-pine is
    installed. Iterates :func:`openbb_pine._load_bundled_widgets`; for each
    widget id ``w`` it registers a tool named ``w`` (already prefixed with
    ``pine_`` in widgets.json) whose handler dispatches to the widget's
    ``endpoint`` (currently always ``/api/v1/pine/run``) with the widget's
    default ``params`` merged with any overrides the MCP client supplies.

    Parameters
    ----------
    mcp_server
        Any object implementing :class:`MCPServerLike`. In production this
        is :class:`openbb_mcp_server.MCPServer`; in tests it is a
        :class:`unittest.mock.Mock`.
    """
    for widget_id, spec in _load_bundled_widgets().items():
        mcp_server.register_tool(
            name=widget_id,
            description=str(spec.get("description", "")),
            handler=_make_tool_handler(widget_id, spec),
            schema=_derive_schema_from_widget(spec),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _derive_schema_from_widget(spec: dict[str, Any]) -> dict[str, Any]:
    """Turn a widget's ``params`` dict into a JSON schema.

    We do a lightweight best-effort: every key in ``params`` becomes a
    property in the schema with an inferred type from the default value's
    Python type. This is sufficient for MCP clients to pre-validate
    argument shapes; the authoritative validation still happens at the
    ``/api/v1/pine/run`` endpoint via its Pydantic model
    (:class:`openbb_pine.routers._models.PineRunRequest`).
    """
    params = spec.get("params", {})
    properties: dict[str, dict[str, str]] = {}
    for key, value in params.items():
        properties[key] = {"type": _json_type_of(value)}
    return {
        "type": "object",
        "properties": properties,
        # Nothing is strictly required — every widget param carries a
        # default so the MCP client can invoke the tool with no args and
        # still land on a valid Pine run.
        "required": [],
        "additionalProperties": True,
    }


def _json_type_of(value: Any) -> str:
    """Map a Python default value to the corresponding JSON schema type.

    Fallback is ``"string"`` — an unknown Python type at least won't fail
    schema validation on the string side (the pine-run endpoint's own
    validator does the strict typing).
    """
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _make_tool_handler(
    widget_id: str, spec: dict[str, Any]
) -> Callable[..., Any]:
    """Build the callable that fires when the MCP client invokes the tool.

    Captures the widget id + spec so the closure knows which defaults to
    merge into the call. The handler itself is a thin wrapper around
    :func:`_dispatch_via_pine_run` — that indirection lets tests inspect
    both layers separately.
    """
    def handler(**overrides: Any) -> Any:
        return _dispatch_via_pine_run(widget_id, spec, **overrides)

    handler.__name__ = f"handler_{widget_id}"
    handler.__doc__ = (
        f"MCP handler for widget {widget_id!r}. Merges caller overrides "
        f"into the widget's default params and dispatches via "
        f"{spec.get('endpoint', '/api/v1/pine/run')}."
    )
    return handler


def _dispatch_via_pine_run(
    widget_id: str, spec: dict[str, Any], **overrides: Any
) -> Any:
    """Merge overrides into widget defaults and dispatch through obb.pine.run.

    M1 scope: the dispatch path itself is stubbed to raise
    :class:`NotImplementedError` — the real MCP server integration lands
    with M4 launch (D3 §7.3). The wiring proves the plumbing works; the
    body will be filled when the MCP server ships. Unit tests exercise
    the schema + closure shape rather than the dispatch body.
    """
    merged_params = {**spec.get("params", {}), **overrides}
    # Deferred wiring — see docstring. Kept as a hard error so accidentally
    # hitting this from a live MCP server surfaces loudly rather than
    # returning a stale / empty payload.
    raise NotImplementedError(
        f"openbb_pine.mcp_tools: MCP dispatch for {widget_id!r} is a "
        f"scaffold at M1. Real dispatch through obb.pine.run(**params) "
        f"lands with the M4 launch. Merged params were: "
        f"{sorted(merged_params.keys())}."
    )
