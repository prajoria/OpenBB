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
from typing import Any, Literal

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
        OutputPathEscapesJail: if the resolved path is outside the jail,
            OR if any component along the path (including the leaf) is a
            symlink pointing outside the jail (bd-9nd.8 hardening).
    """
    jail = _reports_root()
    if output_dir is None:
        candidate = jail / f"daytrade_{session_date}"
    else:
        candidate = Path(output_dir).expanduser()

    # Pre-normalize (security-review round 3 finding #2): normpath
    # collapses any `..` segments BEFORE resolve() so a lexical traversal
    # like `jail/../elsewhere` is caught here rather than depending on
    # the symlink target of resolve().
    import os as _os
    candidate = Path(_os.path.normpath(str(candidate)))

    # First: standard resolve() + relative_to(jail). Catches obvious
    # traversal (../../../etc) but silently follows symlinks — if the
    # symlink target is inside the jail this check passes even though
    # the link itself is attacker-controlled.
    resolved = candidate.resolve()
    try:
        resolved.relative_to(jail)
    except ValueError as exc:
        raise OutputPathEscapesJail(
            f"output_dir {output_dir!r} resolves to {resolved} which is "
            f"outside the reports jail {jail}. Set "
            f"FMP_TRADING_REPORTS_ROOT to widen the jail if needed."
        ) from exc

    # bd-9nd.8 hardening: also verify NO component along the path
    # (jail -> ... -> candidate) is a symlink. An attacker who can
    # write to the jail root but nowhere else could plant a symlink
    # AT one of the intermediate directory names pointing outside;
    # resolve() would follow it, produce a target inside the jail,
    # and pass the relative_to check above — but future writes into
    # that dir would land OUTSIDE the jail via the symlink dereference.
    # The lstat walk detects this at output_dir-resolution time.
    _reject_symlinks_in_chain(candidate, jail)

    return resolved


def _reject_symlinks_in_chain(candidate: Path, jail: Path) -> None:
    """Walk ``candidate``'s path components from ``jail`` down and reject
    if any is a symlink (bd-9nd.8).

    Uses ``lstat()`` (which does NOT follow symlinks) rather than
    ``resolve()`` (which does). If the candidate isn't a descendant of
    ``jail`` lexically, do nothing — the caller's ``resolve() +
    relative_to()`` already rejected it above.

    Exception discipline (security-review round 3 finding #4): the
    "component doesn't exist" case is narrowly caught as
    ``FileNotFoundError``. Any other ``OSError`` (EACCES, ELOOP, etc.)
    is a real problem — surface as :class:`OutputPathEscapesJail`
    rather than silently passing.

    Windows note: on Windows without SeCreateSymbolicLink privilege the
    symlink surface is small — this is defense-in-depth. On Linux/macOS
    where symlinks are trivially plantable it matters more.
    """
    try:
        jail_abs = jail.resolve()
        candidate_abs = candidate.absolute()
    except OSError as exc:
        # Can't even determine paths — hard refusal (round 3 #4).
        raise OutputPathEscapesJail(
            f"cannot verify jail chain for {candidate}: {exc}"
        ) from exc

    # If candidate isn't under jail lexically, skip — resolve()'s
    # relative_to check will have rejected it.
    try:
        rel = candidate_abs.relative_to(jail_abs)
    except ValueError:
        return

    # Walk each component of `rel` under jail_abs, checking is_symlink()
    # via lstat. Skip the jail root itself (operator's own choice).
    current = jail_abs
    for part in rel.parts:
        current = current / part
        try:
            if current.is_symlink():
                raise OutputPathEscapesJail(
                    f"refusing output_dir chain: {current} is a symlink "
                    f"(bd-9nd.8: symlink in path component defeats the "
                    f"jail root's relative_to check)"
                )
        except FileNotFoundError:
            # Narrow (security-review round 3 finding #4): component
            # simply doesn't exist yet — that's expected on first-write
            # to a fresh session_date directory. mkdir(parents=True) in
            # report() creates it under jail_abs.
            continue
        except OSError as exc:
            # EACCES / EPERM / ELOOP: unreadable component is a HARD
            # refusal, not a silent pass. If we can't lstat it, we
            # can't verify it's not a symlink — play safe.
            raise OutputPathEscapesJail(
                f"cannot verify {current} is not a symlink: {exc}"
            ) from exc


def _open_for_write(path: Path, overwrite: bool) -> Any:
    """Atomically open ``path`` for writing with TOCTOU-safe semantics.

    bd-9nd.8 (fix for pre-merge review of PR #448 P1 #1): the prior
    check-then-write pattern

        if path.is_symlink(): raise ...
        if path.exists() and not overwrite: raise ...
        path.write_text(...)                # <-- TOCTOU window

    was racy: an attacker with write access to the jail could plant a
    symlink between the check and the write. This function replaces
    that pattern with a single atomic ``os.open()`` call using flags
    that make the race unreachable:

    * ``O_WRONLY`` + ``O_CREAT`` — create-or-open for write
    * ``O_EXCL``  — fail if the file already exists (paired with
                    ``overwrite=False``, this replaces the exists+raise
                    check with an atomic exclusive-create)
    * ``O_NOFOLLOW`` — fail if the target is a symlink (replaces the
                    is_symlink check atomically)

    Returns an open file descriptor (int) — caller uses ``os.fdopen``
    or ``os.write`` to write and MUST close it.

    On Windows, ``O_NOFOLLOW`` isn't available in ``os.O_*``; the
    fallback is the pre-fix check-then-write pattern with a WARN note
    that the TOCTOU window exists. Not a full mitigation, but Windows
    symlink creation requires admin/dev-mode by default which limits
    the attack surface substantially.
    """
    import os
    import sys

    flags = os.O_WRONLY | os.O_CREAT
    if not overwrite:
        flags |= os.O_EXCL  # atomic "fail if exists"
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW  # atomic "fail if symlink"
    elif sys.platform == "win32":
        # Windows: no O_NOFOLLOW. Fall back to pre-fix check with the
        # inherent TOCTOU acknowledged. Symlink creation on Windows
        # requires admin/dev-mode by default, so the attack surface is
        # smaller than on Unix.
        if path.is_symlink():
            raise OutputPathEscapesJail(
                f"refusing to write through symlink at {path}"
            )

    try:
        # 0o600 = owner rw only (security-review round 3 finding #3).
        # Reports contain P&L; world-readable would leak the operator's
        # trading history to any local user on shared systems.
        fd = os.open(str(path), flags, 0o600)
    except FileExistsError as exc:
        # O_EXCL raised — the file exists and overwrite=False
        raise OutputExists(
            f"refusing to overwrite {path}: pass overwrite=True to regenerate"
        ) from exc
    except OSError as exc:
        # O_NOFOLLOW raises OSError(ELOOP or EEXIST + is_symlink) on
        # Unix when the target is a symlink. Map to OutputPathEscapesJail
        # so callers get the same exception whether they're on Linux or
        # Windows (fallback path).
        if path.is_symlink():
            raise OutputPathEscapesJail(
                f"refusing to write through symlink at {path}"
            ) from exc
        raise
    return fd


def _atomic_write_text(path: Path, content: str, overwrite: bool) -> None:
    """Thin wrapper: open via :func:`_open_for_write`, write, close.

    Encapsulates the fd lifecycle so callers don't manually manage it.
    UTF-8 encoding, matching the pre-fix ``Path.write_text`` semantics.
    """
    import os

    fd = _open_for_write(path, overwrite=overwrite)
    try:
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)


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
        # bd-9nd.8: atomic open — replaces the pre-fix
        # _open_for_write-check + path.write_text pattern that had a
        # TOCTOU window where an attacker could plant a symlink between
        # the check and the write. When overwriting, unlink first (also
        # done atomically via O_NOFOLLOW) then write fresh.
        if md_path.exists():
            logger.warning(
                "report: overwriting existing %s (idempotent regen)", md_path
            )
            if overwrite:
                md_path.unlink()
        _atomic_write_text(md_path, md_content, overwrite=overwrite)

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
            if overwrite:
                json_path.unlink()
        _atomic_write_text(json_path, json_content, overwrite=overwrite)

    if format in ("xlsx", "all"):
        try:
            from openbb_fmp_trading.reporting.xlsx_builder import (
                XLSXUnavailable,
                build_workbook,
            )
        except ImportError as exc:
            warnings.append(f"xlsx skipped: {exc}")
            logger.warning(
                "report: xlsx builder unavailable (%s); skipping xlsx", exc
            )
        else:
            xlsx_path = output_dir / "end_of_day.xlsx"
            # openpyxl doesn't accept an fd — it opens the path itself.
            # But we still want the atomic "exists + no overwrite" check
            # to be race-free, so use _open_for_write's fd, close it,
            # and let openpyxl reopen. The atomic-create semantics of
            # O_EXCL still catch the race.
            if xlsx_path.exists():
                logger.warning(
                    "report: overwriting existing %s (idempotent regen)", xlsx_path
                )
                # openpyxl doesn't support atomic exclusive-create; unlink
                # so a stale file doesn't confuse the load-modify-save loop
                xlsx_path.unlink()
            # Use _open_for_write to gate on symlink + exists atomically.
            # openpyxl will reopen and overwrite the empty file we create.
            import os as _os
            _fd = _open_for_write(xlsx_path, overwrite=True)  # already unlinked above
            _os.close(_fd)
            try:
                build_workbook(session_id, events, metrics, xlsx_path)
            except (XLSXUnavailable, ImportError, OSError) as exc:
                # Narrow catch (silent-failure review): only genuinely
                # optional or environmental failures degrade to a WARN.
                # AttributeError / KeyError / TypeError from event-shape
                # drift PROPAGATE — those are real bugs, not "xlsx is
                # optional" cases.
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

