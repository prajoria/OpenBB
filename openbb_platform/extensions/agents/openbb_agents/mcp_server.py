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
    """Scan ``_TOOL_MODULES`` and return one descriptor dict per public function.

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
            # Only register functions defined in this module (skip re-exports)
            if fn.__module__ != module.__name__:
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


def _call_tool_safe(
    descriptor: dict | None,
    arguments: dict,
    name: str | None = None,
) -> list[str]:
    """Invoke ``descriptor['fn']`` with ``arguments`` and return the safe payload.

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

    Returns a list of ONE json-encoded string (the MCP protocol wraps
    it in a ``TextContent`` at the ``@server.call_tool`` seam — kept as
    a plain string here so this helper is unit-testable without the
    MCP types).

    Passing ``descriptor=None`` returns the unknown-tool error variant
    (``{'error': 'unknown_tool', 'tool': <name>}``). The ``name``
    argument is only required for that branch; when descriptor is
    provided it defaults to ``descriptor['name']``.
    """
    if descriptor is None:
        return [json.dumps({"error": "unknown_tool", "tool": name or "?"})]
    tool_name = descriptor.get("name") or name or "?"
    fn = descriptor["fn"]
    try:
        result = fn(**arguments)
        return [json.dumps(result, default=str)]
    except Exception as exc:
        # Log full details locally (operator triage channel) — NOT
        # returned to the LLM. Includes str(exc) via %s formatting and
        # the full traceback via exc_info=True.
        logger.error("Tool %r raised: %s", tool_name, exc, exc_info=True)
        return [json.dumps({"error": "tool_failed", "tool": tool_name})]


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
        # LLM-boundary sanitization contract (bd-9ck7 / bd-lq4l).
        payloads = _call_tool_safe(descriptor, arguments, name=name)
        return [TextContent(type="text", text=p) for p in payloads]

    async with stdio_server() as (read_stream, write_stream):
        init_opts = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_opts)


def main() -> None:
    """Console-script entry point."""
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
