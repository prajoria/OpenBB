"""Tests for the openbb_regime router (bd-0h2.16 / Phase B4).

Verifies the ``obb.regime.detect`` command:

* returns a valid OBBject with the correct MarketRegime string
* falls back to UNKNOWN + WARNING when SPY or VIX fetch fails
* passes the ``as_of`` parameter through to the detector
* preserves the router shape declared in pyproject.toml
* accepts custom symbols / provider / lookback

The router itself fetches SPY + VIX via ``obb.equity.price.historical``
and ``obb.index.price.historical``. Tests inject mock responses via
``unittest.mock.patch`` to avoid network dependency (all unit tests
here run in <1s without external API calls).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from openbb_regime.detector import (
    MarketRegime,
    _MIN_HISTORY_DAYS,
)
from openbb_regime.regime_router import (
    _DEFAULT_FETCH_DAYS,
    _DEFAULT_SPY_SYMBOL,
    _DEFAULT_VIX_SYMBOL,
    about,
    detect,
    router,
)


# --------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------- #

def _make_spy_close(n: int, above_sma_pct: float = 0.05) -> pd.DataFrame:
    """SPY OHLCV with close deterministic-above-SMA by the given pct."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    sma = 100.0
    close = sma * (1 + above_sma_pct) + np.linspace(0, n / 100, n)
    # 200 days of "trend" to give SMA time to establish
    early_close = np.linspace(sma - 5, sma, n) if n >= 200 else np.full(n, sma)
    close[:200] = early_close[:200]
    return pd.DataFrame({"close": close}, index=dates)


