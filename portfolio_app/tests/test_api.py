"""
API integration tests for portfolio_app — FastAPI TestClient.

Uses unittest.mock to patch data-layer functions so no database
or external service is needed.  Mock data comes from the generated
fixtures (tests/fixtures/*.json) — the same data used by test_service.py.

Run with:
    python -m pytest portfolio_app/tests/test_api.py -v
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

# Make portfolio_app/src importable
_portfolio_app_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_portfolio_app_dir / "src"))
sys.path.insert(0, str(_portfolio_app_dir))

from main import app  # noqa: E402
from tests.mock_data_generator import (  # noqa: E402
    load_account_owner,
    load_equity_historical,
    load_espp,
    load_positions,
)

# --------------------------------------------------------------------------- #
#  Load generated fixtures once at module level
# --------------------------------------------------------------------------- #

_POSITIONS = load_positions()
_ESPP = load_espp()
_EQUITY_HIST = load_equity_historical()
_ACCOUNT_OWNER = load_account_owner()

# Derived constants from the fixture data
_POS_DF = pd.DataFrame(_POSITIONS)
_LATEST_SNAP = (
    _POS_DF.groupby("account_name")["snapshot_date"].transform("max")
)
_LATEST_POS_DF = _POS_DF[_POS_DF["snapshot_date"] == _LATEST_SNAP].reset_index(
    drop=True
)
_SNAPSHOT_DATES = sorted(_POS_DF["snapshot_date"].unique())
_SYMBOLS = sorted(_LATEST_POS_DF["symbol"].unique())
_ACCOUNTS = sorted(_LATEST_POS_DF["account_name"].unique())
_OWNERS = sorted(_LATEST_POS_DF["owner"].unique())
_TERMS_NON_EMPTY = sorted(
    t for t in _LATEST_POS_DF["term"].unique() if str(t).strip()
)
_ONE_ACCOUNT = _ACCOUNTS[0]
_ONE_OWNER = _OWNERS[0]
_ONE_SYMBOL = _SYMBOLS[0]


# --------------------------------------------------------------------------- #
#  Patching helpers
# --------------------------------------------------------------------------- #


def _positions_df(*a, **kw):
    return pd.DataFrame(_POSITIONS)


def _basket_df(*a, **kw):
    df = _LATEST_POS_DF.copy()
    grouped = (
        df.groupby(["symbol", "description"], as_index=False)
        .agg(
            total_quantity=("quantity", "sum"),
            total_cost_basis=("cost_basis_total", "sum"),
            total_current_value=("current_value", "sum"),
            total_gain_loss=("total_gain_loss", "sum"),
            snapshot_date=("snapshot_date", "first"),
        )
    )
    total_value = grouped["total_current_value"].sum()
    grouped["pct_return"] = (
        (grouped["total_gain_loss"] / grouped["total_cost_basis"].replace(0, float("nan"))) * 100
    ).round(2).fillna(0)
    grouped["portfolio_weight_pct"] = (
        grouped["total_current_value"] / total_value * 100 if total_value else 0
    )
    return grouped


def _basket_snapshots_df(*a, **kw):
    df = pd.DataFrame(_POSITIONS)
    return (
        df.groupby(["snapshot_date", "symbol"], as_index=False)
        .agg(
            total_cost_basis=("cost_basis_total", "sum"),
            total_current_value=("current_value", "sum"),
            total_gain_loss=("total_gain_loss", "sum"),
        )
    )


def _espp_df(*a, **kw):
    return pd.DataFrame(_ESPP)


def _equity_df(*a, **kw):
    return pd.DataFrame(_EQUITY_HIST)


def _latest_prices_df(*a, **kw):
    """Latest close per symbol from equity_historical fixture."""
    eh = pd.DataFrame(_EQUITY_HIST)
    if eh.empty:
        return pd.DataFrame(columns=["symbol", "close", "price_date"])
    idx = eh.groupby("symbol")["date"].idxmax()
    latest = eh.loc[idx, ["symbol", "close", "date"]].copy()
    latest = latest.rename(columns={"date": "price_date"})
    return latest.reset_index(drop=True)


def _check_db():
    return True


def _distinct_symbols():
    return [{"label": s, "value": s} for s in _SYMBOLS]


def _distinct_accounts():
    return []


def _distinct_owners():
    return []


SYNC_PATCHES = {
    "main.get_portfolio_basket_df": _basket_df,
    "main.get_all_basket_snapshots_df": _basket_snapshots_df,
    "main.get_espp_df": _espp_df,
    "main.get_equity_historical_df": _equity_df,
    "main.check_db": _check_db,
    "main.get_distinct_symbols": _distinct_symbols,
    "main.get_distinct_accounts": _distinct_accounts,
    "main.get_distinct_owners": _distinct_owners,
}


@pytest.fixture
def client():
    """Synchronous test client — no real server started."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_data_layer():
    """Auto-mock all data-layer functions for every test."""
    all_patches = [patch(k, side_effect=v) for k, v in SYNC_PATCHES.items()]
    mocks = [p.start() for p in all_patches]
    yield mocks
    for p in all_patches:
        p.stop()


