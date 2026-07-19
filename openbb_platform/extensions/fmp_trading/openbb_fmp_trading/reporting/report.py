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

    # NOTE (security-review round 4 revert of round 3 finding #2):
    # We deliberately do NOT pre-normalize the candidate with
    # os.path.normpath here. normpath collapses `link/..` LEXICALLY
    # WITHOUT following the link, which would MASK a planted symlink:
    # consider `jail/link/../elsewhere` where `link -> /etc`. With
    # pre-normpath, the path becomes `jail/elsewhere` (which passes the
    # jail check); without it, resolve() FOLLOWS `link` -> `/etc`,
    # then `..` -> `/`, then `/elsewhere` — which FAILS the
    # relative_to(jail) check as it should.
    #
    # resolve() correctly handles the interaction of `..` and symlinks
    # per POSIX semantics ("evaluated left-to-right after link
    # dereference"). The pre-normpath was well-intentioned but wrong.

    # Standard resolve() + relative_to(jail). resolve() interprets `..`
    # AFTER symlink dereference, so `jail/link/../x` with `link -> /etc`
    # correctly resolves to `/x` and fails the relative_to check.
    resolved = candidate.resolve()
    try:
        resolved.relative_to(jail)
    except ValueError as exc:
        raise OutputPathEscapesJail(
            f"output_dir {output_dir!r} resolves to {resolved} which is "
            f"outside the reports jail {jail}. Set "
            f"FMP_TRADING_REPORTS_ROOT to widen the jail if needed."
        ) from exc

    # bd-9nd.8 hardening: also verify NO component along the ORIGINAL
    # user-supplied path (jail -> ... -> candidate) is a symlink.
    # We pass the ORIGINAL candidate (pre-normalization) so any
    # symlink hidden behind `..` in the input is still visible to the
    # lstat walk — walking a normalized form would miss it. This is
    # defense-in-depth: even if resolve()+relative_to didn't reject
    # (unusual but possible edge cases), a symlink in the write path
    # is still caught.
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


