"""fmp_trading agent turns + MCP server (Phase 3, ``[agent]`` extra).

Every module in this package is extra-gated. Core imports MUST NOT
reach this package — see :mod:`tests.unit.test_tool_registry_not_on_core_import`
for the enforcement (A3 P0 from the design review).

Layout:

* :mod:`.errors`             — AgentError hierarchy (AgentUnavailable,
                                RiskOverrideLoosening, RegistryDrift)
* :mod:`.backend`            — AgentBackend Protocol + ClaudeAgentBackend
                                + AlwaysUnavailableBackend
* :mod:`.tool_registry`      — auto-generated tool schemas from
                                ``obb.fmp_trading.*`` router
* :mod:`.tradable_universe`  — allowlist for A1 injection defense
* :mod:`.pre_open`           — PreOpenAgentTurn + deterministic fallback
* :mod:`.post_close`         — PostCloseAgentTurn + Jinja narrator (P3.2)
* :mod:`.mcp_server`         — stdio MCP server (P3.3)
"""

from __future__ import annotations

# Detect whether the [agent] extra is installed. This is the ONE thing
# agent/__init__ does at import time — everything else is lazy so a
# `from openbb_fmp_trading.agent import is_agent_available` call from
# outside the package (e.g. cli.py) is cheap and doesn't drag in
# anthropic/mcp/jinja if they're absent.
try:
    import anthropic  # noqa: F401 — imported for availability check only
    import mcp  # noqa: F401
    _AGENT_EXTRA_AVAILABLE = True
except ImportError:
    _AGENT_EXTRA_AVAILABLE = False


def is_agent_available() -> bool:
    """True iff ``pip install openbb-fmp-trading[agent]`` has run.

    CLI subcommands (``openbb-daytrade pre-open`` / ``post-close`` /
    ``mcp-serve``) use this to emit a friendly install-hint on missing
    extra rather than an ImportError stack trace.
    """
    return _AGENT_EXTRA_AVAILABLE


__all__ = ["is_agent_available"]