# =========================================================================== #
#  Metadata endpoints
# =========================================================================== #


class TestMetadataEndpoints:
    def test_root(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_widgets_json(self, client):
        r = client.get("/widgets.json")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (list, dict))
        assert len(data) > 0

    def test_apps_json(self, client):
        r = client.get("/apps.json")
        assert r.status_code == 200

    def test_get_symbols(self, client):
        r = client.get("/get_symbols")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == len(_SYMBOLS)

    def test_get_accounts(self, client):
        r = client.get("/get_accounts")
        assert r.status_code == 200
        assert r.json() == []

    def test_get_owners(self, client):
        r = client.get("/get_owners")
        assert r.status_code == 200
        assert r.json() == []


# =========================================================================== #
#  Portfolio endpoints
# =========================================================================== #


class TestPositionsEndpoint:
    def test_blocked(self, client):
        r = client.get("/portfolio/positions")
        assert r.status_code == 403


class TestSummaryEndpoint:
    def test_returns_basket_rows(self, client):
        r = client.get("/portfolio/summary")
        assert r.status_code == 200
        data = r.json()
        symbols = {row["symbol"] for row in data}
        assert len(symbols) > 0
        assert len(data) == len(_SYMBOLS)

    def test_has_weight_and_return(self, client):
        r = client.get("/portfolio/summary")
        for row in r.json():
            assert "pct_return" in row
            assert "portfolio_weight_pct" in row
            assert isinstance(row["pct_return"], (int, float))

    def test_filter_by_symbol(self, client):
        r = client.get(f"/portfolio/summary?symbol={_ONE_SYMBOL}")
        data = r.json()
        assert len(data) == 1
        assert data[0]["symbol"] == _ONE_SYMBOL

    def test_sorted_by_weight_desc(self, client):
        r = client.get("/portfolio/summary")
        weights = [row["portfolio_weight_pct"] for row in r.json()]
        assert weights == sorted(weights, reverse=True)


class TestAllocationEndpoint:
    def test_blocked(self, client):
        r = client.get("/portfolio/allocation")
        assert r.status_code == 403


class TestCostBasisEndpoint:
    def test_blocked(self, client):
        r = client.get("/portfolio/cost_basis")
        assert r.status_code == 403


class TestTaxSummaryEndpoint:
    def test_blocked(self, client):
        r = client.get("/portfolio/tax_summary")
        assert r.status_code == 403


class TestPerformanceEndpoint:
    def test_sorted_by_return(self, client):
        r = client.get("/portfolio/performance")
        assert r.status_code == 200
        data = r.json()
        pcts = [row["pct_return"] for row in data]
        assert pcts == sorted(pcts, reverse=True)

    def test_has_basket_weight(self, client):
        r = client.get("/portfolio/performance")
        data = r.json()
        assert all("portfolio_weight_pct" in row for row in data)


class TestSnapshotsEndpoint:
    def test_returns_by_date(self, client):
        r = client.get("/portfolio/snapshots")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == len(_SNAPSHOT_DATES)

    def test_sorted_by_date(self, client):
        r = client.get("/portfolio/snapshots")
        dates = [row["snapshot_date"] for row in r.json()]
        assert dates == sorted(dates)

    def test_has_totals(self, client):
        r = client.get("/portfolio/snapshots")
        for row in r.json():
            assert "stocks" in row
            assert "total_current_value" in row
            assert row["stocks"] > 0


