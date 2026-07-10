"""Unit tests for credential-helper except narrowing — bd-gv1e.

``openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/
index_constituents.py::_get_db_config`` and ``_get_api_key`` pre-fix used
``except Exception: pass`` around the ``user_settings.json`` read. That
silently swallowed corrupted JSON, permission-denied errors, and unicode
decode errors — the user then saw a downstream "Missing MySQL credential"
error with no hint the settings file was broken.

Post-fix the except clause is narrowed to
``(json.JSONDecodeError, OSError, UnicodeDecodeError)`` with a
``logger.warning`` on the caught path. Unexpected exceptions (e.g. a
``TypeError`` from a bug in the fallback logic) MUST propagate so the
real bug isn't buried.

Security angle: swallowing PermissionError on a credentials file is
exactly what an attacker replacing the file with a symlink-to-unreadable
wants — post-fix, that generates a WARNING log so ops sees the tamper.
"""

from __future__ import annotations

import json
from unittest.mock import mock_open, patch

import pytest


class TestGetDbConfigExceptions:
    """_get_db_config narrows the settings-read except (bd-gv1e)."""

    def test_reads_valid_settings_file(self, monkeypatch, tmp_path):
        """Happy-path regression: valid JSON populates config from file."""
        monkeypatch.delenv("DB_USER", raising=False)
        monkeypatch.delenv("DB_PASSWORD", raising=False)

        settings = tmp_path / "user_settings.json"
        settings.write_text(
            json.dumps(
                {
                    "credentials": {
                        "mysql_host": "db.example.com",
                        "mysql_port": 3307,
                        "mysql_user": "u",
                        "mysql_password": "p",
                    }
                }
            )
        )

        from openbb_fmp_cached.models import index_constituents as mod

        with patch("os.path.expanduser", return_value=str(settings)):
            cfg = mod._get_db_config()

        assert cfg["host"] == "db.example.com"
        assert cfg["port"] == 3307
        assert cfg["user"] == "u"
        assert cfg["password"] == "p"

    def test_narrows_json_decode_error_with_warning(
        self, monkeypatch, tmp_path, caplog
    ):
        """Corrupted JSON logs a warning that names the specific path and falls back to env vars.

        Post-review-fix (PR #424 code-reviewer P2): the log assertion now
        checks the specific settings path substring so a future refactor
        that logs a generic "Failed to read" without the path (weakening
        the security-tracing intent) would fail this test.
        """
        monkeypatch.setenv("DB_USER", "envuser")
        monkeypatch.setenv("DB_PASSWORD", "envpass")

        settings = tmp_path / "user_settings.json"
        settings.write_text("{ this is not valid json")

        from openbb_fmp_cached.models import index_constituents as mod

        with patch("os.path.expanduser", return_value=str(settings)), caplog.at_level(
            "WARNING", logger="openbb_fmp_cached.models.index_constituents"
        ):
            cfg = mod._get_db_config()

        assert (
            cfg["user"] == "envuser"
        ), "Post-fix a JSONDecodeError MUST fall back to env vars, not raise."
        assert cfg["password"] == "envpass"
        # Log MUST identify the specific path (security-tracing intent).
        assert any(str(settings) in rec.message for rec in caplog.records), (
            f"WARNING log MUST include the specific settings_path so an "
            f"operator can trace which file was unreadable. Got: "
            f"{[rec.message for rec in caplog.records]}"
        )

    def test_narrows_permission_error_with_warning(self, monkeypatch, caplog):
        """PermissionError on the settings file logs warning + falls back.

        Security angle: this is the exact scenario an attacker replacing
        user_settings.json with a symlink-to-unreadable-file wants to hide.
        Post-fix we log it.
        """
        monkeypatch.setenv("DB_USER", "envuser")
        monkeypatch.setenv("DB_PASSWORD", "envpass")

        from openbb_fmp_cached.models import index_constituents as mod

        # os.path.exists returns True, but open() raises PermissionError.
        with patch("os.path.exists", return_value=True), patch(
            "builtins.open", side_effect=PermissionError("chmod 000")
        ), caplog.at_level(
            "WARNING", logger="openbb_fmp_cached.models.index_constituents"
        ):
            cfg = mod._get_db_config()

        assert cfg["user"] == "envuser"
        assert cfg["password"] == "envpass"
        assert any(
            "Failed to read" in rec.message and "chmod 000" in rec.message
            for rec in caplog.records
        ), (
            "PermissionError on credentials file MUST log WARNING with the "
            "specific exception message (bd-gv1e security angle)."
        )

    def test_unexpected_exception_propagates(self, monkeypatch, tmp_path):
        """A malformed mysql_port MUST raise ValueError with the specific path.

        Post-review-fix (PR #424 code-reviewer P1a + silent-failure-hunter
        P1a): pre-review this test used a synthetic ``TypeError`` from a
        mocked json.load — didn't reflect a realistic user config.
        Post-fix uses the actual realistic scenario: user's
        ``user_settings.json`` has ``"mysql_port": "3306abc"``. Pre-fix
        (bd-gv1e's original state) would silently fall back to the
        default port 3306, hiding the misconfig. Post-fix the try-scope
        is narrowed to I/O + parse only, so the int() coerce error
        surfaces as ValueError with the specific path + value in the
        message — operator can debug.
        """
        monkeypatch.setenv("DB_USER", "u")
        monkeypatch.setenv("DB_PASSWORD", "p")

        settings = tmp_path / "user_settings.json"
        settings.write_text(json.dumps({"credentials": {"mysql_port": "3306abc"}}))

        from openbb_fmp_cached.models import index_constituents as mod

        with patch("os.path.expanduser", return_value=str(settings)):
            with pytest.raises(ValueError, match="3306abc") as exc_info:
                mod._get_db_config()

        # Error message MUST include the settings path so the operator
        # knows which file to fix.
        assert str(settings) in str(exc_info.value), (
            f"ValueError on bad mysql_port MUST name the settings path. "
            f"Got: {exc_info.value}"
        )

    def test_credentials_not_dict_raises_typeerror_with_path(
        self, monkeypatch, tmp_path
    ):
        """PR #424 silent-failure-hunter P1c: shape drift MUST surface.

        User writes ``"credentials": []`` (a list, not a dict). Pre-fix
        AttributeError from creds.get() was silently swallowed by bare
        except: pass → env fallback. Post-fix narrow-try-scope lets the
        shape check surface a TypeError with the path so operator can
        fix the file.
        """
        monkeypatch.setenv("DB_USER", "u")
        monkeypatch.setenv("DB_PASSWORD", "p")

        settings = tmp_path / "user_settings.json"
        settings.write_text(json.dumps({"credentials": []}))

        from openbb_fmp_cached.models import index_constituents as mod

        with patch("os.path.expanduser", return_value=str(settings)):
            with pytest.raises(TypeError, match="credentials.*must be a JSON object"):
                mod._get_db_config()

    def test_missing_port_key_uses_env_default_not_typeerror(
        self, monkeypatch, tmp_path
    ):
        """PR #424 silent-failure-hunter P1b: int(None) MUST NOT crash.

        If mysql_port is absent from settings AND DB_PORT env is unset,
        pre-review-fix code did ``int(creds.get("mysql_port", port))``
        where port was None → int(None) → TypeError, propagates and
        crashes. Post-fix guards on ``raw_port is not None`` so the
        default port 3306 sticks and the flow continues.
        """
        monkeypatch.setenv("DB_USER", "u")
        monkeypatch.setenv("DB_PASSWORD", "p")
        monkeypatch.delenv("DB_PORT", raising=False)

        settings = tmp_path / "user_settings.json"
        settings.write_text(json.dumps({"credentials": {"mysql_user": "override_u"}}))

        from openbb_fmp_cached.models import index_constituents as mod

        with patch("os.path.expanduser", return_value=str(settings)):
            cfg = mod._get_db_config()

        assert cfg["port"] == 3306, (
            "Missing mysql_port MUST use the default 3306, NOT crash with "
            "int(None) TypeError."
        )
        assert cfg["user"] == "override_u"

    def test_utf8_with_bom_still_readable(self, monkeypatch, tmp_path):
        """PR #424 silent-failure-hunter P2: BOM-prefixed settings must load.

        A settings file written on Windows may have a UTF-8 BOM (``\\ufeff``
        prefix). Pre-review-fix used ``encoding="utf-8"`` which raises
        UnicodeDecodeError on BOM — post-review-fix uses ``utf-8-sig``
        which strips the BOM transparently, preserving compatibility
        with Windows users' existing settings files.
        """
        monkeypatch.delenv("DB_USER", raising=False)
        monkeypatch.delenv("DB_PASSWORD", raising=False)

        settings = tmp_path / "user_settings.json"
        # Write BOM + valid JSON.
        settings.write_bytes(
            b"\xef\xbb\xbf"  # UTF-8 BOM
            + json.dumps(
                {
                    "credentials": {
                        "mysql_user": "bom_user",
                        "mysql_password": "bom_pass",
                    }
                }
            ).encode("utf-8")
        )

        from openbb_fmp_cached.models import index_constituents as mod

        with patch("os.path.expanduser", return_value=str(settings)):
            cfg = mod._get_db_config()

        assert cfg["user"] == "bom_user", (
            "BOM-prefixed settings file MUST load cleanly (utf-8-sig). "
            "Pre-review-fix used utf-8 which would raise UnicodeDecodeError."
        )
        assert cfg["password"] == "bom_pass"


