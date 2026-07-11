"""report() orchestrator (P5.1) — writes MD + JSON + XLSX per format arg.

See design-spec §4.5 for the full flow. This module is deliberately
thin: it delegates to the format-specific builders and returns a
:class:`ReportManifest` describing what was written.

Security posture (security-review round 1 fold-in):

* ``output_dir`` is JAILED under a configurable reports root
  (``REPORTS_ROOT`` default = ``Analysis/exports/``). Any path outside
  the jail is rejected with :class:`OutputPathEscapesJail`. Operators
  can override the jail via the ``FMP_TRADING_REPORTS_ROOT`` env var
  for tests / CI.
* Overwrites require **explicit** ``overwrite=True``. Default is
  ``overwrite=False`` — refuses to clobber existing files with
  :class:`OutputExists`. This closes the "attacker with local FS access
  overwrites yesterday's report" risk class.
* Files are written with exclusive-create semantics when overwrite
  is False (openpyxl/xlsx handled via unlink-then-write when
  overwrite is True — atomicity trade-off).

Idempotency: with ``overwrite=True`` repeat calls overwrite existing
files. Each overwrite emits a WARN log (review S5). Operators
regenerating reports after template fixes pass ``overwrite=True``
explicitly — that's a feature, not a bug.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from openbb_fmp_trading.models.results import ReportManifest

logger = logging.getLogger(__name__)


class OutputPathEscapesJail(ValueError):
    """Raised when ``output_dir`` resolves outside the reports jail."""


class OutputExists(FileExistsError):
    """Raised when an output file exists and ``overwrite=False`` (default)."""


def _reports_root() -> Path:
    """Return the jail root for report output.

    Precedence:
      1. FMP_TRADING_REPORTS_ROOT env var (absolute or relative to cwd)
      2. Analysis/exports/ (default)

    Resolved to an absolute path so the ``is_relative_to`` check works
    consistently across platforms.
    """
    env = os.environ.get("FMP_TRADING_REPORTS_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.cwd() / "Analysis" / "exports").resolve()


def _resolve_output_dir(output_dir: Path | None, session_date: date) -> Path:
    """Resolve + jail-check ``output_dir``.

    Args:
        output_dir: User-supplied path or None. None means "use the
            per-session default under the jail root".
        session_date: Used to construct the default subdirectory name.

    Returns:
        The resolved absolute path guaranteed to be inside the reports jail.

    Raises:
        OutputPathEscapesJail: if the resolved path is outside the jail.
    """
    jail = _reports_root()
    if output_dir is None:
        candidate = jail / f"daytrade_{session_date}"
    else:
        candidate = Path(output_dir).expanduser()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(jail)
    except ValueError as exc:
        raise OutputPathEscapesJail(
            f"output_dir {output_dir!r} resolves to {resolved} which is "
            f"outside the reports jail {jail}. Set "
            f"FMP_TRADING_REPORTS_ROOT to widen the jail if needed."
        ) from exc
    return resolved


def _open_for_write(path: Path, overwrite: bool) -> None:
    """Refuse the write if the file exists and overwrite=False.

    Also refuses to follow symlinks — an attacker who plants a symlink
    in the jail dir could otherwise redirect the write to /etc/passwd
    (with jail-root permissions).
    """
    if path.is_symlink():
        raise OutputPathEscapesJail(
            f"refusing to write through symlink at {path}"
        )
    if path.exists() and not overwrite:
        raise OutputExists(
            f"refusing to overwrite {path}: pass overwrite=True to regenerate"
        )


def report(
    session_id: str,
    format: Literal["md", "xlsx", "json", "all"] = "all",
    output_dir: Path | None = None,
    include_agent_narrative: bool = True,
    overwrite: bool = False,
) -> ReportManifest:
    """Render session artifacts. See design-spec §4.5.

    Args:
        session_id: The session to render.
        format: Which format(s) to emit.
        output_dir: Target directory. Defaults to
            ``<reports_root>/daytrade_<date>/``. Must resolve inside the
            reports jail (see :func:`_reports_root`).
        include_agent_narrative: When True and the journal has an
            EndOfDayReportEvent with briefing_md_content, use that
            verbatim for the MD path.
        overwrite: When False (default), refuse to clobber existing
            files. Pass True to regenerate — will emit a WARN per file.

    Raises:
        OutputPathEscapesJail: if ``output_dir`` is outside the jail.
        OutputExists: if a target file exists and overwrite=False.
        ValueError: if session_date can't be determined (S3 raise-on-fail).
    """
    from openbb_fmp_trading.reporting import journal_reader
    from openbb_fmp_trading.reporting.json_builder import build_json_manifest
    from openbb_fmp_trading.reporting.md_builder import build_md

    events = list(journal_reader.read_session_events(session_id))
    metrics = journal_reader.compute_metrics_from_events(events)

    session_date = _parse_session_date(session_id, events)
    output_dir = _resolve_output_dir(output_dir, session_date)
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
        _open_for_write(md_path, overwrite)
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
        _open_for_write(json_path, overwrite)
        if json_path.exists():
            logger.warning(
                "report: overwriting existing %s (idempotent regen)", json_path
            )
        json_path.write_text(json_content, encoding="utf-8")

    if format in ("xlsx", "all"):
        try:
            from openbb_fmp_trading.reporting.xlsx_builder import build_workbook
        except ImportError as exc:
            warnings.append(f"xlsx skipped: {exc}")
            logger.warning(
                "report: xlsx builder unavailable (%s); skipping xlsx", exc
            )
        else:
            xlsx_path = output_dir / "end_of_day.xlsx"
            _open_for_write(xlsx_path, overwrite)
            if xlsx_path.exists():
                logger.warning(
                    "report: overwriting existing %s (idempotent regen)", xlsx_path
                )
                # openpyxl doesn't support atomic exclusive-create; unlink
                # so a stale file doesn't confuse the load-modify-save loop
                xlsx_path.unlink()
            try:
                build_workbook(session_id, events, metrics, xlsx_path)
            except Exception as exc:  # noqa: BLE001 — xlsx is optional
                warnings.append(f"xlsx failed: {exc}")
                logger.warning("report: xlsx build failed (%s); skipping", exc)
                xlsx_path = None

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

    Review S3 fix: on parse failure, RAISE ValueError. Silent fallback
    to today() mis-dates the report + output dir.
    """
    for e in events:
        if getattr(e, "event_type", None) == "session_start":
            ts = getattr(e, "ts", None)
            if ts is not None and hasattr(ts, "date"):
                return ts.date()
    # No session_start event — try parsing session_id.
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
    """True iff the journal has an EndOfDayReportEvent with briefing_md_content."""
    for e in events:
        if getattr(e, "event_type", None) == "end_of_day_report":
            payload = getattr(e, "payload", {}) or {}
            if payload.get("briefing_md_content"):
                return True
    return False


__all__ = ["OutputExists", "OutputPathEscapesJail", "report"]

