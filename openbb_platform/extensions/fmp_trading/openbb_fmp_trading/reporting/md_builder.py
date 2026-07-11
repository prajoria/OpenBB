"""Markdown builder for report() (P5.1).

Two paths, in priority order:

  1. **include_agent_narrative=True** AND briefing_md_content recoverable
     from the journal -> use it verbatim. LLM prose is richer than any
     template; operators want it verbatim in post-mortems.
  2. Otherwise -> render templates/end_of_day.md.j2 with SessionMetrics.

The template is the SAME file agent/post_close.py's fallback uses (one
source of truth per design-spec §6.3). P5.0 Step 4 widened
EndOfDayReportEvent to journal briefing_md_content so path (1) is
actually reachable — previously it was a permanent dead knob
(review finding #2).

Honest limitation: the template's session_date/session_id args default
to empty strings when this module renders standalone. In practice
report() always passes the real values via the render kwargs; the
defaults exist so a smoke-test caller with no session context doesn't
crash the render.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def build_md(
    events: list[Any],
    metrics,
    include_agent_narrative: bool = True,
    session_date: str = "",
    session_id: str = "",
) -> str:
    """Build the end-of-day.md content string.

    Args:
        events: Journal events (used to extract the LLM briefing if
            include_agent_narrative=True and the journal has one).
        metrics: SessionMetrics (used by the deterministic template
            path AND surfaced in the header of the LLM path too).
        include_agent_narrative: When True, prefer the LLM's briefing_md
            over the template. When False, always render the template.
        session_date: ISO date string for the template header.
        session_id: Session identifier for the template header.
    """
    if include_agent_narrative:
        briefing = _extract_briefing_md(events)
        if briefing is not None:
            return briefing
    return _render_narrator_template(
        metrics, session_date=session_date, session_id=session_id
    )


def _extract_briefing_md(events: list[Any]) -> str | None:
    """Return the LLM's ``briefing_md`` content if the journal has an
    ``EndOfDayReportEvent`` that carries ``payload.briefing_md_content``.

    P5.0 Step 4 widened the event schema to include this field. Legacy
    events (pre-P5.0-Step-4) only have ``briefing_md_length: int`` — we
    return None in that case so the caller falls through to the
    deterministic template.

    Review finding #2 fold-in: the extractor is no longer a permanent
    no-op; it works whenever the P5.0-augmented journal is available.
    """
    for e in events:
        if getattr(e, "event_type", None) == "end_of_day_report":
            payload = getattr(e, "payload", {}) or {}
            content = payload.get("briefing_md_content")
            if content:
                return content
    return None


def _render_narrator_template(
    metrics, session_date: str = "", session_id: str = ""
) -> str:
    """Render templates/end_of_day.md.j2 with the given SessionMetrics.

    Jinja is optional (part of the [agent] extra). If it's missing,
    return a minimal ASCII briefing so report(format='md') still ships
    something the operator can inspect. Falling loud on missing jinja
    would defeat the "graceful degradation" contract in the design spec.
    """
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except ImportError:
        logger.warning(
            "md_builder: jinja2 unavailable; using ASCII fallback briefing"
        )
        return _ascii_fallback(metrics, session_date, session_id)

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("end_of_day.md.j2")
    return template.render(
        session_date=session_date,
        session_id=session_id,
        metrics=metrics,
        recommendations=[],
    )


def _ascii_fallback(metrics, session_date: str, session_id: str) -> str:
    """Ultra-minimal briefing when jinja2 is absent."""
    lines = [
        f"# Session Briefing — {session_date}",
        "",
        f"**Session ID:** `{session_id}`",
        f"**Realized P&L:** {metrics.realized_pnl}",
        f"**P&L source:** {getattr(metrics, 'pnl_source', 'unknown')}",
        f"**Fills:** {metrics.fill_count} across {metrics.order_count} orders",
        f"**Total commissions:** {getattr(metrics, 'total_commissions', 0)}",
        f"**Total slippage:** {getattr(metrics, 'total_slippage', 0)}",
        "",
        "## Risk gates that fired today",
        "",
    ]
    if metrics.veto_counts_by_gate:
        for gate, count in sorted(metrics.veto_counts_by_gate.items()):
            lines.append(f"- **{gate}** — {count} veto(s)")
    else:
        lines.append("- No RiskManager vetoes today.")
    lines.append("")
    lines.append(
        "_This is an ASCII fallback briefing (jinja2 not installed). "
        "Install `openbb-fmp-trading[agent]` for the full narrator._"
    )
    return "\n".join(lines) + "\n"


__all__ = ["build_md"]