class TestGetApiKeyExceptions:
    """_get_api_key narrows the settings-read except (bd-gv1e)."""

    def test_env_var_takes_precedence(self, monkeypatch):
        """Env-first ordering preserved (D5)."""
        monkeypatch.setenv("FMP_API_KEY", "env-key")
        monkeypatch.delenv("FMP_CACHED_API_KEY", raising=False)

        from openbb_fmp_cached.models import index_constituents as mod

        # Settings file MUST NOT even be checked if env is set.
        with patch("os.path.exists") as mock_exists:
            key = mod._get_api_key()

        assert key == "env-key"
        assert mock_exists.call_count == 0, (
            "Env-first ordering: if FMP_API_KEY is set, settings file "
            "MUST NOT be read at all."
        )

    def test_narrows_json_decode_error_with_warning(
        self, monkeypatch, tmp_path, caplog
    ):
        """Corrupted JSON logs warning + returns empty string (matches pre-fix fallback)."""
        monkeypatch.delenv("FMP_API_KEY", raising=False)
        monkeypatch.delenv("FMP_CACHED_API_KEY", raising=False)

        settings = tmp_path / "user_settings.json"
        settings.write_text("{ not json")

        from openbb_fmp_cached.models import index_constituents as mod

        with patch("os.path.expanduser", return_value=str(settings)), caplog.at_level(
            "WARNING", logger="openbb_fmp_cached.models.index_constituents"
        ):
            key = mod._get_api_key()

        assert key == ""
        assert any(
            "Failed to read" in rec.message for rec in caplog.records
        ), "Corrupted settings during api-key read MUST log WARNING (bd-gv1e)."

    def test_unexpected_exception_propagates(self, monkeypatch):
        """TypeError from a bug MUST NOT be swallowed."""
        monkeypatch.delenv("FMP_API_KEY", raising=False)
        monkeypatch.delenv("FMP_CACHED_API_KEY", raising=False)

        from openbb_fmp_cached.models import index_constituents as mod

        with patch("os.path.exists", return_value=True), patch(
            "builtins.open", mock_open(read_data="{}")
        ), patch("json.load", side_effect=TypeError("bug!")):
            with pytest.raises(TypeError, match="bug!"):
                mod._get_api_key()
