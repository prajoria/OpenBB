"""PII redaction invariants (§10 P1-4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from openbb_browser_test_harness.redact import (
    _DENY_FRAGMENTS,
    assert_screenshot_clean,
    contains_pii,
    redact_text,
)


def test_deny_list_includes_known_home_paths() -> None:
    assert any("Users" in f for f in _DENY_FRAGMENTS)


def test_contains_pii_flags_home_directory() -> None:
    has_pii, offender = contains_pii(r"C:\Users\daaji\project\file.py")
    assert has_pii
    assert offender


def test_contains_pii_clean_string_passes() -> None:
    has_pii, offender = contains_pii("hello world")
    assert not has_pii
    assert offender == ""


def test_redact_replaces_windows_home_path() -> None:
    redacted = redact_text(r"C:\Users\daaji\project\file.py")
    assert "daaji" not in redacted
    assert "<home>" in redacted


def test_redact_replaces_posix_home_path() -> None:
    redacted = redact_text("/home/daaji/project/file.py")
    assert "daaji" not in redacted
    assert "<home>" in redacted


def test_assert_screenshot_clean_refuses_bad_path() -> None:
    with pytest.raises(ValueError, match="PII fragment"):
        assert_screenshot_clean(Path(r"C:\Users\daaji\output\W0.png"))


def test_assert_screenshot_clean_accepts_safe_path() -> None:
    """A path with no home-directory fragment should pass.

    We deliberately don't use pytest's ``tmp_path`` fixture — on Windows
    it lives under ``C:\\Users\\<username>\\...`` which is exactly what
    the redaction guard rejects. That the guard rejects tmp_path is a
    feature, not a bug. Test with a bare relative path here.
    """
    # No exception raised.
    assert_screenshot_clean(Path("screenshots") / "W0.png")