class TestEsppEndpoint:
    def test_returns_purchases(self, client):
        r = client.get("/espp/purchases")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == len(_ESPP)

    def test_has_purchase_fields(self, client):
        r = client.get("/espp/purchases")
        for row in r.json():
            assert "purchase_date" in row
            assert "symbol" in row


class TestEquityHistoricalEndpoint:
    def test_returns_prices(self, client):
        r = client.get(f"/equity/historical?symbol={_ONE_SYMBOL}")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == len(_EQUITY_HIST)

    def test_has_ohlcv(self, client):
        r = client.get(f"/equity/historical?symbol={_ONE_SYMBOL}")
        for row in r.json():
            for col in ("open", "high", "low", "close", "volume"):
                assert col in row


# =========================================================================== #
#  Market proxy endpoints (mock the OpenBB client)
# =========================================================================== #


class TestMarketQuoteEndpoint:
    def test_proxy_success(self, client):
        with patch("main.obb_client") as mock_obb:
            mock_obb.get = AsyncMock(
                return_value=[{"symbol": "TEST", "price": 123.45}]
            )
            r = client.get("/market/quote?symbol=TEST")
            assert r.status_code == 200
            assert r.json()[0]["symbol"] == "TEST"

    def test_proxy_failure(self, client):
        with patch("main.obb_client") as mock_obb:
            mock_obb.get = AsyncMock(return_value=None)
            r = client.get("/market/quote?symbol=TEST")
            assert r.status_code == 502


class TestMarketHistoricalEndpoint:
    def test_proxy_success(self, client):
        with patch("main.obb_client") as mock_obb:
            mock_obb.get = AsyncMock(
                return_value=[{"date": "2025-01-01", "close": 100}]
            )
            r = client.get("/market/historical?symbol=TEST")
            assert r.status_code == 200

    def test_proxy_failure(self, client):
        with patch("main.obb_client") as mock_obb:
            mock_obb.get = AsyncMock(return_value=None)
            r = client.get("/market/historical?symbol=TEST")
            assert r.status_code == 502


# =========================================================================== #
#  Health endpoint
# =========================================================================== #


class TestHealthEndpoint:
    def test_healthy(self, client):
        with patch("main.obb_client") as mock_obb:
            mock_obb.health = AsyncMock(return_value=True)
            mock_obb.base_url = "https://127.0.0.1:6902"
            r = client.get("/health")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "ok"
            assert body["database"] is True
            assert body["openbb_api"] is True

    def test_degraded_db(self, client):
        with patch("main.check_db", return_value=False):
            with patch("main.obb_client") as mock_obb:
                mock_obb.health = AsyncMock(return_value=True)
                mock_obb.base_url = "https://127.0.0.1:6902"
                r = client.get("/health")
                assert r.json()["status"] == "degraded"
                assert r.json()["database"] is False


# =========================================================================== #
#  Stock Analysis endpoints  (/stock/*)
# =========================================================================== #

# ---------------------------------------------------------------------------
# Synthetic DataFrames returned by obb_client.get_df mocks
# ---------------------------------------------------------------------------

def _profile_df():
    return pd.DataFrame([{
        "symbol": "CLS", "name": "Celestica Inc", "sector": "Technology",
        "industry": "Electronic Components", "description": "A contract mfg company.",
        "ceo": "Rob Mionis", "full_time_employees": 27000, "website": "https://celestica.com",
    }])


def _quote_df():
    return pd.DataFrame([{
        "symbol": "CLS", "last_price": 80.0, "change_percent": 0.015,
        "volume": 1_200_000, "market_cap": 9_000_000_000,
    }])


def _peers_df():
    return pd.DataFrame([{"symbol": s} for s in ["JBL", "FLEX", "CLS"]])


def _income_df():
    rows = []
    for yr in [2023, 2022, 2021]:
        rows.append({
            "period_ending": f"{yr}-12-31",
            "revenue": 7_000_000_000 + (2023 - yr) * 500_000_000,
            "gross_profit": 700_000_000,
            "operating_income": 300_000_000,
            "net_income": 200_000_000,
            "basic_earnings_per_share": 2.5,
        })
    return pd.DataFrame(rows)


def _balance_df():
    rows = []
    for yr in [2023, 2022, 2021]:
        rows.append({
            "period_ending": f"{yr}-12-31",
            "total_debt": 1_000_000_000,
            "total_equity": 2_000_000_000,
        })
    return pd.DataFrame(rows)