def _make_vix_close(n: int, level: float = 15.0) -> pd.DataFrame:
    """VIX OHLCV with a constant close level."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"close": np.full(n, level)}, index=dates)


def _mock_obb_response(df: pd.DataFrame) -> MagicMock:
    """Wrap a DataFrame in a mock OBBject with .to_df()."""
    m = MagicMock()
    m.to_df.return_value = df
    return m


# --------------------------------------------------------------------- #
# about endpoint
# --------------------------------------------------------------------- #

class TestAboutEndpoint:
    """Metadata endpoint smoke tests."""

    def test_about_returns_obbject_with_name(self):
        result = about()
        assert result.results["name"] == "openbb-regime"

    def test_about_lists_all_regimes(self):
        result = about()
        regimes = result.results["regimes"]
        # All 5 MarketRegime values must be listed
        for r in MarketRegime:
            assert r.value in regimes

    def test_about_documents_python_and_direct_import_paths(self):
        result = about()
        assert "obb.regime.detect" in result.results["python"]
        assert "detect_market_regime" in result.results["direct_import"]


# --------------------------------------------------------------------- #
# detect endpoint — happy paths
# --------------------------------------------------------------------- #

class TestDetectHappyPath:
    """Test cases where both SPY + VIX fetch succeed."""

    def test_bull_regime_returned_for_bull_fixtures(self):
        """SPY above 200d SMA + VIX low → TRENDING_BULL."""
        spy_df = _make_spy_close(300, above_sma_pct=0.05)
        vix_df = _make_vix_close(300, level=15.0)   # low VIX

        with patch("openbb.obb") as mock_obb:
            mock_obb.equity.price.historical.return_value = _mock_obb_response(spy_df)
            mock_obb.index.price.historical.return_value = _mock_obb_response(vix_df)

            result = detect()

        assert result.results["regime"] == MarketRegime.TRENDING_BULL.value

    def test_crisis_regime_returned_for_high_vix(self):
        """VIX above 30 alone → CRISIS (per iter-1 NOVEL-2 fix in detector)."""
        spy_df = _make_spy_close(300, above_sma_pct=0.05)   # bullish SPY
        vix_df = _make_vix_close(300, level=40.0)   # crisis VIX

        with patch("openbb.obb") as mock_obb:
            mock_obb.equity.price.historical.return_value = _mock_obb_response(spy_df)
            mock_obb.index.price.historical.return_value = _mock_obb_response(vix_df)

            result = detect()

        assert result.results["regime"] == MarketRegime.CRISIS.value

    def test_result_carries_diagnostic_fields(self):
        """Results dict must expose as_of, symbols, provider, row counts."""
        spy_df = _make_spy_close(300)
        vix_df = _make_vix_close(300)

        with patch("openbb.obb") as mock_obb:
            mock_obb.equity.price.historical.return_value = _mock_obb_response(spy_df)
            mock_obb.index.price.historical.return_value = _mock_obb_response(vix_df)

            result = detect(as_of="2026-01-15")

        assert result.results["as_of"] == "2026-01-15"
        assert result.results["spy_symbol"] == _DEFAULT_SPY_SYMBOL
        assert result.results["vix_symbol"] == _DEFAULT_VIX_SYMBOL
        assert result.results["spy_rows"] == 300
        assert result.results["vix_rows"] == 300

    def test_custom_symbols_and_provider_threaded_through(self):
        """Router must pass through custom symbol + provider kwargs."""
        spy_df = _make_spy_close(300)
        vix_df = _make_vix_close(300)

        with patch("openbb.obb") as mock_obb:
            mock_obb.equity.price.historical.return_value = _mock_obb_response(spy_df)
            mock_obb.index.price.historical.return_value = _mock_obb_response(vix_df)

            detect(
                spy_symbol="IVV",
                vix_symbol="^VXN",
                provider="yfinance",
            )

        # Verify obb.equity.price.historical was called with the custom symbol
        call_args = mock_obb.equity.price.historical.call_args
        assert call_args.kwargs["symbol"] == "IVV"
        assert call_args.kwargs["provider"] == "yfinance"
        # Same for VIX / index.price.historical
        call_args = mock_obb.index.price.historical.call_args
        assert call_args.kwargs["symbol"] == "^VXN"


# --------------------------------------------------------------------- #
# detect endpoint — R7.3 loud-empty paths
# --------------------------------------------------------------------- #

class TestDetectLoudEmpty:
    """Verify UNKNOWN + WARNING when a fetch fails."""

    def test_spy_fetch_failure_returns_unknown_with_reason(self, caplog):
        """SPY fetch raises → UNKNOWN result carrying the failure reason.

        R7.11 load-bearing: reverting the try/except around SPY fetch
        would make the exception propagate out → test flips from PASSED
        (asserting UNKNOWN return) to ERRORED.
        """
        import logging

        with patch("openbb.obb") as mock_obb:
            mock_obb.equity.price.historical.side_effect = RuntimeError(
                "fmp_cached: rate limit hit"
            )

            with caplog.at_level(logging.WARNING, logger="openbb_regime.regime_router"):
                result = detect()

        assert result.results["regime"] == MarketRegime.UNKNOWN.value
        assert "SPY fetch failed" in result.results["reason"]
        assert "rate limit" in result.results["error"]
        warnings = [r for r in caplog.records if "SPY fetch failed" in r.getMessage()]
        assert len(warnings) == 1

    def test_vix_fetch_failure_returns_unknown_with_reason(self, caplog):
        """VIX fetch raises → UNKNOWN result carrying the failure reason."""
        import logging
        spy_df = _make_spy_close(300)

        with patch("openbb.obb") as mock_obb:
            mock_obb.equity.price.historical.return_value = _mock_obb_response(spy_df)
            mock_obb.index.price.historical.side_effect = ValueError("no VIX data")

            with caplog.at_level(logging.WARNING, logger="openbb_regime.regime_router"):
                result = detect()

        assert result.results["regime"] == MarketRegime.UNKNOWN.value
        assert "VIX fetch failed" in result.results["reason"]
        assert "no VIX data" in result.results["error"]
        warnings = [r for r in caplog.records if "VIX fetch failed" in r.getMessage()]
        assert len(warnings) == 1


# --------------------------------------------------------------------- #
# detect endpoint — as_of parameter
# --------------------------------------------------------------------- #

class TestDetectAsOf:
    """The as_of parameter must be threaded through to the detector."""

    def test_as_of_narrows_fetch_window(self):
        """as_of=X → end_date=X + start_date=X-lookback_days."""
        spy_df = _make_spy_close(300)
        vix_df = _make_vix_close(300)

        with patch("openbb.obb") as mock_obb:
            mock_obb.equity.price.historical.return_value = _mock_obb_response(spy_df)
            mock_obb.index.price.historical.return_value = _mock_obb_response(vix_df)

            detect(as_of="2026-06-01", lookback_days=400)

        call_args = mock_obb.equity.price.historical.call_args.kwargs
        assert call_args["end_date"] == "2026-06-01"
        # start_date should be 400 days earlier
        start = pd.Timestamp(call_args["start_date"])
        end = pd.Timestamp(call_args["end_date"])
        assert (end - start).days == 400


# --------------------------------------------------------------------- #
# Router shape
# --------------------------------------------------------------------- #

class TestRouterShape:
    """Router must expose the expected commands + shape."""

    def test_router_has_detect_and_about_commands(self):
        """R7.11 load-bearing: mutating the @router.command decorator
        off `detect` or `about` would remove them from the router.
        Verify both are registered.
        """
        api_router = router.api_router
        paths = [route.path for route in api_router.routes]
        # Under prefix="" the paths are just /detect and /about
        assert any("detect" in p for p in paths)
        assert any("about" in p for p in paths)

    def test_module_scope_constants(self):
        """R7.10 module-scope defaults for symbols + lookback window."""
        assert _DEFAULT_FETCH_DAYS == 400
        assert _DEFAULT_SPY_SYMBOL == "SPY"
        assert _DEFAULT_VIX_SYMBOL == "^VIX"
        # lookback must exceed the detector's _MIN_HISTORY_DAYS + walkback
        assert _DEFAULT_FETCH_DAYS >= _MIN_HISTORY_DAYS + 33
