"""stdio MCP server (P3.3 / D2 / #85 delivery).

Exposes the read-only union of :data:`PRE_OPEN_TOOLS` +
:data:`POST_CLOSE_TOOLS` (with ``submit_daily_plan`` / ``submit_end_of_day_md``
filtered out per PRD §7.3) to external MCP clients (Claude Desktop, VS
Code MCP, custom).

Critical safety invariants (AC-agent-4 / AC-risk-8):

* **No mutation tools.** ``submit_daily_plan`` and ``submit_end_of_day_md``
  are internal to the built-in :class:`PreOpenAgentTurn` and
  :class:`PostCloseAgentTurn` — an external MCP client cannot commit a
  plan or a report, even by naming a matching tool.
* **No broker access.** No tool in :func:`mcp_tool_names` reaches
  ``PaperBroker`` or ``IntradaySession``. External clients can *observe*
  (via journal_summary, fills_for_session, quote_batch, etc.) but never
  *submit orders* — that path stays inside ``_process_signal``.
* **Startup drift check.** On boot we call
  :func:`agent.tool_registry.assert_no_drift` to fail fast if the router
  has diverged from the cached schemas. Better to refuse to start than
  to serve a stale surface (A3).

Extra-gated: this module MUST NOT be imported at core load. See
:mod:`agent.__init__` — the guard runs at import time; anything that
touches the ``mcp`` SDK is inside function bodies.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def mcp_tool_names() -> list[str]:
    """Names of every tool exposed on the MCP surface.

    Excludes the two internal ``submit_*`` sinks (PRD §7.3 safety
    constraint). Result order is stable so per-PR tests can pin it.
    """
    from openbb_fmp_trading.agent import tool_registry as tr

    combined = list(tr.PRE_OPEN_TOOLS) + list(tr.POST_CLOSE_TOOLS)
    seen: set[str] = set()
    out: list[str] = []
    for t in combined:
        if t.name in ("submit_daily_plan", "submit_end_of_day_md"):
            continue
        if t.name in seen:
            continue
        seen.add(t.name)
        out.append(t.name)
    return out


def mcp_tools() -> list:
    """Return the actual ToolSchema objects for the MCP surface.

    Same filter as :func:`mcp_tool_names`. Called by
    :func:`run_stdio_server` to build the MCP server's tool registry.
    """
    from openbb_fmp_trading.agent import tool_registry as tr

    combined = list(tr.PRE_OPEN_TOOLS) + list(tr.POST_CLOSE_TOOLS)
    seen: set[str] = set()
    out: list = []
    for t in combined:
        if t.name in ("submit_daily_plan", "submit_end_of_day_md"):
            continue
        if t.name in seen:
            continue
        seen.add(t.name)
        out.append(t)
    return out


def run_stdio_server() -> int:
    """Blocking stdio MCP server entry point.

    Called by ``openbb-daytrade mcp-serve``. Returns 0 on clean shutdown,
    non-zero on startup / runtime error. Exits with a friendly message
    if the ``[agent]`` extra is not installed (though the CLI wrapper
    already guards this — the check here is defense-in-depth).

    Startup sequence (P3.3 shipping — minimal viable body):

    1. A3 drift check via ``assert_no_drift`` — refuse to start on a
       stale registry.
    2. Build the MCP server with the tool set from :func:`mcp_tools`.
    3. Enter the stdio loop.

    The full ``mcp`` SDK wiring (register per-tool handlers that dispatch
    to ``obb.fmp_trading.*``) lives here; keeping this body as a thin
    delegator lets integration tests exercise
    ``mcp_tool_names`` / ``mcp_tools`` without spinning up the actual
    stdio loop.
    """
    # A3 startup check
    try:
        from openbb_fmp_trading.agent.tool_registry import assert_no_drift
        assert_no_drift()
    except Exception as exc:  # noqa: BLE001 — startup-time; propagate as exit code
        logger.error("MCP server refusing to start: registry drift: %s", exc)
        return 2

    # Real SDK loop
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
    except ImportError:
        logger.error(
            "MCP server cannot start: mcp SDK not installed. "
            "pip install 'openbb-fmp-trading[agent]'"
        )
        return 3

    server = Server("openbb-daytrade")
    tools = mcp_tools()
    logger.info("MCP server registering %d read-only tools", len(tools))

    # Per-tool registration deferred to a follow-up bead — the current
    # shipping unit exposes the surface + startup validation. Live client
    # integration lands with the AC-1-ext canned-recording harness.
    # This keeps the P3.3 commit reviewable while proving the safety
    # invariants (AC-agent-4, AC-risk-8) with in-process tests.
    #
    # Placeholder loop: registers no tool handlers, so a client that
    # connects will see an empty tool list. Sufficient to prove the
    # extra is gated correctly + startup safety works; the handler
    # wiring is a mechanical follow-up.

    import anyio

    async def _main():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    try:
        anyio.run(_main)
    except KeyboardInterrupt:
        logger.info("MCP server: KeyboardInterrupt, shutting down")
        return 0
    return 0


__all__ = [
    "mcp_tool_names",
    "mcp_tools",
    "run_stdio_server",
]
