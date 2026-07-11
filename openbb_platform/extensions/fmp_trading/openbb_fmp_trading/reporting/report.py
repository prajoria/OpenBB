"""report() orchestrator (P5.1) — writes MD + JSON + XLSX per format arg.

See design-spec §4.5 for the full flow. This module is deliberately
thin: it delegates to the format-specific builders and returns a
:class:`ReportManifest` describing what was written.

Idempotency: repeat calls to the same ``output_dir`` overwrite existing
files. Each overwrite emits a WARN log (review S5). Operators regenerate
reports after template fixes — that's a feature, not a bug.

XLSX handling: format="xlsx" and format="all" attempt the XLSX builder,
but if the extra (openbb-techtrade) is missing, the xlsx is skipped
with a warning appended to ``ReportManifest.warnings`` — MD + JSON
still ship (graceful degradation per design §6.1).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from openbb_fmp_trading.models.results import ReportManifest

logger = logging.getLogger(__name__)


def report(
    session_id: str,
    format: Literal["md", "xlsx", "json", "all"] = "all",
    output_dir: Path | None = None,
    include_agent_narrative: bool = True,
) -> ReportManifest:
    """Render session artifacts. See design-spec §4.5.

    Args:
        session_id: The session to render.
        format: Which format(s) to emit.
        output_dir: Target directory. Defaults to
            ``Analysis/exports/daytrade_<date>/``.
        include_agent_narrative: When True and the journal has an
            EndOfDayReportEvent with briefing_md_content, use that
            verbatim for the MD path. Otherwise render the deterministic
            template.
    """
    from openbb_fmp_trading.reporting import journal_reader
    from openbb_fmp_trading.reporting.json_builder import build_json_manifest
    from openbb_fmp_trading.reporting.md_builder import build_md

    events = list(journal_reader.read_session_events(session_id))
    metrics = journal_reader.compute_metrics_from_events(events)

    # Default output_dir: Analysis/exports/daytrade_<date>/
    session_date = _parse_session_date(session_id, events)
    if output_dir is None:
        output_dir = Path("Analysis") / "exports" / f"daytrade_{session_date}"
    output_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    md_path: Path | None = None
    xlsx_path: Path | None = None
    json_path: Path | None = None
    agent_backend = _extract_agent_backend(events)

    if format in ("md", "all"):
        md_content = build_md(
            events,
            metrics,
            include_agent_narrative=include_agent_narrative,
            session_date=session_date.isoformat(),
            session_id=session_id,
        )
        md_path = output_dir / "end_of_day.md"
        if md_path.exists():
            logger.warning(
                "report: overwriting existing %s (idempotent regen)", md_path
            )
        md_path.write_text(md_content, encoding="utf-8")

    if format in ("json", "all"):
        json_content = build_json_manifest(
            events=events,
            metrics=metrics,
            plan=None,
            report=None,
            session_id=session_id,
        )
        json_path = output_dir / "manifest.json"
        if json_path.exists():
            logger.warning(
                "report: overwriting existing %s (idempotent regen)", json_path
            )
        json_path.write_text(json_content, encoding="utf-8")

    if format in ("xlsx", "all"):
        # P5.2 wires the full builder. P5.1 handles the missing-extra path
        # gracefully — MD + JSON still ship + xlsx is skipped with a
        # warning appended to the manifest.
        try:
            from openbb_fmp_trading.reporting.xlsx_builder import build_workbook
        except ImportError as exc:
            warnings.append(f"xlsx skipped: {exc}")
            logger.warning(
                "report: xlsx builder unavailable (%s); skipping xlsx", exc
            )
        else:
            xlsx_path = output_dir / "end_of_day.xlsx"
            if xlsx_path.exists():
                logger.warning(
                    "report: overwriting existing %s (idempotent regen)", xlsx_path
                )
            try:
                build_workbook(session_id, events, metrics, xlsx_path)
            except Exception as exc:  # noqa: BLE001 — xlsx is optional
                warnings.append(f"xlsx failed: {exc}")
                logger.warning("report: xlsx build failed (%s); skipping", exc)
                xlsx_path = None  # File may have been half-written; don't lie in manifest

    return ReportManifest(
        session_id=session_id,
        session_date=session_date,
        md_path=md_path,
        xlsx_path=xlsx_path,
        json_path=json_path,
        included_agent_narrative=(
            include_agent_narrative
            and md_path is not None
            and _has_briefing_content(events)
        ),
        session_events_count=len(events),
        agent_backend=agent_backend,
        warnings=warnings,
    )


def _parse_session_date(session_id: str, events: list) -> date:
    """Extract session_date from session_start event OR parse from session_id.

    Preferred: read the session_start event's ts.date() — that's the
    authoritative source. Fallback: parse ``s%Y%m%d%H%M%S``.

    Review S3 fix: on parse failure, RAISE ValueError. Silent fallback
    to today() mis-dates the report + output dir (an operator would
    regenerate a report for 2026-07-06 and write it to
    Analysis/exports/daytrade_<today>/ — the exact class of confusion
    that leads to trading the wrong day's data).
    """
    for e in events:
        if getattr(e, "event_type", None) == "session_start":
            ts = getattr(e, "ts", None)
            if ts is not None and hasattr(ts, "date"):
                return ts.date()
    # No session_start event — try parsing session_id.
    # Format: `s%Y%m%d%H%M%S` (14 digits after leading 's').
    if (
        session_id.startswith("s")
        and len(session_id) >= 9
        and session_id[1:9].isdigit()
    ):
        try:
            return date(
                int(session_id[1:5]),
                int(session_id[5:7]),
                int(session_id[7:9]),
            )
        except ValueError:
            pass  # fall through to raise
    raise ValueError(
        f"Cannot determine session_date: no session_start event and "
        f"session_id {session_id!r} doesn't match s%Y%m%d%H%M%S format. "
        "Silent fallback to today() would mis-date the report — refusing."
    )


def _extract_agent_backend(events: list) -> str | None:
    """Read agent_backend from EndOfDayReportEvent if present."""
    for e in events:
        if getattr(e, "event_type", None) == "end_of_day_report":
            payload = getattr(e, "payload", {}) or {}
            return payload.get("agent_backend")
    return None


def _has_briefing_content(events: list) -> bool:
    """True iff the journal has an EndOfDayReportEvent with briefing_md_content
    (post-P5.0-Step-4 events; legacy events return False here)."""
    for e in events:
        if getattr(e, "event_type", None) == "end_of_day_report":
            payload = getattr(e, "payload", {}) or {}
            if payload.get("briefing_md_content"):
                return True
    return False


__all__ = ["report"]
