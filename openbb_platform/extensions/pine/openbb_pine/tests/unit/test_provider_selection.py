"""Tests for ``openbb_pine.runtime.provider_selection`` -- D2 section 4 + PRD section 13.8."""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from openbb_pine.errors import PineProviderError
from openbb_pine.runtime.provider_selection import resolve_provider


class TestExplicitRequest:
    """Branch 1 -- caller passed ``provider="fmp"`` or ``"fmp_cached"``."""

    def test_explicit_fmp_returns_fmp(self):
        assert resolve_provider("fmp") == "fmp"

    def test_explicit_fmp_cached_returns_fmp_cached(self):
        assert resolve_provider("fmp_cached") == "fmp_cached"

    def test_explicit_value_wins_even_when_fmp_cached_unavailable(self):
        """``provider="fmp_cached"`` must be honored even if the module is
        not importable -- the downstream ``obb.equity.price.historical`` call
        will surface the real error after the retry budget (D2 section 4)."""
        # Patch find_spec to simulate openbb_fmp_cached missing.
        with patch("openbb_pine.runtime.provider_selection.importlib.util.find_spec") as fs:
            fs.return_value = None
            assert resolve_provider("fmp_cached") == "fmp_cached"


class TestDefaultPrecedence:
    """Branch 2 -- caller passed nothing; prefer fmp_cached if installed."""

    def test_default_prefers_fmp_cached_when_installed(self):
        with patch("openbb_pine.runtime.provider_selection.importlib.util.find_spec") as fs:
            # Return truthy spec object only for openbb_fmp_cached.
            fs.side_effect = lambda name: (
                SimpleNamespace(name=name) if name == "openbb_fmp_cached" else None
            )
            assert resolve_provider(None) == "fmp_cached"

    def test_default_falls_back_to_fmp_without_fmp_cached(self):
        with patch("openbb_pine.runtime.provider_selection.importlib.util.find_spec") as fs:
            fs.return_value = None
            assert resolve_provider(None) == "fmp"


class TestFastFail:
    """Branch 3 -- any non-FMP provider raises ``PineProviderError`` (PRD section 13.8)."""

    @pytest.mark.parametrize("bad", ["yfinance", "alpha_vantage", "polygon", "intrinio"])
    def test_non_fmp_raises_provider_error(self, bad):
        with pytest.raises(PineProviderError) as excinfo:
            resolve_provider(bad)
        msg = str(excinfo.value)
        # PRD section 13.8 message-shape contract.
        assert "fmp" in msg and "fmp_cached" in msg
        assert bad in msg or repr(bad) in msg
        # Tracking URL surfaced for users.
        assert "github.com" in msg.lower()

    def test_non_fmp_error_carries_requested_attribute(self):
        with pytest.raises(PineProviderError) as excinfo:
            resolve_provider("yfinance")
        assert getattr(excinfo.value, "requested", None) == "yfinance"

    def test_non_fmp_error_carries_supported_tuple(self):
        with pytest.raises(PineProviderError) as excinfo:
            resolve_provider("polygon")
        assert getattr(excinfo.value, "supported", None) == ("fmp", "fmp_cached")


class TestUserSettings:
    """``settings`` shape -- user_settings.defaults.commands key (D2 section 4)."""

    def test_settings_with_fmp_preference_returns_fmp(self):
        settings = SimpleNamespace(
            defaults=SimpleNamespace(
                commands={"equity.price.historical": {"provider": ["fmp"]}}
            )
        )
        # No explicit request -> preference wins.
        with patch("openbb_pine.runtime.provider_selection.importlib.util.find_spec") as fs:
            fs.return_value = None
            assert resolve_provider(None, settings=settings) == "fmp"

    def test_settings_with_non_fmp_preference_raises_fast(self):
        settings = SimpleNamespace(
            defaults=SimpleNamespace(
                commands={"equity.price.historical": {"provider": ["yfinance"]}}
            )
        )
        with pytest.raises(PineProviderError) as excinfo:
            resolve_provider(None, settings=settings)
        assert excinfo.value.requested == "yfinance"

    def test_settings_with_no_relevant_entry_uses_default(self):
        settings = SimpleNamespace(defaults=SimpleNamespace(commands={}))
        with patch("openbb_pine.runtime.provider_selection.importlib.util.find_spec") as fs:
            fs.return_value = None
            assert resolve_provider(None, settings=settings) == "fmp"

    def test_settings_with_string_provider_not_list(self):
        """``Defaults.validate_before`` normalizes string -> list, but be defensive."""
        settings = SimpleNamespace(
            defaults=SimpleNamespace(
                commands={"equity.price.historical": {"provider": "fmp_cached"}}
            )
        )
        with patch("openbb_pine.runtime.provider_selection.importlib.util.find_spec") as fs:
            fs.return_value = None
            assert resolve_provider(None, settings=settings) == "fmp_cached"
