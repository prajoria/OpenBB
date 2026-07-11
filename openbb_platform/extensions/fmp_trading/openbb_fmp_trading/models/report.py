"""EndOfDayReport + subtypes (PRD §6.2.6, Phase 3 P3.2).

Produced by PostCloseAgentTurn — either from an LLM turn or from the
deterministic Jinja narrator fallback (delivers GH #84). The tick loop
never consumes this; it's read by the operator (CLI / MD report) and by
tomorrow's pre-open turn for prior-session context.

T5 (P1) guardrail: every :class:`TomorrowRecommendation` defaults to
``low_signal=True``. One session of P&L is mostly noise — recommendations
built from it are recency-biased by construction. The flag warns
downstream consumers not to over-weight day-one advice. A future
follow-up bead will require N-session aggregation before flipping
``low_signal=False``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from openbb_core.provider.abstract.data import Data
from pydantic import Field


class TomorrowRecommendation(Data):
    """One structured next-day suggestion from the post-close review.

    T5 default of ``low_signal=True`` acknowledges that a single
    session's outcomes are noisy. Consumers should treat these as
    directional hints, not commitments — especially any recommendation
    of ``kind == "risk"`` or ``kind == "preset"`` which materially
    affects tomorrow's trading.
    """

    kind: Literal["watchlist", "preset", "risk", "process"] = Field(
        description="Category of the suggestion."
    )
    detail: str = Field(description="One-sentence recommendation body.")
    low_signal: bool = Field(
        default=True,
        description=(
            "T5: recency-safe default. Set to False only when supported "
            "by N-session history — see the design spec T5 follow-up."
        ),
    )


class SessionMetrics(Data):
    """Aggregate metrics for one session. Derived from journal replay."""

    realized_pnl: Decimal = Field(description="Total realized P&L in dollars.")
    win_rate_today: float | None = Field(
        default=None,
        description=(
            "Fraction of closed round-trips that were winners. None if "
            "no round-trips completed."
        ),
    )
    veto_counts_by_gate: dict[str, int] = Field(
        default_factory=dict,
        description="Per-gate (G1..G8) count of RiskManager vetoes today.",
    )
    fill_count: int = Field(
        default=0, description="Total fill events in the journal."
    )
    order_count: int = Field(
        default=0, description="Total order events in the journal."
    )


class EndOfDayReport(Data):
    """The post-close turn's committed deliverable.

    Two production paths produce this object with an IDENTICAL schema
    (D4 full-parity fallback):

      1. LLM turn — richer prose in ``briefing_md``, plus more nuanced
         ``tomorrow_recommendations``.
      2. Deterministic Jinja narrator (fulfills #84) — mechanical
         summary of today's metrics.

    Only ``agent_backend`` + ``is_deterministic_fallback`` distinguish
    them at the schema level.
    """

    session_date: date = Field(description="The trading date this report covers.")
    session_id: str = Field(description="IntradaySession identifier.")
    agent_backend: Literal["claude", "openai", "none"] = Field(
        description="Provenance — 'none' means the deterministic narrator ran."
    )
    is_deterministic_fallback: bool = Field(
        default=False,
        description=(
            "True when the deterministic Jinja narrator produced the "
            "briefing (LLM unavailable, tool-call malformed, or air-"
            "gapped operator mode)."
        ),
    )
    briefing_md: str = Field(
        description=(
            "Human-readable Markdown briefing — the #84 payload. "
            "Consumed by the CLI post-close subcommand and the P5 "
            "report() command."
        )
    )
    tomorrow_recommendations: list[TomorrowRecommendation] = Field(
        default_factory=list,
        description=(
            "Structured next-day suggestions. Every entry defaults to "
            "low_signal=True per T5."
        ),
    )
    metrics: SessionMetrics = Field(description="Aggregate session metrics.")


__all__ = [
    "EndOfDayReport",
    "SessionMetrics",
    "TomorrowRecommendation",
]
