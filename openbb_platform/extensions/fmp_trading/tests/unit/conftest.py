"""Shared unit-test helpers for fmp_trading.

Under ``--import-mode=importlib`` (enabled repo-wide in ``pytest.ini``
to avoid basename collisions across extensions — see #739), test files
cannot reliably do ``from .sibling import helper`` or
``from tests.unit.sibling import helper`` — importlib mode makes each
test file its own top-level module. ``conftest.py`` is the one
mechanism pytest still auto-injects into sibling test files regardless
of import mode, so cross-test helpers belong here. #860.
"""

from __future__ import annotations


def _tool_call_with_risk(risk_updates: dict, watchlist=("MSFT",)):
    """Build a submit_daily_plan tool-call arg dict with LLM-emitted
    session_risk overrides.

    Historically lived in ``test_risk_clamp.py``; consumed by both
    ``test_risk_clamp`` and ``test_prompt_injection``. Hoisted here so
    the cross-file import survives ``--import-mode=importlib``.
    """
    # Local imports so bare collection of this conftest doesn't drag the
    # whole fmp_trading agent stack into every pytest session start.
    from openbb_fmp_trading.agent.backend import ToolCall
    from openbb_fmp_trading.models.config import RiskConfig

    base_risk = RiskConfig().model_dump()
    base_risk.update(risk_updates)
    return ToolCall(
        name="submit_daily_plan",
        args={
            "as_of": "2026-07-13T13:30:00+00:00",
            "date": "2026-07-13",
            "watchlist": list(watchlist),
            "preset": "intraday_momentum",
            "alerts": [],
            "session_risk": base_risk,
            "thesis": "t",
            "agent_backend": "claude",
        },
        model_id="claude-sonnet-4-5",
    )
