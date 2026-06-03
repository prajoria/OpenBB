"""Tests for complementary TNX service with internal fallback behavior."""

import pandas as pd
from unittest.mock import patch

from openbb_fmp_cached.complementary.free_yield_service import (
    get_latest_us10y_rate,
    get_us10y_series,
)


def _build_row(date_str: str, yield_pct: float, source: str) -> dict:
    return {
        "date": date_str,
        "yield_pct": yield_pct,
        "source": source,
        "raw": {"date": date_str, "value": yield_pct},
    }


def test_us10y_cache_hit_skips_provider_calls():
    """Cache hit should return cached data without calling upstream providers."""
    with (
        patch("openbb_fmp_cached.complementary.free_yield_service.init_database"),
        patch("openbb_fmp_cached.complementary.free_yield_service.repository.ensure_table"),
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.repository.read_cached_rows",
            return_value=[
                {"date": "2025-01-01", "close": 4.10, "additional_fields": {"source": "fmp"}},
                {"date": "2025-01-10", "close": 4.20, "additional_fields": {"source": "fmp"}},
            ],
        ),
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.fmp_source.fetch_us10y"
        ) as mock_fmp,
    ):
        result = get_us10y_series("2025-01-01", "2025-01-10")

    assert isinstance(result, pd.DataFrame)
    assert list(result["source"]) == ["fmp", "fmp"]
    mock_fmp.assert_not_called()


def test_us10y_fmp_success_path():
    """FMP success should persist and return normalized data."""
    with (
        patch("openbb_fmp_cached.complementary.free_yield_service.init_database"),
        patch("openbb_fmp_cached.complementary.free_yield_service.repository.ensure_table"),
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.repository.read_cached_rows",
            return_value=[],
        ),
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.repository.upsert_rows"
        ) as mock_upsert,
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.fmp_source.fetch_us10y",
            return_value=[_build_row("2025-01-10", 4.33, "fmp")],
        ) as mock_fmp,
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.fred_source.fetch_us10y"
        ) as mock_fred,
    ):
        result = get_us10y_series("2025-01-01", "2025-01-10")

    assert result.iloc[-1]["yield_pct"] == 4.33
    assert result.iloc[-1]["source"] == "fmp"
    mock_fmp.assert_called_once()
    mock_fred.assert_not_called()
    mock_upsert.assert_called_once()


def test_us10y_fmp_tier_failure_falls_back_to_fred(caplog):
    """Tier/access errors on FMP should fall back to FRED with info log."""
    with (
        patch("openbb_fmp_cached.complementary.free_yield_service.init_database"),
        patch("openbb_fmp_cached.complementary.free_yield_service.repository.ensure_table"),
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.repository.read_cached_rows",
            return_value=[],
        ),
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.fmp_source.fetch_us10y",
            side_effect=RuntimeError("403 forbidden - upgrade required"),
        ),
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.fred_source.fetch_us10y",
            return_value=[_build_row("2025-01-10", 4.19, "fred")],
        ) as mock_fred,
    ):
        with caplog.at_level("INFO"):
            result = get_us10y_series("2025-01-01", "2025-01-10", request_id="req-1")

    assert result.iloc[-1]["source"] == "fred"
    assert mock_fred.called
    assert "fallback transition" in caplog.text
    assert "tier_access" in caplog.text


def test_us10y_fmp_and_fred_fail_falls_back_to_yfinance():
    """When FMP and FRED fail, service should return YFinance data."""
    with (
        patch("openbb_fmp_cached.complementary.free_yield_service.init_database"),
        patch("openbb_fmp_cached.complementary.free_yield_service.repository.ensure_table"),
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.repository.read_cached_rows",
            return_value=[],
        ),
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.fmp_source.fetch_us10y",
            side_effect=RuntimeError("timeout"),
        ),
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.fred_source.fetch_us10y",
            side_effect=RuntimeError("fred unavailable"),
        ),
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.yahoo_source.fetch_us10y",
            return_value=[_build_row("2025-01-10", 4.01, "yfinance")],
        ) as mock_yahoo,
    ):
        result = get_us10y_series("2025-01-01", "2025-01-10")

    assert result.iloc[-1]["source"] == "yfinance"
    assert result.iloc[-1]["yield_pct"] == 4.01
    mock_yahoo.assert_called_once()


def test_latest_rate_returns_static_fallback_when_all_providers_fail(caplog):
    """Latest rate helper should return static fallback when no provider succeeds."""
    with (
        patch("openbb_fmp_cached.complementary.free_yield_service.init_database"),
        patch("openbb_fmp_cached.complementary.free_yield_service.repository.ensure_table"),
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.repository.read_cached_rows",
            return_value=[],
        ),
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.fmp_source.fetch_us10y",
            side_effect=RuntimeError("403"),
        ),
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.fred_source.fetch_us10y",
            side_effect=RuntimeError("down"),
        ),
        patch(
            "openbb_fmp_cached.complementary.free_yield_service.yahoo_source.fetch_us10y",
            side_effect=RuntimeError("down"),
        ),
    ):
        with caplog.at_level("WARNING"):
            rate, source = get_latest_us10y_rate("2025-01-01", "2025-01-10", fallback=0.031)

    assert rate == 0.031
    assert source == "fallback:static"
    assert "Using static fallback rate" in caplog.text
