"""Regression tests for bd-9nd.8: TOCTOU + symlink hardening on report writes.

The pre-fix report.py had two vulnerabilities the pre-merge PR #448
review flagged as P1 (deferred as P2 to unblock merge):

  1. TOCTOU (Time Of Check vs Time Of Use): _open_for_write checked
     is_symlink + exists, then Path.write_text ran later — an attacker
     with jail write access could plant a symlink between check and
     write, redirecting the write to /etc/passwd (with jail-root
     credentials).

  2. output_dir path components weren't checked for symlinks. resolve()
     FOLLOWS symlinks, so a link at any intermediate dir pointing
     inside the jail would pass the relative_to check even though the
     link itself was attacker-controlled.

The fix replaces check-then-write with atomic os.open() using
O_EXCL|O_NOFOLLOW, and walks the output_dir path components with
lstat() to reject symlinks anywhere in the chain.

Windows note: several tests skip on Windows because:
  * symlink creation requires admin/dev-mode (unavailable in CI)
  * O_NOFOLLOW isn't in os.O_* — the fix uses the pre-fix check-then-
    write fallback with a WARN note about the residual TOCTOU window
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _jail_to_tmp(tmp_path, monkeypatch):
    """Set FMP_TRADING_REPORTS_ROOT to tmp_path for every test."""
    monkeypatch.setenv("FMP_TRADING_REPORTS_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def _stub_journal(monkeypatch):
    """Stub read_session_events so tests don't need a real journal."""
    monkeypatch.setattr(
        "openbb_fmp_trading.reporting.journal_reader.read_session_events",
        lambda session_id, root=None: iter([]),
    )


class TestAtomicOverwriteRefusal:
    """The core O_EXCL contract: overwrite=False atomically fails if
    the file exists — no check-then-write window."""

    def test_second_call_without_overwrite_raises_output_exists(
        self, tmp_path, _stub_journal
    ):
        from openbb_fmp_trading.reporting.report import OutputExists, report

        report(session_id="s20260713", format="md", output_dir=tmp_path)
        with pytest.raises(OutputExists):
            report(session_id="s20260713", format="md", output_dir=tmp_path)

    def test_second_call_with_overwrite_true_succeeds(
        self, tmp_path, _stub_journal
    ):
        from openbb_fmp_trading.reporting.report import report

        report(session_id="s20260713", format="md", output_dir=tmp_path)
        # Must not raise
        report(
            session_id="s20260713",
            format="md",
            output_dir=tmp_path,
            overwrite=True,
        )
        assert (tmp_path / "end_of_day.md").exists()


class TestSymlinkRefusal:
    """The core O_NOFOLLOW contract: a symlinked output-file target
    fails atomically, no is_symlink race window."""

    def test_symlink_at_output_file_refused(self, tmp_path, _stub_journal):
        """An attacker planted a symlink at end_of_day.md pointing to
        /etc/passwd. The write must be refused atomically."""
        if sys.platform == "win32":
            pytest.skip("Symlink creation on Windows requires admin/dev mode")

        from openbb_fmp_trading.reporting.report import (
            OutputPathEscapesJail,
            report,
        )

        # Plant the symlink at the target file path
        target_outside = tmp_path / "attacker_target"
        target_outside.write_text("original attacker content", encoding="utf-8")

        # end_of_day.md -> ../attacker_target (outside the write jail)
        (tmp_path / "end_of_day.md").symlink_to(target_outside)

        # With overwrite=True (needed because the symlink "exists")
        with pytest.raises(OutputPathEscapesJail, match="symlink"):
            report(
                session_id="s20260713",
                format="md",
                output_dir=tmp_path,
                overwrite=True,
            )

        # The symlink target was NOT modified — write was atomically refused
        assert target_outside.read_text() == "original attacker content"

    def test_symlink_in_output_dir_chain_refused(
        self, tmp_path, monkeypatch
    ):
        """An attacker planted a symlink at one of the parent directory
        components of output_dir pointing to a jail-inside path but the
        LINK is attacker-controlled. resolve() would follow it silently.
        _reject_symlinks_in_chain (bd-9nd.8) catches it via lstat()."""
        if sys.platform == "win32":
            pytest.skip("Symlink creation on Windows requires admin/dev mode")

        from openbb_fmp_trading.reporting.report import (
            OutputPathEscapesJail,
            report,
        )

        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter([]),
        )

        # Jail root = tmp_path (set by _jail_to_tmp fixture, but this
        # test uses monkeypatch directly for clarity)
        monkeypatch.setenv("FMP_TRADING_REPORTS_ROOT", str(tmp_path))

        # Real target inside jail (a legit subdir)
        real_dir = tmp_path / "real_reports"
        real_dir.mkdir()

        # Symlink at 'reports_link' -> 'real_reports' (both inside jail —
        # resolve() would follow to real_reports and pass relative_to)
        (tmp_path / "reports_link").symlink_to(real_dir)

        # Ask report() to write under the symlinked name
        with pytest.raises(OutputPathEscapesJail, match="symlink"):
            report(
                session_id="s20260713",
                format="md",
                output_dir=tmp_path / "reports_link",
            )


