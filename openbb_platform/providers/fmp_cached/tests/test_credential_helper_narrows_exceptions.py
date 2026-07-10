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
        """Corrupted JSON logs a warning and falls back to env vars."""
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
        assert any("Failed to read" in rec.message for rec in caplog.records), (
            "Corrupted settings file MUST emit a WARNING log so operators "
            "can trace the fallback back to file-corruption (bd-gv1e). "
            "Pre-fix used ``except Exception: pass`` — silent."
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

    def test_unexpected_exception_propagates(self, monkeypatch):
        """A TypeError (bug in fallback code) MUST NOT be swallowed.

        This test locks the narrow-except discipline: bare ``except:``
        would catch TypeError too and silently return an env-fallback
        config, hiding the real bug. Post-fix narrow-except
        ``(JSONDecodeError, OSError, UnicodeDecodeError)`` lets TypeError
        propagate with a real traceback.
        """
        monkeypatch.setenv("DB_USER", "envuser")
        monkeypatch.setenv("DB_PASSWORD", "envpass")

        from openbb_fmp_cached.models import index_constituents as mod

        # Simulate a bug: json.load raises TypeError (not JSONDecodeError).
        with patch("os.path.exists", return_value=True), patch(
            "builtins.open", mock_open(read_data="{}")
        ), patch("json.load", side_effect=TypeError("unhashable type")):
            with pytest.raises(TypeError, match="unhashable type"):
                mod._get_db_config()


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