def _cash_df():
    rows = []
    for yr in [2023, 2022, 2021]:
        rows.append({
            "period_ending": f"{yr}-12-31",
            "free_cash_flow": 180_000_000 + (2023 - yr) * 10_000_000,
        })
    return pd.DataFrame(rows)


def _ratios_df():
    return pd.DataFrame([{
        "gross_profit_margin": 0.10,
        "operating_profit_margin": 0.043,
        "net_profit_margin": 0.028,
        "return_on_invested_capital": 0.095,
        "current_ratio": 1.4,
        "debt_to_equity": 0.5,
        "price_earnings_ratio": 14.0,
        "enterprise_value_multiple": 8.5,
        "price_to_free_cash_flow": 12.0,
        "price_to_sales": 0.4,
        "earnings_yield": 0.071,
    }])


def _price_hist_df():
    """90-day daily OHLCV for CLS and SPY."""
    import random as _random
    rng = _random.Random(42)
    rows = []
    from datetime import date as _date, timedelta as _td
    end = _date(2025, 12, 31)
    for sym, start_p in [("CLS", 80.0), ("SPY", 500.0)]:
        p = start_p
        for d in range(90):
            dt = end - _td(days=89 - d)
            if dt.weekday() >= 5:
                continue
            chg = rng.uniform(-0.02, 0.02)
            close = round(max(1.0, p * (1 + chg)), 4)
            rows.append({
                "symbol": sym,
                "date":   dt.isoformat(),
                "open":   round(p, 4),
                "high":   round(max(p, close) * 1.005, 4),
                "low":    round(min(p, close) * 0.995, 4),
                "close":  close,
                "volume": rng.randint(500_000, 5_000_000),
            })
            p = close
    return pd.DataFrame(rows)


def _universe_hist_df():
    """90-day daily history for a small peer universe."""
    import random as _random
    rng = _random.Random(7)
    rows = []
    from datetime import date as _date, timedelta as _td
    end = _date(2025, 12, 31)
    for sym, start_p in [("CLS", 80.0), ("JBL", 120.0), ("FLEX", 35.0), ("XLK", 230.0), ("SPY", 500.0)]:
        p = start_p
        for d in range(90):
            dt = end - _td(days=89 - d)
            if dt.weekday() >= 5:
                continue
            chg = rng.uniform(-0.02, 0.02)
            close = round(max(1.0, p * (1 + chg)), 4)
            rows.append({
                "symbol": sym,
                "date":   dt.isoformat(),
                "close":  close,
                "open":   round(p, 4),
                "high":   round(max(p, close) * 1.005, 4),
                "low":    round(min(p, close) * 0.995, 4),
                "volume": rng.randint(100_000, 2_000_000),
            })
            p = close
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Context manager: patch obb_client.get_df to return canned DataFrames
# and clear the in-process cache before each test call.
# ---------------------------------------------------------------------------

def _obb_df_side_effect(path, **params):
    """Return appropriate synthetic DataFrame for each OpenBB API path."""
    if "profile" in path:
        return _profile_df()
    if "quote" in path:
        return _quote_df()
    if "peers" in path or "compare" in path:
        return _peers_df()
    if "income" in path:
        return _income_df()
    if "balance" in path:
        return _balance_df()
    if "cash" in path:
        return _cash_df()
    if "ratios" in path:
        return _ratios_df()
    if "historical" in path:
        syms = str(params.get("symbol", ""))
        if "," in syms and len(syms.split(",")) > 2:
            return _universe_hist_df()
        return _price_hist_df()
    return pd.DataFrame()


# =========================================================================== #
#  TestStockContextEndpoint
# =========================================================================== #


