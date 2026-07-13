"""AC-agent-4 + AC-risk-8: MCP surface is READ-ONLY.

Verifies the two invariants that make external-MCP-client access safe:

  AC-agent-4: submit_daily_plan / submit_end_of_day_md are NOT on the
              MCP surface (PRD 7.3 — external clients can't commit).
  AC-risk-8:  No tool returns or mutates a broker/session reference.

Together these guarantee an attacker who compromises an MCP client can
observe but cannot trade. The chokepoint invariant from Phase 2 P2.4
holds: broker.submit is only reachable via IntradaySession._process_signal,
which is not exposed as a tool.
"""

from __future__ import annotations

import pytest


class TestMCPSurfaceExcludesMutation:
    def test_submit_daily_plan_not_on_surface(self):
        from openbb_fmp_trading.agent.mcp_server import mcp_tool_names

        assert "submit_daily_plan" not in mcp_tool_names()

    def test_submit_end_of_day_md_not_on_surface(self):
        from openbb_fmp_trading.agent.mcp_server import mcp_tool_names

        assert "submit_end_of_day_md" not in mcp_tool_names()


class TestMCPSurfaceExcludesBroker:
    """AC-risk-8: no broker-shaped tool leaks onto the surface."""

    def test_no_broker_in_any_tool_name(self):
        from openbb_fmp_trading.agent.mcp_server import mcp_tool_names

        forbidden_substrings = ("broker", "submit_order", "place_order",
                                "cancel_order", "close_position")
        for name in mcp_tool_names():
            for forbidden in forbidden_substrings:
                assert forbidden not in name.lower(), (
                    f"Tool '{name}' contains forbidden substring '{forbidden}' — "
                    "broker/order mutation must not be reachable via MCP"
                )

    def test_no_broker_in_any_tool_description(self):
        """A tool named innocently but described as 'submits orders' also
        counts as a leak."""
        from openbb_fmp_trading.agent.mcp_server import mcp_tools

        for tool in mcp_tools():
            desc = tool.description.lower()
            # 'submit' alone is fine (e.g. submit_daily_plan is filtered
            # out already, and no read-only tool should mention submitting).
            # 'broker' or 'order' in the description of a READ tool is
            # suspicious — the read tools deal with quotes, movers, news,
            # journal summaries.
            assert "broker" not in desc, (
                f"Tool '{tool.name}' description mentions 'broker': {desc!r}"
            )


class TestMCPSurfaceUnionMinusSubmits:
    """AC-agent-4 contract: MCP = PRE_OPEN ∪ POST_CLOSE − {submit_*}."""

    def test_surface_is_union_of_registered_tools_minus_submits(self):
        from openbb_fmp_trading.agent import tool_registry as tr
        from openbb_fmp_trading.agent.mcp_server import mcp_tool_names

        expected = set()
        for t in list(tr.PRE_OPEN_TOOLS) + list(tr.POST_CLOSE_TOOLS):
            if t.name in ("submit_daily_plan", "submit_end_of_day_md"):
                continue
            expected.add(t.name)

        assert set(mcp_tool_names()) == expected

    def test_surface_is_non_empty(self):
        """Sanity: if the read-only surface were empty, the MCP server
        would be pointless."""
        from openbb_fmp_trading.agent.mcp_server import mcp_tool_names

        assert len(mcp_tool_names()) > 0

    def test_surface_names_are_unique(self):
        """De-duplication contract: even when PRE_OPEN + POST_CLOSE
        both include the same read-only tool (e.g., session_status),
        it appears exactly once on the merged surface."""
        from openbb_fmp_trading.agent.mcp_server import mcp_tool_names

        names = mcp_tool_names()
        assert len(names) == len(set(names))


class TestAllowlistFailClosed:
    """Security-review recommendation: MCP filter is an allowlist, not
    a denylist. A new tool without ``mcp_exposed=True`` stays OFF the
    surface by default — fail-closed, not fail-open."""

    def test_new_tool_without_flag_stays_off_surface(self, monkeypatch):
        """Adding a hypothetical mutation tool to PRE_OPEN_TOOLS without
        the mcp_exposed flag must NOT leak it onto the MCP surface."""
        from openbb_fmp_trading.agent import tool_registry as tr
        from openbb_fmp_trading.agent.mcp_server import mcp_tool_names
        from openbb_fmp_trading.agent.tool_registry import ToolSchema

        # Inject a fake mutation tool that DIDN'T get the mcp_exposed flag.
        # In the old denylist world this would have leaked onto the MCP
        # surface (name isn't in the {submit_daily_plan, submit_end_of_day_md}
        # denylist). Under the allowlist, it stays off.
        malicious_tool = ToolSchema(
            name="place_market_order",
            description="A future mutation tool a maintainer forgot to flag.",
            input_schema={"type": "object"},
            # NOTE: mcp_exposed defaults to False — no explicit flag set
        )
        monkeypatch.setattr(
            tr, "PRE_OPEN_TOOLS", list(tr.PRE_OPEN_TOOLS) + [malicious_tool],
        )

        names = mcp_tool_names()
        assert "place_market_order" not in names, (
            "Allowlist failed closed as required: a new tool without "
            "mcp_exposed=True leaked onto the MCP surface"
        )

    def test_new_tool_with_explicit_flag_appears_on_surface(self, monkeypatch):
        """Positive: adding a tool WITH mcp_exposed=True does appear."""
        from openbb_fmp_trading.agent import tool_registry as tr
        from openbb_fmp_trading.agent.mcp_server import mcp_tool_names
        from openbb_fmp_trading.agent.tool_registry import ToolSchema

        opted_in_tool = ToolSchema(
            name="new_read_only_tool",
            description="Legitimate new read-only tool.",
            input_schema={"type": "object"},
            mcp_exposed=True,
        )
        monkeypatch.setattr(
            tr, "PRE_OPEN_TOOLS", list(tr.PRE_OPEN_TOOLS) + [opted_in_tool],
        )

        assert "new_read_only_tool" in mcp_tool_names()

    def test_submit_daily_plan_stays_off_via_allowlist(self):
        """Belt-and-suspenders: submit_* still off because they don't
        opt in — the change from denylist to allowlist should preserve
        this."""
        from openbb_fmp_trading.agent.mcp_server import mcp_tool_names

        assert "submit_daily_plan" not in mcp_tool_names()
        assert "submit_end_of_day_md" not in mcp_tool_names()


class TestExpectedReadOnlyToolsPresent:
    """Positive check: the read-only tools we DO want are actually there."""

    @pytest.mark.parametrize("name", [
        "quote_batch",
        "market_movers",
        "company_news",
        "session_status",
        "journal_summary",
        "fills_for_session",
    ])
    def test_expected_read_only_tool_on_surface(self, name):
        from openbb_fmp_trading.agent.mcp_server import mcp_tool_names

        assert name in mcp_tool_names()