def _refuse_symlink_at_target(path: Path) -> None:
    """Refuse writes where ``path`` itself is a symlink.

    Complements :func:`_reject_symlinks_in_chain` (which walks the
    parent directory chain) and :func:`_open_for_write`'s
    ``O_NOFOLLOW`` (which catches symlinks at open time).

    This exists because the writer's overwrite path in :func:`report`
    unconditionally ``unlink()``s an existing ``path`` before calling
    ``_atomic_write_text``. ``Path.unlink()`` removes the symlink
    itself (not the target), which clears the way for a fresh write
    that never triggers ``O_NOFOLLOW`` — the attacker's symlink is
    silently destroyed and replaced by our regular file. Net effect:
    the attacker doesn't get to hijack our write, but the
    ``OutputPathEscapesJail`` we contract to raise is never raised,
    and downstream security-hardening tests report DID NOT RAISE.

    Fix: call this BEFORE any unlink, so the symlink-at-target case
    raises with the specific exception the tests + spec require. #896.

    Uses :meth:`Path.is_symlink` (which does NOT follow the link) —
    the correct check for "is the final path component itself a link".
    Returns None on success; raises :class:`OutputPathEscapesJail` on
    detected symlink.
    """
    try:
        if path.is_symlink():
            raise OutputPathEscapesJail(
                f"refusing to write through symlink at {path}"
            )
    except OSError as exc:
        # Path.is_symlink can raise on unusual filesystems / permission
        # issues. Play safe: treat "can't determine" as "refuse".
        raise OutputPathEscapesJail(
            f"cannot verify {path} is not a symlink: {exc}"
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
    # bd-9nd.8 review round 5 P1: re-verify the chain AFTER mkdir. Between
    # _resolve_output_dir's chain-walk and this mkdir(parents=True) call,
    # an attacker with jail write access could plant a symlink in an
    # intermediate directory that mkdir would then follow. Re-walking
    # here catches any symlink that landed during the window OR that
    # mkdir(parents=True) itself traversed. If we find one, the caller
    # gets the same OutputPathEscapesJail as if the initial check had
    # caught it — no silent write-through.
    _reject_symlinks_in_chain(output_dir, _reports_root())

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
        #
        # #896: BEFORE the unlink, refuse if the target is a symlink.
        # Path.exists() follows symlinks (returns True for a symlink
        # pointing to an existing file), and Path.unlink() removes the
        # symlink itself — so a naive `if exists: unlink()` step
        # destroys the attacker's symlink and clears the path for our
        # fresh write, defeating _open_for_write's O_NOFOLLOW check
        # (which never sees a symlink to reject).
        _refuse_symlink_at_target(md_path)
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
        # #896: refuse symlink at target BEFORE the unlink step (which
        # would destroy the attacker-planted symlink and clear the
        # path for our fresh write, defeating O_NOFOLLOW).
        _refuse_symlink_at_target(json_path)
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
            # bd-9nd.8 review round 5 P0 (folds in bd-9nd.13): openpyxl
            # doesn't accept an fd, so the old pattern was
            #   unlink(xlsx_path); _open_for_write(xlsx_path); close(fd);
            #   build_workbook(xlsx_path)  # <-- reopens by name
            # The close→reopen window let an attacker plant a symlink at
            # xlsx_path pointing outside the jail; openpyxl (no O_NOFOLLOW)
            # would happily write through it. Additionally, when
            # overwrite=True we forced _open_for_write to drop O_EXCL, so
            # the "exclusive create" guarantee named in the prior comment
            # was FALSE.
            #
            # Fix: write to a mkstemp() temp file in the SAME directory
            # (same-fs so os.replace is atomic on POSIX), then atomically
            # rename over xlsx_path. This inherits mkstemp's O_EXCL|O_CREAT
            # atomicity for the temp file itself, and os.replace() is
            # atomic on POSIX (best-effort on Windows). The pre-check
            # for exists + WARN is preserved as an operator-signal.
            # #896: refuse symlink at target BEFORE the exists() +
            # overwrite branches (same rationale as md_path and
            # json_path — the mkstemp+rename below would otherwise
            # succeed and destroy the symlink instead of raising).
            _refuse_symlink_at_target(xlsx_path)
            if xlsx_path.exists():
                if not overwrite:
                    raise OutputExists(
                        f"refusing to overwrite {xlsx_path}: "
                        f"pass overwrite=True to regenerate"
                    )
                logger.warning(
                    "report: overwriting existing %s (idempotent regen)", xlsx_path
                )
            elif xlsx_path.is_symlink():
                # Broken/dangling symlink at target — refuse. `exists()`
                # returns False for a symlink to a nonexistent target,
                # so we need the explicit lstat-based check.
                # (Kept as belt-and-suspenders: _refuse_symlink_at_target
                # above also catches this; this arm is now dead code but
                # left as a defense-in-depth marker.)
                raise OutputPathEscapesJail(
                    f"refusing to write through symlink at {xlsx_path}"
                )

            import os as _os
            import tempfile

            # mkstemp gives us: (a) an atomic O_EXCL|O_CREAT open with
            # a random name (unguessable by racing attacker), (b) an fd
            # we immediately close (openpyxl reopens by name — but the
            # random name isn't guessable in the sub-ms window), (c) a
            # path in the SAME directory as xlsx_path so os.replace is
            # atomic on the same filesystem.
            tmp_fd, tmp_path_str = tempfile.mkstemp(
                prefix=".end_of_day.xlsx.",
                suffix=".tmp",
                dir=str(output_dir),
            )
            tmp_path = Path(tmp_path_str)
            try:
                _os.close(tmp_fd)
                # Verify the temp file itself isn't a symlink (mkstemp
                # produces a real file; this catches an impossibly-rare
                # race where the tmpfile got replaced under us).
                if tmp_path.is_symlink():
                    raise OutputPathEscapesJail(
                        f"tempfile at {tmp_path} became a symlink — abort"
                    )
                try:
                    build_workbook(session_id, events, metrics, tmp_path)
                except (XLSXUnavailable, ImportError, OSError) as exc:
                    # Narrow catch (silent-failure review): only genuinely
                    # optional or environmental failures degrade to a WARN.
                    # AttributeError / KeyError / TypeError from event-shape
                    # drift PROPAGATE — those are real bugs, not "xlsx is
                    # optional" cases.
                    warnings.append(f"xlsx failed: {exc}")
                    logger.warning("report: xlsx build failed (%s); skipping", exc)
                    xlsx_path = None
                else:
                    # Atomic rename into place. On POSIX this is a single
                    # syscall (rename(2)) — no window where xlsx_path is
                    # missing or partial. On Windows, os.replace atomically
                    # replaces an existing file (unlike os.rename which
                    # would fail).
                    _os.replace(str(tmp_path), str(xlsx_path))
                    # Tighten permissions after rename (mkstemp default is 0o600
                    # on POSIX; os.replace preserves this, but be explicit).
                    try:
                        _os.chmod(str(xlsx_path), 0o600)
                    except OSError:
                        # Windows: chmod has limited effect; not fatal.
                        pass
            finally:
                # Clean up temp file if build failed OR replace didn't run.
                # tmp_path.exists() is False after a successful os.replace,
                # so this only removes on error paths.
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        logger.warning(
                            "report: could not remove xlsx tempfile %s", tmp_path
                        )

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

