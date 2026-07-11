"""PostCloseAgentTurn — the 16:15 ET one-shot review + narrator (P3.2).

Reads the day's journal, produces an :class:`EndOfDayReport` (either LLM
briefing or Jinja narrator fallback — the fallback delivers GH #84), and
writes ``last_watchlist`` / ``last_plan`` / ``last_session_summary`` to
:mod:`state_store` so tomorrow's :class:`PreOpenAgentTurn` fallback path
has real context.

Runs at 16:15 ET, AFTER the flat-by-close cascade + tick-loop teardown.
No positions should still be open when this fires; that's an invariant
Phase 2's ``session.close(flat_at_close=True)`` maintains.

Defense stack mirrors P3.1 in spirit (D4 schema parity, T3 loud
fallback, A6 provenance journaling) with a lighter surface — post-close
has no ``session_risk`` field to clamp, no ``watchlist`` to allowlist
against a tradable universe (the report is retrospective, not
prescriptive).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from openbb_fmp_trading.agent.backend import AgentBackend, ToolCall
from openbb_fmp_trading.agent.errors import AgentUnavailable
from openbb_fmp_trading.models.config import DailyConfig
from openbb_fmp_trading.models.journal_events import (
    AgentFallbackEvent,
    EndOfDayReportEvent,
)
from openbb_fmp_trading.models.plan import DailyPlan
from openbb_fmp_trading.models.report import (
    EndOfDayReport,
    SessionMetrics,
    TomorrowRecommendation,
)

logger = logging.getLogger(__name__)

#: Bumped when ``prompts/post_close_v1.txt`` changes materially (A6).
POST_CLOSE_PROMPT_VERSION: str = "post_close_v1"

#: Location of the Jinja narrator template — the GH #84 deliverable
#: when the ``[agent]`` extra is absent.
_TEMPLATES_DIR = Path(__file__).parent / "templates"
_NARRATOR_TEMPLATE = "post_close_briefing.md.j2"

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def _render_narrator(
    session_date: date,
    session_id: str,
    metrics: SessionMetrics,
    recommendations: list[TomorrowRecommendation],
) -> str:
    """Render the deterministic Jinja narrator (GH #84 fallback path).

    Loaded lazily so importing ``post_close`` doesn't require jinja2
    (which is in the ``[agent]`` extra). Tests that don't exercise the
    fallback don't pay the jinja import cost.
    """
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(_NARRATOR_TEMPLATE)
    return template.render(
        session_date=session_date.isoformat(),
        session_id=session_id,
        metrics=metrics,
        recommendations=recommendations,
    )


@dataclass
class PostCloseAgentTurn:
    """Fires once at 16:15 ET, produces an :class:`EndOfDayReport`.

    Attributes:
        config:          Operator's :class:`DailyConfig` (scope, defaults).
        backend:         Any :class:`AgentBackend`. Tests inject
                         :class:`AlwaysUnavailableBackend` to exercise
                         the narrator fallback path.
        bandwidth:       Phase 1 ``BandwidthMeter``. Same pre-charge +
                         reconcile pattern as P3.1.
        journal:         ``openbb_core_journal.JournalWriter``.
        plan:            Today's committed :class:`DailyPlan`. Written
                         to state_store on completion so tomorrow's
                         pre-open fallback can read it.
        scope:           Multi-profile key for state_store. Defaults to
                         ``"default"``.
    """

    config: DailyConfig
    backend: AgentBackend
    bandwidth: Any
    journal: Any
    plan: DailyPlan
    scope: str = "default"

    def __post_init__(self) -> None:
        self._system_prompt = _load_prompt(POST_CLOSE_PROMPT_VERSION)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(
        self,
        session_id: str,
        as_of: datetime | None = None,
    ) -> EndOfDayReport:
        """Execute the turn. Returns an :class:`EndOfDayReport` —
        never raises.

        The turn ALWAYS writes ``last_watchlist`` / ``last_plan`` /
        ``last_session_summary`` to state_store — even on fallback —
        because tomorrow's pre-open needs those regardless of whether
        today's LLM briefing succeeded.
        """
        as_of = as_of or datetime.now(timezone.utc)
        session_date = as_of.date()

        # Read the day's journal into metrics. This is deterministic
        # pre-work; the LLM (if used) only decides HOW to narrate, not
        # WHAT happened.
        metrics = self._compute_metrics_from_journal(session_id)

        tool_call: ToolCall | None = None
        source_error: Exception | None = None
        report: EndOfDayReport | None = None

        # --- Attempt LLM call ---
        try:
            self.bandwidth.charge_agent_turn_budget(estimated_tokens=12000)
            tool_call = self.backend.run_turn(
                system_prompt=self._system_prompt,
                user_prompt=self._build_user_prompt(session_id, session_date, metrics),
                tools=self._tools(),
                required_final_tool="submit_end_of_day_md",
                budget=self.bandwidth,
                temperature=0.0,
                max_iterations=8,
                max_tokens=8192,
            )
            if getattr(tool_call, "output_tokens", None) is not None:
                actual = (tool_call.input_tokens or 0) + (tool_call.output_tokens or 0)
                if hasattr(self.bandwidth, "reconcile"):
                    self.bandwidth.reconcile(estimated=12000, actual=actual)
        except AgentUnavailable as exc:
            source_error = exc
            logger.info("PostCloseAgentTurn: agent unavailable (%s); using narrator", exc)

        # --- Validate LLM output ---
        if tool_call is not None:
            try:
                raw = dict(tool_call.args)
                raw["agent_backend"] = "claude"
                raw["is_deterministic_fallback"] = False
                # Force our computed metrics rather than trusting the LLM
                # to re-derive them — the journal is the source of truth.
                raw["metrics"] = metrics.model_dump()
                report = EndOfDayReport.model_validate(raw)
            except ValidationError as exc:
                source_error = exc
                logger.warning(
                    "PostCloseAgentTurn: LLM output failed validation "
                    "(%s); falling through to narrator", exc,
                )

        # --- Fallback path (delivers #84 narrator) ---
        if report is None:
            report = self._deterministic_narrator(
                session_id, session_date, metrics, source_error
            )

        # --- Always: write state_store so tomorrow's pre-open has context ---
        self._persist_state(report, metrics)

        # --- Commit + journal ---
        self._journal_commit(report, tool_call)
        return report

    # ------------------------------------------------------------------
    # Deterministic narrator (#84 fallback)
    # ------------------------------------------------------------------

    def _deterministic_narrator(
        self,
        session_id: str,
        session_date: date,
        metrics: SessionMetrics,
        source_error: Exception | None,
    ) -> EndOfDayReport:
        """Render the Jinja template + emit the loud fallback journal entry."""
        # T5: single-session data is insufficient for structured
        # recommendations. The narrator emits zero by default.
        recommendations: list[TomorrowRecommendation] = []

        briefing_md = _render_narrator(
            session_date, session_id, metrics, recommendations
        )

        report = EndOfDayReport(
            session_date=session_date,
            session_id=session_id,
            agent_backend="none",
            is_deterministic_fallback=True,
            briefing_md=briefing_md,
            tomorrow_recommendations=recommendations,
            metrics=metrics,
        )

        # T3: loud journal entry
        self.journal.write(
            AgentFallbackEvent(
                ts=datetime.now(timezone.utc),
                session_id=session_id,
                payload={
                    "turn": "post_close",
                    "reason": "agent_unavailable_or_invalid_output",
                    "source_error": (
                        type(source_error).__name__ if source_error else "none"
                    ),
                    "fallback_source": "jinja_narrator",
                },
            )
        )
        return report

    # ------------------------------------------------------------------
    # Journal replay -> SessionMetrics
    # ------------------------------------------------------------------

    def _compute_metrics_from_journal(self, session_id: str) -> SessionMetrics:
        """Replay today's journal into aggregate metrics.

        Delegates to the shared helper in
        :mod:`openbb_fmp_trading.reporting.journal_reader` (P5.0 refactor).
        Kept as a thin method so P3.2 callers don't change; the actual
        math lives in one place now.

        Exception discipline (review S2 — narrow catch):

        * ``FileNotFoundError`` -> empty metrics (session never journaled).
        * ``ImportError`` on the reporting package -> empty metrics
          (defensive; shouldn't happen).
        * ``SchemaVersionError`` from ``JournalReader`` -> empty metrics
          with WARN log (future writer produced this — we can't parse
          safely, but empty is better than crash for the post-close path).
        * **EVERYTHING ELSE propagates.** A ``TypeError`` /
          ``AttributeError`` deep in the metrics helper is a bug —
          surfacing it beats masking it as "empty session" for the next
          6 months.
        """
        try:
            from openbb_fmp_trading.reporting.journal_reader import (
                compute_metrics_from_events,
                read_session_events,
            )
        except ImportError:
            logger.info(
                "PostCloseAgentTurn: reporting.journal_reader not importable; empty metrics"
            )
            return SessionMetrics(realized_pnl=Decimal("0"))

        try:
            events = list(read_session_events(session_id))
        except FileNotFoundError:
            return SessionMetrics(realized_pnl=Decimal("0"))
        except Exception as exc:
            # Narrow: only SchemaVersionError from openbb_core_journal is
            # legitimately catchable here (future writer version). Match
            # by class name to avoid an import cycle across extras.
            if type(exc).__name__ == "SchemaVersionError":
                logger.warning(
                    "PostCloseAgentTurn: journal has future schema (%s); empty metrics",
                    exc,
                )
                return SessionMetrics(realized_pnl=Decimal("0"))
            # NO broad `except Exception` — programming bugs propagate.
            raise
        return compute_metrics_from_events(events)

    # ------------------------------------------------------------------
    # State persistence — always fires, even on fallback
    # ------------------------------------------------------------------

    def _persist_state(
        self, report: EndOfDayReport, metrics: SessionMetrics
    ) -> None:
        """Write last_watchlist, last_plan, last_session_summary.

        Tomorrow's pre-open fallback path relies on these being present;
        we write them regardless of whether the LLM turn succeeded (T3
        principle: the operator cares about tomorrow, not today's
        review's provenance).
        """
        from openbb_fmp_trading.core import state_store

        state_store.save_last_watchlist(list(self.plan.watchlist), self.scope)
        state_store.save_last_plan(self.plan, self.scope)
        state_store.save_last_session_summary(
            {
                "date": report.session_date.isoformat(),
                "session_id": report.session_id,
                "realized_pnl": str(metrics.realized_pnl),
                "veto_counts": metrics.veto_counts_by_gate,
                "fill_count": metrics.fill_count,
                "order_count": metrics.order_count,
            },
            self.scope,
        )

    # ------------------------------------------------------------------
    # Journaling + prompt construction
    # ------------------------------------------------------------------

    def _journal_commit(
        self, report: EndOfDayReport, tool_call: ToolCall | None
    ) -> None:
        self.journal.write(
            EndOfDayReportEvent(
                ts=datetime.now(timezone.utc),
                session_id=report.session_id,
                payload={
                    "agent_backend": report.agent_backend,
                    "is_deterministic_fallback": report.is_deterministic_fallback,
                    "briefing_md_length": len(report.briefing_md),
                    # Review finding #2 fold-in (P5.0 Step 4): journal the
                    # actual briefing content so report(include_agent_narrative=
                    # True) can extract it verbatim tomorrow / next week /
                    # during a post-mortem. Without this the extractor is a
                    # permanent no-op and the include_agent_narrative flag
                    # is a dead knob.
                    "briefing_md_content": report.briefing_md,
                    "recommendation_count": len(report.tomorrow_recommendations),
                    "model_id": (
                        getattr(tool_call, "model_id", None) if tool_call else None
                    ),
                    "prompt_version": POST_CLOSE_PROMPT_VERSION,
                },
            )
        )

    def _build_user_prompt(
        self, session_id: str, session_date: date, metrics: SessionMetrics
    ) -> str:
        return (
            f"Session date: {session_date.isoformat()}\n"
            f"Session ID: {session_id}\n"
            f"Realized P&L: {metrics.realized_pnl}\n"
            f"Fills: {metrics.fill_count}, Orders: {metrics.order_count}\n"
            f"Veto counts: {metrics.veto_counts_by_gate}\n\n"
            "Produce the EndOfDayReport via submit_end_of_day_md."
        )

    def _tools(self) -> list:
        from openbb_fmp_trading.agent.tool_registry import POST_CLOSE_TOOLS

        return list(POST_CLOSE_TOOLS)


__all__ = [
    "POST_CLOSE_PROMPT_VERSION",
    "PostCloseAgentTurn",
]
