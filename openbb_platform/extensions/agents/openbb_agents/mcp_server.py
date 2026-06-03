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
        if descriptor is None:
            raise ValueError(f"Unknown tool: {name!r}")
        fn = descriptor["fn"]
        try:
            result = fn(**arguments)
            return [TextContent(type="text", text=json.dumps(result, default=str))]
        except Exception as exc:
            logger.error("Tool %r raised: %s", name, exc, exc_info=True)
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]

    async with stdio_server() as (read_stream, write_stream):
        init_opts = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_opts)


def main() -> None:
    """Console-script entry point."""
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
