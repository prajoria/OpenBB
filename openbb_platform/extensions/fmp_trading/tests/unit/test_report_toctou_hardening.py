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


# ---------------------------------------------------------------------------
# Round 5 review fixes: xlsx mkstemp+rename atomic write, mkdir-window re-check
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlink creation requires admin on Windows"
)
class TestMkdirWindowReCheck:
    """Round 5 P1: re-run _reject_symlinks_in_chain AFTER mkdir(parents=True)
    so a symlink planted in the window between _resolve_output_dir's chain-walk
    and the mkdir call is still caught.
    """

    def test_symlink_planted_after_resolve_but_before_mkdir_is_caught(
        self, tmp_path, monkeypatch
    ):
        """Simulate a race by planting the symlink during the mkdir call.

        We monkey-patch Path.mkdir to plant a symlink at output_dir BEFORE
        the underlying mkdir call runs. The post-mkdir chain re-check
        must fire OutputPathEscapesJail.
        """
        from openbb_fmp_trading.reporting import report as report_mod
        from openbb_fmp_trading.reporting.errors import OutputPathEscapesJail

        # Use tmp_path as the jail
        monkeypatch.setattr(
            report_mod, "_reports_root", lambda: tmp_path
        )
        # Give ourselves a session_id + minimal journal so report() runs
        # up through the mkdir + re-check gate
        from openbb_fmp_trading.reporting import journal_reader

        monkeypatch.setattr(
            journal_reader, "read_session_events", lambda sid: iter([])
        )
        # Compute metrics from empty events must not error
        from openbb_fmp_trading.models.report import SessionMetrics
        from decimal import Decimal
        monkeypatch.setattr(
            journal_reader,
            "compute_metrics_from_events",
            lambda events: SessionMetrics(
                realized_pnl=Decimal("0"),
                pnl_source="empty",
                total_commissions=Decimal("0"),
                total_slippage=Decimal("0"),
                veto_counts_by_gate={},
                fill_count=0,
                order_count=0,
            ),
        )
        # Force session_date to today so _parse_session_date won't raise
        from datetime import date as _date
        monkeypatch.setattr(
            report_mod, "_parse_session_date", lambda sid, events: _date(2026, 7, 11)
        )

        target_output_dir = tmp_path / "daytrade_2026-07-11"
        outside = tmp_path.parent / "outside_jail_target"
        outside.mkdir(exist_ok=True)

        original_mkdir = Path.mkdir

        def racing_mkdir(self, *args, **kwargs):
            # Plant a symlink at exactly the target output_dir path
            # BEFORE the real mkdir runs (simulating the race window).
            if self == target_output_dir and not self.exists():
                self.symlink_to(outside, target_is_directory=True)
                return None  # mkdir(exist_ok=True) on the symlink is a no-op
            return original_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", racing_mkdir)

        with pytest.raises(OutputPathEscapesJail, match="symlink"):
            report_mod.report(session_id="s20260711120000")


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="mkstemp+rename atomicity is POSIX-specific; Windows uses different flow",
)
class TestXlsxMkstempRename:
    """Round 5 P0: xlsx path uses tempfile.mkstemp + os.replace to close the
    close→reopen window in the old unlink+open+close+openpyxl-reopen sequence.
    """

    def test_xlsx_temp_file_cleaned_up_on_build_failure(self, tmp_path, monkeypatch):
        """If build_workbook raises, the tempfile in output_dir must not linger."""
        from openbb_fmp_trading.reporting import report as report_mod
        from openbb_fmp_trading.reporting.xlsx_builder import XLSXUnavailable

        monkeypatch.setattr(report_mod, "_reports_root", lambda: tmp_path)

        from openbb_fmp_trading.reporting import journal_reader

        monkeypatch.setattr(
            journal_reader, "read_session_events", lambda sid: iter([])
        )
        from openbb_fmp_trading.models.report import SessionMetrics
        from decimal import Decimal

        monkeypatch.setattr(
            journal_reader,
            "compute_metrics_from_events",
            lambda events: SessionMetrics(
                realized_pnl=Decimal("0"),
                pnl_source="empty",
                total_commissions=Decimal("0"),
                total_slippage=Decimal("0"),
                veto_counts_by_gate={},
                fill_count=0,
                order_count=0,
            ),
        )
        from datetime import date as _date

        monkeypatch.setattr(
            report_mod,
            "_parse_session_date",
            lambda sid, events: _date(2026, 7, 11),
        )

        # Force build_workbook to raise XLSXUnavailable so we hit the
        # tempfile-cleanup path in the finally block.
        from openbb_fmp_trading.reporting import xlsx_builder

        def raising_build(*args, **kwargs):
            raise XLSXUnavailable("simulated")

        monkeypatch.setattr(xlsx_builder, "build_workbook", raising_build)

        result = report_mod.report(session_id="s20260711120000", format="xlsx")

        # xlsx build failed → xlsx_path should be None in the manifest
        assert result.xlsx_path is None
        # No lingering .end_of_day.xlsx.*.tmp files in output_dir
        output_dir = tmp_path / "daytrade_2026-07-11"
        stale = list(output_dir.glob(".end_of_day.xlsx.*.tmp"))
        assert stale == [], f"tempfile leaked on build failure: {stale}"

    def test_xlsx_write_atomic_no_partial_file_on_success(self, tmp_path, monkeypatch):
        """After successful build, xlsx_path exists AND no tempfile lingers."""
        from openbb_fmp_trading.reporting import report as report_mod

        monkeypatch.setattr(report_mod, "_reports_root", lambda: tmp_path)

        from openbb_fmp_trading.reporting import journal_reader

        monkeypatch.setattr(
            journal_reader, "read_session_events", lambda sid: iter([])
        )
        from openbb_fmp_trading.models.report import SessionMetrics
        from decimal import Decimal

        monkeypatch.setattr(
            journal_reader,
            "compute_metrics_from_events",
            lambda events: SessionMetrics(
                realized_pnl=Decimal("0"),
                pnl_source="empty",
                total_commissions=Decimal("0"),
                total_slippage=Decimal("0"),
                veto_counts_by_gate={},
                fill_count=0,
                order_count=0,
            ),
        )
        from datetime import date as _date

        monkeypatch.setattr(
            report_mod,
            "_parse_session_date",
            lambda sid, events: _date(2026, 7, 11),
        )

        # Stub build_workbook to actually write a minimal file so we
        # exercise the successful os.replace path.
        from openbb_fmp_trading.reporting import xlsx_builder

        def fake_build(session_id, events, metrics, path):
            path.write_bytes(b"PK\x03\x04fake-xlsx")

        monkeypatch.setattr(xlsx_builder, "build_workbook", fake_build)

        result = report_mod.report(session_id="s20260711120000", format="xlsx")

        assert result.xlsx_path is not None
        assert result.xlsx_path.exists()
        assert result.xlsx_path.read_bytes().startswith(b"PK\x03\x04")
        # No leftover tempfile
        output_dir = tmp_path / "daytrade_2026-07-11"
        stale = list(output_dir.glob(".end_of_day.xlsx.*.tmp"))
        assert stale == [], f"tempfile leaked on success: {stale}"

    def test_xlsx_symlink_at_target_rejected_before_temp_created(
        self, tmp_path, monkeypatch
    ):
        """A pre-existing symlink at xlsx_path must be caught (via is_symlink
        check) before any tempfile is created. Regression: `exists()` returns
        False for a broken symlink, so a bare `if path.exists()` check would
        miss a symlink pointing at a nonexistent target."""
        from openbb_fmp_trading.reporting import report as report_mod
        from openbb_fmp_trading.reporting.errors import OutputPathEscapesJail

        monkeypatch.setattr(report_mod, "_reports_root", lambda: tmp_path)

        from openbb_fmp_trading.reporting import journal_reader

        monkeypatch.setattr(
            journal_reader, "read_session_events", lambda sid: iter([])
        )
        from openbb_fmp_trading.models.report import SessionMetrics
        from decimal import Decimal

        monkeypatch.setattr(
            journal_reader,
            "compute_metrics_from_events",
            lambda events: SessionMetrics(
                realized_pnl=Decimal("0"),
                pnl_source="empty",
                total_commissions=Decimal("0"),
                total_slippage=Decimal("0"),
                veto_counts_by_gate={},
                fill_count=0,
                order_count=0,
            ),
        )
        from datetime import date as _date

        monkeypatch.setattr(
            report_mod,
            "_parse_session_date",
            lambda sid, events: _date(2026, 7, 11),
        )

        # Pre-create output_dir and plant a dangling symlink at the xlsx target
        output_dir = tmp_path / "daytrade_2026-07-11"
        output_dir.mkdir(parents=True, exist_ok=True)
        xlsx_target = output_dir / "end_of_day.xlsx"
        dangling = tmp_path.parent / "outside-dangling-target.xlsx"
        # Do NOT create `dangling` — the symlink target is nonexistent
        xlsx_target.symlink_to(dangling)

        # exists() on a dangling symlink returns False; is_symlink() returns True.
        assert not xlsx_target.exists()
        assert xlsx_target.is_symlink()

        with pytest.raises(OutputPathEscapesJail, match="symlink"):
            report_mod.report(session_id="s20260711120000", format="xlsx")
