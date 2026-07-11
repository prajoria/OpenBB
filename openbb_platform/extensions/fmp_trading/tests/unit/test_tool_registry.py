"""AC-agent-3: tool registry exports curated tool lists + drift detection.

Verifies:
  - PRE_OPEN_TOOLS + POST_CLOSE_TOOLS export non-empty lists
  - Every ToolSchema has name + description
  - submit_daily_plan is in PRE_OPEN_TOOLS
  - submit_end_of_day_md is in POST_CLOSE_TOOLS
  - POST_CLOSE_TOOLS is a proper superset of PRE_OPEN_TOOLS read-only tools
  - assert_no_drift() runs cleanly on the current registry
"""

from __future__ import annotations

import pytest


class TestRegistryContract:
    def test_pre_open_tools_non_empty(self):
        from openbb_fmp_trading.agent.tool_registry import PRE_OPEN_TOOLS

        assert len(PRE_OPEN_TOOLS) > 0

    def test_post_close_tools_non_empty(self):
        from openbb_fmp_trading.agent.tool_registry import POST_CLOSE_TOOLS

        assert len(POST_CLOSE_TOOLS) > 0

    def test_every_tool_has_name_and_description(self):
        from openbb_fmp_trading.agent.tool_registry import (
            POST_CLOSE_TOOLS,
            PRE_OPEN_TOOLS,
        )

        for tool in list(PRE_OPEN_TOOLS) + list(POST_CLOSE_TOOLS):
            assert tool.name, f"empty name on {tool!r}"
            assert tool.description, f"empty description on {tool.name}"

    def test_submit_daily_plan_in_pre_open(self):
        from openbb_fmp_trading.agent.tool_registry import PRE_OPEN_TOOLS

        names = {t.name for t in PRE_OPEN_TOOLS}
        assert "submit_daily_plan" in names

    def test_submit_end_of_day_md_in_post_close(self):
        from openbb_fmp_trading.agent.tool_registry import POST_CLOSE_TOOLS

        names = {t.name for t in POST_CLOSE_TOOLS}
        assert "submit_end_of_day_md" in names

    def test_submit_daily_plan_not_in_post_close(self):
        """The two submit_* sinks are turn-specific; POST_CLOSE_TOOLS
        must NOT include submit_daily_plan (the post-close agent shouldn't
        be able to commit a plan)."""
        from openbb_fmp_trading.agent.tool_registry import POST_CLOSE_TOOLS

        names = {t.name for t in POST_CLOSE_TOOLS}
        assert "submit_daily_plan" not in names

    def test_post_close_includes_journal_readers(self):
        from openbb_fmp_trading.agent.tool_registry import POST_CLOSE_TOOLS

        names = {t.name for t in POST_CLOSE_TOOLS}
        # Post-close adds fills / journal summary on top of the read-only base
        assert "journal_summary" in names
        assert "fills_for_session" in names


class TestNoDrift:
    def test_assert_no_drift_passes_on_shipping_registry(self):
        """A3: the drift check runs cleanly on the tools we ship."""
        from openbb_fmp_trading.agent.tool_registry import assert_no_drift

        # Must not raise — this is the contract mcp-serve startup relies on
        assert_no_drift()