class TestStockContextEndpoint:
    def test_returns_symbol_row(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/context?symbol=CLS")
            assert r.status_code == 200
            data = r.json()
            assert len(data) == 1
            assert data[0]["symbol"] == "CLS"

    def test_returns_sector(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/context?symbol=CLS")
            assert r.status_code == 200
            assert r.json()[0]["sector"] == "Technology"

    def test_obb_unavailable_still_returns_row(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(return_value=pd.DataFrame())
            r = client.get("/stock/context?symbol=CLS")
            assert r.status_code == 200
            data = r.json()
            assert len(data) == 1
            assert data[0]["symbol"] == "CLS"


# =========================================================================== #
#  TestStockProfileEndpoint
# =========================================================================== #


class TestStockProfileEndpoint:
    EXPECTED_KEYS = {"symbol", "name", "sector", "industry", "market_cap", "last_price",
                     "change_pct", "volume", "peer_count", "peers", "sector_etfs",
                     "ceo", "employees", "website", "description"}

    def test_returns_profile_row(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/profile?symbol=CLS")
            assert r.status_code == 200
            data = r.json()
            assert len(data) == 1

    def test_all_expected_keys_present(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/profile?symbol=CLS")
            row = r.json()[0]
            assert self.EXPECTED_KEYS.issubset(set(row.keys()))

    def test_obb_unavailable_still_returns_row(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(return_value=pd.DataFrame())
            r = client.get("/stock/profile?symbol=CLS")
            assert r.status_code == 200
            data = r.json()
            assert len(data) == 1
            assert data[0]["symbol"] == "CLS"

    def test_peers_and_sector_etfs_are_strings(self, client):
        """Lists are serialised as comma-separated strings for table display."""
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/profile?symbol=CLS")
            row = r.json()[0]
            assert isinstance(row["peers"], str)
            assert isinstance(row["sector_etfs"], str)


# =========================================================================== #
#  TestStockFundamentalsEndpoint
# =========================================================================== #

_FUNDAMENTAL_METRICS = {
    "Revenue Growth (last)", "EPS Growth (last)", "FCF Growth (last)",
    "Gross Margin (last)", "Operating Margin (last)", "Net Margin (last)",
    "ROIC (last)", "Current Ratio (last)", "Debt/Equity (last)",
}


class TestStockFundamentalsEndpoint:
    def test_returns_metric_value_rows(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/fundamentals?symbol=CLS")
            assert r.status_code == 200
            data = r.json()
            assert isinstance(data, list)
            assert len(data) > 0

    def test_each_row_has_metric_and_value(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/fundamentals?symbol=CLS")
            for row in r.json():
                assert "metric" in row
                assert "value" in row

    def test_all_expected_metrics_present(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/fundamentals?symbol=CLS")
            metrics = {row["metric"] for row in r.json()}
            assert _FUNDAMENTAL_METRICS.issubset(metrics)

    def test_obb_unavailable_returns_dash_values(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(return_value=pd.DataFrame())
            r = client.get("/stock/fundamentals?symbol=CLS")
            assert r.status_code == 200
            for row in r.json():
                assert row["value"] == "-"


# =========================================================================== #
#  TestStockTechnicalsEndpoint
# =========================================================================== #

_TECHNICAL_INDICATORS = {"RSI(14)", "ADX(14)", "ATR(14)", "OBV", "MACD_Signal", "BB_Pct"}


class TestStockTechnicalsEndpoint:
    def test_returns_indicator_value_rows(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/technicals?symbol=CLS")
            assert r.status_code == 200
            data = r.json()
            assert isinstance(data, list)
            assert len(data) > 0

    def test_each_row_has_indicator_and_value(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/technicals?symbol=CLS")
            for row in r.json():
                assert "indicator" in row
                assert "value" in row

    def test_all_expected_indicators_present(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/technicals?symbol=CLS")
            indicators = {row["indicator"] for row in r.json()}
            assert _TECHNICAL_INDICATORS.issubset(indicators)

    def test_obb_unavailable_returns_dash_values(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(return_value=pd.DataFrame())
            r = client.get("/stock/technicals?symbol=CLS")
            assert r.status_code == 200
            for row in r.json():
                assert row["value"] == "-"


# =========================================================================== #
#  TestStockValuationEndpoint
# =========================================================================== #


class TestStockValuationEndpoint:
    _EXPECTED_METRICS = {
        "Price (last)", "EPS (last)", "P/E (last)", "EV/EBITDA (last)",
        "P/FCF (last)", "P/S (last)", "Earnings Yield (last)",
    }

    def test_returns_metric_value_rows(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/valuation?symbol=CLS")
            assert r.status_code == 200
            data = r.json()
            assert len(data) > 0

    def test_each_row_has_metric_and_value(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/valuation?symbol=CLS")
            for row in r.json():
                assert "metric" in row
                assert "value" in row

    def test_expected_valuation_metrics_present(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/valuation?symbol=CLS")
            metrics = {row["metric"] for row in r.json()}
            assert self._EXPECTED_METRICS.issubset(metrics)


# =========================================================================== #
#  TestStockRiskEndpoint
# =========================================================================== #

_RISK_METRICS = {
    "Sharpe", "Sortino", "Jensen Alpha", "Beta",
    "VaR 95%", "CVaR 95%", "Max Drawdown", "Ulcer Index",
}


class TestStockRiskEndpoint:
    def test_returns_metric_value_rows(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/risk?symbol=CLS&benchmark=SPY")
            assert r.status_code == 200
            data = r.json()
            assert len(data) > 0

    def test_all_risk_metrics_present(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/risk?symbol=CLS&benchmark=SPY")
            metrics = {row["metric"] for row in r.json()}
            assert _RISK_METRICS.issubset(metrics)

    def test_obb_unavailable_returns_dash_values(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(return_value=pd.DataFrame())
            r = client.get("/stock/risk?symbol=CLS")
            assert r.status_code == 200
            for row in r.json():
                assert row["value"] == "-"


# =========================================================================== #
#  TestStockRelativeEndpoint
# =========================================================================== #


class TestStockRelativeEndpoint:
    _EXPECTED_COLS = {"symbol", "Annual Return", "Volatility", "Sharpe",
                      "VaR 95%", "CVaR 95%", "Max Drawdown"}

    def test_returns_table_rows(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/relative?symbol=CLS&benchmark=SPY")
            assert r.status_code == 200
            data = r.json()
            assert isinstance(data, list)
            assert len(data) > 0

    def test_each_row_has_expected_cols(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/relative?symbol=CLS&benchmark=SPY")
            for row in r.json():
                assert self._EXPECTED_COLS.issubset(set(row.keys()))

    def test_returns_empty_list_when_no_history(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(return_value=pd.DataFrame())
            r = client.get("/stock/relative?symbol=CLS")
            assert r.status_code == 200
            assert r.json() == []

    def test_symbol_col_present_in_each_row(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/relative?symbol=CLS")
            for row in r.json():
                assert "symbol" in row


# =========================================================================== #
#  TestStockDecisionEndpoint
# =========================================================================== #

_DECISION_KEYS = {
    "symbol", "business_quality", "fundamentals", "technicals",
    "valuation", "risk_fit", "relative_peer_score", "total_score", "decision",
}

_VALID_DECISIONS = {"Strong Buy", "Buy", "Hold/Watch", "Avoid/Sell", "Pending"}


class TestStockDecisionEndpoint:
    def test_returns_single_row(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/decision?symbol=CLS")
            assert r.status_code == 200
            data = r.json()
            assert len(data) == 1

    def test_all_decision_keys_present(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/decision?symbol=CLS")
            row = r.json()[0]
            assert _DECISION_KEYS.issubset(set(row.keys()))

    def test_symbol_in_result(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/decision?symbol=CLS")
            assert r.json()[0]["symbol"] == "CLS"

    def test_decision_label_valid(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/decision?symbol=CLS")
            assert r.json()[0]["decision"] in _VALID_DECISIONS

    def test_obb_unavailable_returns_valid_decision(self, client):
        """Even when all OpenBB calls return empty DataFrames, the endpoint returns
        a valid decision label (fallback defaults produce a numeric score).
        """
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(return_value=pd.DataFrame())
            r = client.get("/stock/decision?symbol=CLS")
            assert r.status_code == 200
            decision = r.json()[0]["decision"]
            assert decision in {"Strong Buy", "Buy", "Hold/Watch", "Avoid/Sell", "Pending"}

    def test_scores_in_valid_range(self, client):
        with patch("main._stock_cache", {}), patch("main.obb_client") as mock_obb:
            mock_obb.get_df = AsyncMock(side_effect=_obb_df_side_effect)
            r = client.get("/stock/decision?symbol=CLS")
            row = r.json()[0]
            for dim in ("business_quality", "fundamentals", "technicals", "valuation", "risk_fit"):
                score = row[dim]
                assert score is None or (0.0 <= score <= 5.0), f"{dim} = {score} out of [0,5]"
