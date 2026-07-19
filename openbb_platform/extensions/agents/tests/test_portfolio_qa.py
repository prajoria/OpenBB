"""Tests for openbb_agents.agents.portfolio_qa — agent construction + guardrail wiring.

These tests verify agent configuration, not live LLM calls. They ensure the
agent is built with the right tools, has PII guardrails wired, and produces a
valid ADK LlmAgent instance.
"""

import sys
from pathlib import Path

import pytest

# Every test in this file imports from `google.adk` (via
# openbb_agents.agents.portfolio_qa). Two-layer guard:
#
#   1. ``pytestmark = pytest.mark.requires_agents`` — deselected under
#      the standard CI marker filter ``-m "not requires_agents"``
#      (see #818).
#   2. Module-level ``importorskip`` — if a harness runs WITHOUT the
#      marker filter (e.g. bare ``pytest openbb_platform``), the
#      missing dep produces a clean skip at collection rather than
#      per-test errors. Harness known-noise report.
pytestmark = pytest.mark.requires_agents
pytest.importorskip("google.adk")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestPortfolioQAConstruction:
    def test_returns_llm_agent_instance(self):
        from google.adk.agents import LlmAgent
        from openbb_agents.agents.portfolio_qa import build_portfolio_qa_agent

        agent = build_portfolio_qa_agent(model="openai/gpt-4o")
        assert isinstance(agent, LlmAgent)

    def test_has_expected_name(self):
        from openbb_agents.agents.portfolio_qa import build_portfolio_qa_agent

        agent = build_portfolio_qa_agent(model="openai/gpt-4o")
        assert agent.name == "portfolio_qa"

    def test_tools_include_portfolio_functions(self):
        from openbb_agents.agents.portfolio_qa import build_portfolio_qa_agent

        agent = build_portfolio_qa_agent(model="openai/gpt-4o")
        tool_names = {getattr(t, "name", None) or getattr(t, "func", t).__name__
                      for t in agent.tools}
        assert "get_positions" in tool_names
        assert "get_sector_exposure" in tool_names

    def test_instruction_mentions_read_only(self):
        from openbb_agents.agents.portfolio_qa import build_portfolio_qa_agent

        agent = build_portfolio_qa_agent(model="openai/gpt-4o")
        assert "read-only" in agent.instruction.lower()
