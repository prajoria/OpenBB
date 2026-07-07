"""stdio MCP server for OpenBB Agents.

Auto-discovers every public function in the ``tools/`` layer and exposes each
as an MCP tool over a stdio JSON-RPC transport.  This lets Claude Code,
VS Code Copilot Chat, and any other MCP-capable client call portfolio and
analysis tools without knowing the Python call path.

Entry point
-----------
Run directly::

    .venv_win\\Scripts\\python.exe -m openbb_agents.mcp_server

Or via the installed console script::

    openbb-agents-mcp

Discovery rules
---------------
- All modules listed in ``_TOOL_MODULES`` are scanned.
- Any top-level function whose name does **not** start with ``_`` is
  registered as an MCP tool.
- The function's first-line docstring becomes the tool description.
- Type annotations are converted to a JSON Schema ``inputSchema``.

JSON Schema mapping
-------------------
Only the annotation types present in the current tool layer are mapped:

    str   → {"type": "string"}
    int   → {"type": "integer"}
    float → {"type": "number"}
    bool  → {"type": "boolean"}
    list  → {"type": "array"}
    dict  → {"type": "object"}

Unannotated parameters and complex types fall back to ``{}``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any, get_type_hints

logger = logging.getLogger(__name__)

# ── modules to scan for public tools ────────────────────────────────────────
from openbb_agents.tools import portfolio_tools  # noqa: E402

_TOOL_MODULES = [portfolio_tools]  # extend as more tool modules are added

# ── type → JSON Schema primitive map ────────────────────────────────────────
_TYPE_MAP: dict[Any, dict] = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    list: {"type": "array"},
    dict: {"type": "object"},
}


# ── explicit-opt-in marker for LLM exposure ────────────────────────────────

# Re-export ``mcp_tool`` from the standalone module so callers can use
# ``from openbb_agents.mcp_server import mcp_tool`` (backward-compatible
# import path). The decorator itself lives in ``_mcp_tool.py`` to avoid
# a circular import — tool modules import the decorator, and this module
# imports the tool modules to build the registry.
from openbb_agents._mcp_tool import mcp_tool  # noqa: E402,F401


def build_input_schema(fn: Any) -> dict:
    """Derive a JSON Schema ``inputSchema`` from a function's type hints.

    Parameters with no default are placed in ``required``.  Private
    parameters (name starts with ``_``) are omitted — they are DI hooks
    not intended for external callers.
    """
    try:
        hints = get_type_hints(fn)
    except Exception:
        hints = {}

    sig = inspect.signature(fn)
    properties: dict[str, dict] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name.startswith("_"):
            continue  # skip DI injection hooks
        annotation = hints.get(name)
        schema_type = _TYPE_MAP.get(annotation, {})
        properties[name] = schema_type

        if param.default is inspect.Parameter.empty:
            required.append(name)

    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def collect_tools() -> list[dict]:
    """Scan ``_TOOL_MODULES`` and return one descriptor per ``@mcp_tool``-decorated function.

    Trust-boundary invariant (bd-17kv / bd-6bcf): a function reaches the
    LLM iff it carries ``__mcp_exposed__ = True`` (set by the
    :func:`mcp_tool` decorator). Auto-discovery of every public function
    is off. Underscore-prefixed names are still excluded even if
    someone accidentally decorates one — belt-and-braces.

    Each descriptor has keys:
        name        – function name (used as MCP tool name)
        description – first line of the docstring (or empty string)
        schema      – JSON Schema ``inputSchema``
        fn          – the callable itself
    """
    tools: list[dict] = []
    seen: set[str] = set()

    for module in _TOOL_MODULES:
        for name, fn in inspect.getmembers(module, inspect.isfunction):
            if name.startswith("_") or name in seen:
                continue
            # Belt-and-braces vs. Round-1 review LOW finding:
            # ``public_alias = _private`` at module scope would surface
            # ``_private`` under a public name. ``getmembers`` returns
            # the alias's public name in the loop variable, so also
            # check ``fn.__name__`` — the actual defined name of the
            # underlying function.
            if fn.__name__.startswith("_"):
                continue
            # Only register functions defined in this module (skip re-exports)
            if fn.__module__ != module.__name__:
                continue
            # Explicit opt-in — bd-17kv / bd-6bcf trust-boundary fix.
            # Undecorated public functions are silently skipped rather
            # than being auto-exposed as callable LLM tools. Run this
            # check BEFORE the async guard below so undecorated public
            # async helpers don't log a misleading "Skipping @mcp_tool"
            # warning (Round-2 review cosmetic finding).
            if not getattr(fn, "__mcp_exposed__", False):
                continue
            # Round-1 review MEDIUM: ``async def`` tools would return an
            # un-awaited coroutine from ``fn(**arguments)`` in
            # ``_call_tool_safe``, and ``json.dumps(coro, default=str)``
            # would serialise ``'<coroutine object …>'`` back to the LLM
            # as a 'successful' result — silent failure the operator
            # wouldn't see. Reject at registration time instead so the
            # mistake surfaces loudly at server startup.
            if inspect.iscoroutinefunction(fn):
                logger.warning(
                    "Skipping @mcp_tool %r: async functions are not supported "
                    "by the sync _call_tool_safe path. Convert to sync, or "
                    "extend _call_tool_safe to await coroutine functions.",
                    name,
                )
                continue
            seen.add(name)
            doc = inspect.getdoc(fn) or ""
            first_line = doc.splitlines()[0] if doc else ""
            tools.append(
                {
                    "name": name,
                    "description": first_line,
                    "schema": build_input_schema(fn),
                    "fn": fn,
                }
            )

    return tools


# ── MCP server wiring ────────────────────────────────────────────────────────


class _McpToolError(RuntimeError):
    """Internal marker exception the ``@server.call_tool`` seam raises when
    ``_call_tool_safe`` reports ``is_error=True``.

    The MCP SDK's error path (see ``mcp/server/lowlevel/server.py`` —
    ``_make_error_result(str(error_message))`` in v1.26+) reads ONLY
    ``str(exc)`` when building the wire response and drops any custom
    attributes. So the exception message itself IS the sanitized
    payload — no other channel survives.

    Round-2 review verified this empirically by round-tripping a real
    ``Server`` and ``CallToolRequest``; an earlier design that carried
    the payload on ``self.content`` had that attribute silently
    discarded, leaving only the constant string ``'mcp_tool_error'``
    on the wire. The current shape ensures the sanitized
    ``{'error': …, 'tool': …}`` JSON reaches the LLM as the wire
    content, and ``isError=True`` is preserved by the SDK's error-
    wrapping automatically.
    """

    def __init__(self, payload: str) -> None:
        # payload IS the message; SDK's _make_error_result reads str(self).
        super().__init__(payload)


def _call_tool_safe(
    descriptor: dict | None,
    arguments: dict,
    name: str | None = None,
) -> tuple[list[str], bool]:
    """Invoke ``descriptor['fn']`` and return ``(payloads, is_error)``.

    Wraps the raw tool call with two invariants (bd-9ck7 / bd-lq4l):

    1. **Exception messages are NEVER surfaced to the LLM.** Any raise
       from the tool returns a generic ``{'error': 'tool_failed',
       'tool': <name>}`` payload so credential fragments, absolute file
       paths, DSN strings, HTTP URLs, and other internal state can't be
       exfiltrated through the MCP boundary via prompt injection.
    2. **Full details are logged locally.** The operator running the
       MCP server sees ``str(exc)`` + traceback via ``logger.error(...,
       exc_info=True)`` for triage, but that channel never reaches the
       LLM client.

    Returns ``(payloads, is_error)`` where ``payloads`` is a list of
    ONE json-encoded string (kept as a plain string here so this
    helper is unit-testable without the MCP types). ``is_error`` lets
    the ``@server.call_tool`` seam preserve the MCP-level error signal
    the SDK exposes to clients — old code raised ``ValueError`` for
    unknown tools which the SDK wrapped into a JSON-RPC error response;
    plain returns produce ``isError=False``, so we re-raise or route
    via the SDK's error path when appropriate.

    Passing ``descriptor=None`` returns ``(unknown_tool_payload, True)``.
    """
    if descriptor is None:
        payload = json.dumps({"error": "unknown_tool", "tool": name or "?"})
        return [payload], True
    tool_name = descriptor.get("name") or name or "?"
    fn = descriptor["fn"]
    try:
        result = fn(**arguments)
        return [json.dumps(result, default=str)], False
    except Exception as exc:
        # Log full details locally (operator triage channel) — NOT
        # returned to the LLM. Includes str(exc) via %s formatting and
        # the full traceback via exc_info=True.
        logger.error("Tool %r raised: %s", tool_name, exc, exc_info=True)
        return [json.dumps({"error": "tool_failed", "tool": tool_name})], True


async def _serve() -> None:
    """Build and run the MCP server over stdio."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    server = Server("openbb-agents")
    discovered = collect_tools()
    tool_index = {t["name"]: t for t in discovered}

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["schema"],
            )
            for t in discovered
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        descriptor = tool_index.get(name)
        # Delegate to the testable helper — see _call_tool_safe for the
        # LLM-boundary sanitization contract (bd-9ck7 / bd-lq4l). The
        # is_error flag propagates the MCP-level error signal: raising
        # here lets the SDK wrap the response as isError=True, matching
        # the pre-fix ValueError-raising semantics on the wire.
        payloads, is_error = _call_tool_safe(descriptor, arguments, name=name)
        content = [TextContent(type="text", text=p) for p in payloads]
        if is_error:
            # The MCP SDK's error path (v1.26+ Server._handle_request)
            # calls ``_make_error_result(str(exc))`` and DROPS any
            # custom attributes on the exception. So the exception
            # message MUST be the sanitized JSON payload — anything
            # else disappears on the wire. Round-2 review verified
            # this empirically via a live SDK round-trip.
            # Note: the sanitized payload was already logged as an
            # ERROR via _call_tool_safe; no sensitive state re-enters
            # the traceback here (payloads[0] is the same generic
            # ``{'error': …, 'tool': …}`` json that would have gone
            # in the returned content anyway).
            raise _McpToolError(payloads[0])
        return content

    async with stdio_server() as (read_stream, write_stream):
        init_opts = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_opts)


def main() -> None:
    """Console-script entry point."""
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
