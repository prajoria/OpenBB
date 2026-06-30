"""Tests for ``openbb_pine.runtime.fmp_provider`` -- D2 section 2."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from openbb_pine.errors import PineProviderError
from openbb_pine.runtime.fmp_provider import (
    FMPOHLCVProvider,
    FMPRequest,
    infer_asset_class,
)


# --- Asset-class inference -----------------------------------------------------


class TestInferAssetClass:
    """D2 section 2.2 -- symbol -> {equity,crypto,currency,commodity}."""

    @pytest.mark.parametrize("symbol", ["AAPL", "MSFT", "BRK.B", "SPY", "QQQ", "VOO"])
    def test_equity_default(self, symbol):
        assert infer_asset_class(symbol) == "equity"

    @pytest.mark.parametrize(
        "symbol", ["BTC-USD", "ETH-USD", "BTCUSD", "ETHUSD", "XBTUSD", "BTC-USDT", "SOL-USD"]
    )
    def test_crypto(self, symbol):
        assert infer_asset_class(symbol) == "crypto"

    @pytest.mark.parametrize("symbol", ["EUR/USD", "GBP/USD", "EURUSD", "GBPUSD", "USDJPY"])
    def test_currency(self, symbol):
        assert infer_asset_class(symbol) == "currency"

    @pytest.mark.parametrize("symbol", ["GC1!", "CL1!", "NG=F", "GC=F", "^GSPC"])
    def test_commodity_or_index(self, symbol):
        # Commodity prefixed/suffixed -- index ``^GSPC`` per D2 inference rule 3.
        assert infer_asset_class(symbol) in {"commodity"}


# --- FMPRequest dataclass ------------------------------------------------------


class TestFMPRequest:
    def test_request_is_frozen(self):
        req = FMPRequest(symbol="AAPL", interval="1d", start=None, end=None)
        with pytest.raises((AttributeError, Exception)):
            req.symbol = "TSLA"  # type: ignore[misc]

    def test_request_minimal_fields(self):
        req = FMPRequest(symbol="AAPL", interval="1d", start=None, end=None)
        assert req.symbol == "AAPL"
        assert req.interval == "1d"
        assert req.start is None and req.end is None


# --- FMPOHLCVProvider construction --------------------------------------------


class TestFMPOHLCVProviderInit:
    def test_provider_used_field_records_input(self):
        req = FMPRequest(symbol="AAPL", interval="1d", start=None, end=None)
        prov = FMPOHLCVProvider(req, provider="fmp")
        assert prov.provider_used == "fmp"

    def test_provider_used_fmp_cached(self):
        req = FMPRequest(symbol="AAPL", interval="1d", start=None, end=None)
        prov = FMPOHLCVProvider(req, provider="fmp_cached")
        assert prov.provider_used == "fmp_cached"

    def test_bars_consumed_starts_at_zero(self):
        req = FMPRequest(symbol="AAPL", interval="1d", start=None, end=None)
        prov = FMPOHLCVProvider(req, provider="fmp")
        assert prov.bars_consumed == 0

    def test_invalid_provider_raises_at_construction(self):
        req = FMPRequest(symbol="AAPL", interval="1d", start=None, end=None)
        with pytest.raises(PineProviderError):
            FMPOHLCVProvider(req, provider="yfinance")  # type: ignore[arg-type]


# --- Asset-class -> endpoint dispatch -----------------------------------------


def _patched_obb(historical_returns: pd.DataFrame):
    """Build a MagicMock chain that returns a fake OBBject with ``to_df``."""
    fake_obbj = MagicMock()
    fake_obbj.to_df.return_value = historical_returns
    obb = MagicMock()
    obb.equity.price.historical.return_value = fake_obbj
    obb.crypto.price.historical.return_value = fake_obbj
    obb.currency.price.historical.return_value = fake_obbj
    obb.commodity.price.historical.return_value = fake_obbj
    return obb, fake_obbj


def _make_frame(rows=3):
    idx = pd.DatetimeIndex(
        [datetime(2024, 1, 1, tzinfo=timezone.utc) + pd.Timedelta(days=i) for i in range(rows)],
        name="date",
    )
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(rows)],
            "high": [101.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
            "volume": [1_000_000.0 + i for i in range(rows)],
        },
        index=idx,
    )


class TestEndpointDispatch:
    """Per D2 section 2.2 -- one route per asset class."""

    def test_equity_routes_to_equity_endpoint(self):
        df = _make_frame()
        obb, _ = _patched_obb(df)
        req = FMPRequest(symbol="AAPL", interval="1d", start=None, end=None)
        prov = FMPOHLCVProvider(req, provider="fmp")
        with patch("openbb_pine.runtime.fmp_provider._import_obb", return_value=obb):
            list(prov.iter_ohlcv())
        assert obb.equity.price.historical.called
        assert not obb.crypto.price.historical.called

    def test_crypto_routes_to_crypto_endpoint(self):
        df = _make_frame()
        obb, _ = _patched_obb(df)
        req = FMPRequest(symbol="BTC-USD", interval="1d", start=None, end=None)
        prov = FMPOHLCVProvider(req, provider="fmp")
        with patch("openbb_pine.runtime.fmp_provider._import_obb", return_value=obb):
            list(prov.iter_ohlcv())
        assert obb.crypto.price.historical.called

    def test_currency_routes_to_currency_endpoint(self):
        df = _make_frame()
        obb, _ = _patched_obb(df)
        req = FMPRequest(symbol="EUR/USD", interval="1d", start=None, end=None)
        prov = FMPOHLCVProvider(req, provider="fmp")
        with patch("openbb_pine.runtime.fmp_provider._import_obb", return_value=obb):
            list(prov.iter_ohlcv())
        assert obb.currency.price.historical.called

    def test_commodity_routes_to_commodity_endpoint(self):
        df = _make_frame()
        obb, _ = _patched_obb(df)
        req = FMPRequest(symbol="GC1!", interval="1d", start=None, end=None)
        prov = FMPOHLCVProvider(req, provider="fmp")
        with patch("openbb_pine.runtime.fmp_provider._import_obb", return_value=obb):
            list(prov.iter_ohlcv())
        assert obb.commodity.price.historical.called


# --- Iterator shape & bars_consumed -------------------------------------------


class TestIterOHLCVShape:
    def test_yields_ohlcv_namedtuples_in_order(self):
        df = _make_frame(rows=3)
        obb, _ = _patched_obb(df)
        req = FMPRequest(symbol="AAPL", interval="1d", start=None, end=None)
        prov = FMPOHLCVProvider(req, provider="fmp")
        with patch("openbb_pine.runtime.fmp_provider._import_obb", return_value=obb):
            bars = list(prov.iter_ohlcv())
        assert len(bars) == 3
        # NamedTuple field-shape contract -- timestamp:int, then 5 floats.
        for bar in bars:
            assert isinstance(bar.timestamp, int)
            assert isinstance(bar.open, float)
            assert isinstance(bar.high, float)
            assert isinstance(bar.low, float)
            assert isinstance(bar.close, float)
            assert isinstance(bar.volume, float)
        # Time-monotonic.
        assert [b.timestamp for b in bars] == sorted(b.timestamp for b in bars)

    def test_bars_consumed_increments_per_yield(self):
        df = _make_frame(rows=5)
        obb, _ = _patched_obb(df)
        req = FMPRequest(symbol="AAPL", interval="1d", start=None, end=None)
        prov = FMPOHLCVProvider(req, provider="fmp")
        with patch("openbb_pine.runtime.fmp_provider._import_obb", return_value=obb):
            it = prov.iter_ohlcv()
            next(it)
            assert prov.bars_consumed == 1
            next(it)
            assert prov.bars_consumed == 2
            list(it)
            assert prov.bars_consumed == 5

    def test_endpoint_receives_symbol_and_interval(self):
        df = _make_frame()
        obb, _ = _patched_obb(df)
        req = FMPRequest(symbol="MSFT", interval="1h", start=None, end=None)
        prov = FMPOHLCVProvider(req, provider="fmp_cached")
        with patch("openbb_pine.runtime.fmp_provider._import_obb", return_value=obb):
            list(prov.iter_ohlcv())
        _, kwargs = obb.equity.price.historical.call_args
        assert kwargs.get("symbol") == "MSFT"
        # Interval may be translated -- but the request value is preserved enough
        # for FMP's standard model (1m/5m/15m/30m/1h/4h/1d).
        assert "interval" in kwargs
        # Provider routing reaches OpenBB.
        assert kwargs.get("provider") == "fmp_cached"


# --- Daily timestamp -> UTC seconds normalization -----------------------------


class TestTimestampNormalization:
    def test_naive_dates_promoted_to_utc(self):
        idx = pd.DatetimeIndex(
            [datetime(2024, 1, 1), datetime(2024, 1, 2)], name="date"
        )  # tz-naive
        df = pd.DataFrame(
            {
                "open": [1.0, 2.0],
                "high": [1.0, 2.0],
                "low": [1.0, 2.0],
                "close": [1.0, 2.0],
                "volume": [1.0, 2.0],
            },
            index=idx,
        )
        obb, _ = _patched_obb(df)
        req = FMPRequest(symbol="AAPL", interval="1d", start=None, end=None)
        prov = FMPOHLCVProvider(req, provider="fmp")
        with patch("openbb_pine.runtime.fmp_provider._import_obb", return_value=obb):
            bars = list(prov.iter_ohlcv())
        # 2024-01-01T00:00:00Z = 1704067200; 2024-01-02 = +86400.
        assert bars[0].timestamp == 1704067200
        assert bars[1].timestamp == 1704067200 + 86400

    def test_none_volume_coerces_to_zero(self):
        idx = pd.DatetimeIndex([datetime(2024, 1, 1, tzinfo=timezone.utc)], name="date")
        df = pd.DataFrame(
            {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [None]},
            index=idx,
        )
        obb, _ = _patched_obb(df)
        req = FMPRequest(symbol="AAPL", interval="1d", start=None, end=None)
        prov = FMPOHLCVProvider(req, provider="fmp")
        with patch("openbb_pine.runtime.fmp_provider._import_obb", return_value=obb):
            (bar,) = list(prov.iter_ohlcv())
        assert bar.volume == 0.0
