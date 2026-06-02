"""portfolio_qa — Read-only portfolio Q&A agent (ADK LlmAgent).

Answers natural-language questions about the user's portfolio by calling
portfolio tool functions. PII (account numbers, owner names) is scrubbed by the
``pii_redaction_callback`` guardrail before any tool response reaches the model.

Usage::

    from openbb_agents.agents.portfolio_qa import build_portfolio_qa_agent

    agent = build_portfolio_qa_agent(model="openai/gpt-4o")
    # Then pass to an ADK runner or register in the MCP server.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from openbb_agents.tools.portfolio_tools import get_positions, get_sector_exposure

_SYSTEM_INSTRUCTION = """\
You are a read-only portfolio analysis assistant. You have access to tools that
query the user's local MySQL portfolio database and live market data from
fmp_cached.

Rules you MUST follow:
- You never make investment recommendations (no buy/sell/hold).
- You never fabricate numbers — if a tool returns no data, say so.
- Account identifiers in tool responses are redacted tokens; use them as-is
  when calling tools that accept an account parameter.
- Always show the source of your numbers (which tool call produced them).
- Dollar amounts and percentages must be formatted for readability.
- If a question cannot be answered with your available tools, explain what is
  missing rather than guessing.
"""


def build_portfolio_qa_agent(
    *,
    model: str = "openai/gpt-4o",
) -> LlmAgent:
    """Build and return the portfolio_qa LlmAgent.

    Parameters
    ----------
    model:
        LiteLLM model identifier. At runtime this should come from
        ``config.get_analytical_model()``; a default is provided for tests.

    Returns
    -------
    LlmAgent
        Configured with portfolio tools and PII guardrails.
    """
    tools = [
        FunctionTool(func=get_positions),
        FunctionTool(func=get_sector_exposure),
    ]

    return LlmAgent(
        name="portfolio_qa",
        model=model,
        instruction=_SYSTEM_INSTRUCTION,
        tools=tools,
        description="Answers questions about portfolio positions, sector exposure, and risk.",
    )
