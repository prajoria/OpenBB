"""``@mcp_tool`` decorator — the trust-boundary marker for MCP exposure.

Kept in a standalone module so tool modules under ``openbb_agents/tools/``
can import ``mcp_tool`` without pulling in the full ``mcp_server`` (which
in turn imports the tool modules — circular).

Regression fix for OpenBBTechnical-17kv / 6bcf: previously
``collect_tools`` auto-registered every public function in
``_TOOL_MODULES``. A single naming mistake (``def cancel_order``
without a leading underscore) would silently promote a mutating
operation into the LLM's tool set. The decorator flips the default to
"private unless explicitly marked exposed" so new tools require a
reviewer-visible ``@mcp_tool`` line.
"""

from __future__ import annotations


def mcp_tool(fn):
    """Mark ``fn`` as an MCP-exposed tool.

    Sets ``fn.__mcp_exposed__ = True`` and returns the function unchanged
    (no wrapping — the function's signature and call-time behaviour are
    identical to an undecorated one). ``collect_tools`` in
    ``openbb_agents.mcp_server`` requires this attribute before
    registering a function as an LLM-callable tool.

    Note: ``@mcp_tool`` on an underscore-prefixed name is still rejected
    by ``collect_tools`` — belt-and-braces against accidental exposure
    of internal helpers.

    Usage::

        from openbb_agents._mcp_tool import mcp_tool

        @mcp_tool
        def get_positions(...): ...
    """
    fn.__mcp_exposed__ = True
    return fn