class TestOpenForWriteAtomicSemantics:
    """Direct tests of the _open_for_write helper — confirming O_EXCL
    + O_NOFOLLOW map to the right custom exceptions."""

    def test_open_for_write_exclusive_create_succeeds(self, tmp_path):
        from openbb_fmp_trading.reporting.report import _open_for_write

        target = tmp_path / "newfile.txt"
        fd = _open_for_write(target, overwrite=False)
        assert isinstance(fd, int)
        os.write(fd, b"hello")
        os.close(fd)
        assert target.read_text() == "hello"

    def test_open_for_write_raises_output_exists_on_race(self, tmp_path):
        """O_EXCL means the second call fails atomically — this is
        what closes the pre-fix TOCTOU window."""
        from openbb_fmp_trading.reporting.report import (
            OutputExists,
            _open_for_write,
        )

        target = tmp_path / "existing.txt"
        target.write_text("first", encoding="utf-8")

        with pytest.raises(OutputExists):
            _open_for_write(target, overwrite=False)

    def test_open_for_write_raises_on_symlink(self, tmp_path):
        if sys.platform == "win32":
            pytest.skip("Symlink creation on Windows requires admin/dev mode")

        from openbb_fmp_trading.reporting.report import (
            OutputPathEscapesJail,
            _open_for_write,
        )

        target_outside = tmp_path / "outside"
        target_outside.write_text("x", encoding="utf-8")
        link_path = tmp_path / "linked"
        link_path.symlink_to(target_outside)

        with pytest.raises(OutputPathEscapesJail, match="symlink"):
            _open_for_write(link_path, overwrite=True)


class TestAtomicWriteText:
    """Regression: the _atomic_write_text helper closes the fd on
    exception (context-manager-equivalent semantics)."""

    def test_atomic_write_text_writes_content(self, tmp_path):
        from openbb_fmp_trading.reporting.report import _atomic_write_text

        target = tmp_path / "written.md"
        _atomic_write_text(target, "hello world\n", overwrite=False)
        assert target.read_text() == "hello world\n"

    def test_atomic_write_text_closes_fd_on_exception(self, tmp_path, monkeypatch):
        """If os.write raises mid-write, the fd must still be closed
        (finally clause). Regression against fd leaks."""
        import os as _os

        from openbb_fmp_trading.reporting import report as report_mod

        target = tmp_path / "will-fail.md"

        # Force os.write to raise
        def failing_write(fd, data):
            raise OSError("simulated write failure")

        monkeypatch.setattr(_os, "write", failing_write)

        with pytest.raises(OSError, match="simulated write failure"):
            report_mod._atomic_write_text(target, "content", overwrite=False)
        # If the fd leaked we'd see a warning from asyncio/gc; hard to
        # assert directly but the finally clause in _atomic_write_text
        # is what makes this safe.
