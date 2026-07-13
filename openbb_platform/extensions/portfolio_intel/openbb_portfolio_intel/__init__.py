"""OpenBB Portfolio Intelligence extension.

Delivers portfolio-level analytics — X-Ray look-through, event calendar,
smart-money overlay, risk decomposition, what-if simulator, paper trading,
and alerts — on top of the ``fmp_cached`` provider and the existing
``portfolio_app`` service.

See ``docs/Specs/Portfolio-Intelligence-Engine-PRD.md`` for scope and
``docs/Specs/Portfolio-Intelligence-Engine-Execution-Plan.md`` for the
delivery plan. M0 ships this scaffold only; commands land in P1+.
"""

from __future__ import annotations

__version__ = "0.0.1"

# Public surface stays deliberately empty in M0. Populated as commands land
# in P1 (X-Ray, Events, Risk, Smart-Money), P2 (What-If, Attribution,
# Paper), and P3 (Alerts, Sentiment, Backtest hand-off).
__all__: list[str] = []
