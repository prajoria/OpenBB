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


def _snapshots_df(*a, **kw):
    cols = [
        "account_name", "symbol", "quantity",
        "cost_basis_total", "current_value", "total_gain_loss",
        "snapshot_date",
    ]
    return pd.DataFrame(_POSITIONS)[cols]


def _espp_df(*a, **kw):
    return pd.DataFrame(_ESPP)


def _equity_df(*a, **kw):
    return pd.DataFrame(_EQUITY_HIST)


def _check_db():
    return True


def _distinct_symbols():
    return [{"label": s, "value": s} for s in _SYMBOLS]


def _distinct_accounts():
    return [{"label": a, "value": a} for a in _ACCOUNTS]


def _distinct_owners():
    return [{"label": o, "value": o} for o in _OWNERS]


DATA_PATCHES = {
    "main.get_positions_df": _positions_df,
    "main.get_all_snapshots_df": _snapshots_df,
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
    patches = [patch(k, side_effect=v) for k, v in DATA_PATCHES.items()]
    mocks = [p.start() for p in patches]
    yield mocks
    for p in patches:
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
        assert len(r.json()) == len(_ACCOUNTS)

    def test_get_owners(self, client):
        r = client.get("/get_owners")
        assert r.status_code == 200
        assert len(r.json()) == len(_OWNERS)


# =========================================================================== #
#  Portfolio endpoints
# =========================================================================== #


class TestPositionsEndpoint:
    def test_returns_list(self, client):
        r = client.get("/portfolio/positions")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # Patched get_positions_df returns ALL 160 rows (both snapshots);
        # endpoint sorts but doesn't filter by snapshot itself.
        assert len(data) == len(_POSITIONS)

    def test_sorted_by_value(self, client):
        r = client.get("/portfolio/positions")
        values = [row["current_value"] for row in r.json()]
        assert values == sorted(values, reverse=True)

    def test_filter_by_account(self, client):
        r = client.get(f"/portfolio/positions?account={_ONE_ACCOUNT}")
        data = r.json()
        assert len(data) > 0
        assert all(row["account_name"] == _ONE_ACCOUNT for row in data)

    def test_filter_by_owner(self, client):
        r = client.get(f"/portfolio/positions?owner={_ONE_OWNER}")
        data = r.json()
        assert len(data) > 0
        assert all(row["owner"] == _ONE_OWNER for row in data)

    def test_no_match_returns_empty(self, client):
        r = client.get("/portfolio/positions?account=NonExistent9999")
        assert r.json() == []


class TestSummaryEndpoint:
    def test_returns_aggregated(self, client):
        r = client.get("/portfolio/summary")
        assert r.status_code == 200
        data = r.json()
        symbols = {row["symbol"] for row in data}
        # Aggregated by symbol — fewer rows than raw positions
        assert len(symbols) > 0
        assert len(data) <= len(_POSITIONS)

    def test_has_pct_return(self, client):
        r = client.get("/portfolio/summary")
        for row in r.json():
            assert "pct_return" in row
            assert isinstance(row["pct_return"], (int, float))

    def test_filter_by_owner(self, client):
        r = client.get(f"/portfolio/summary?owner={_ONE_OWNER}")
        data = r.json()
        assert len(data) > 0

    def test_sorted_by_value_desc(self, client):
        r = client.get("/portfolio/summary")
        values = [row["total_current_value"] for row in r.json()]
        assert values == sorted(values, reverse=True)


class TestAllocationEndpoint:
    def test_returns_by_account(self, client):
        r = client.get("/portfolio/allocation")
        assert r.status_code == 200
        data = r.json()
        accounts = {row["account_name"] for row in data}
        assert len(accounts) > 0

    def test_has_num_symbols(self, client):
        r = client.get("/portfolio/allocation")
        for row in r.json():
            assert "num_symbols" in row
            assert row["num_symbols"] >= 1

    def test_filter_by_owner(self, client):
        r = client.get(f"/portfolio/allocation?owner={_ONE_OWNER}")
        data = r.json()
        assert len(data) > 0
        assert all(row["owner"] == _ONE_OWNER for row in data)


class TestCostBasisEndpoint:
    def test_returns_lots(self, client):
        r = client.get("/portfolio/cost_basis")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == len(_POSITIONS)  # one row per lot

    def test_filter_by_symbol(self, client):
        r = client.get(f"/portfolio/cost_basis?symbol={_ONE_SYMBOL}")
        data = r.json()
        assert len(data) > 0
        assert all(row["symbol"] == _ONE_SYMBOL for row in data)

    def test_filter_by_account(self, client):
        r = client.get(f"/portfolio/cost_basis?account={_ONE_ACCOUNT}")
        data = r.json()
        assert len(data) > 0
        assert all(row["account_name"] == _ONE_ACCOUNT for row in data)

    def test_sorted_by_symbol_acquired(self, client):
        r = client.get("/portfolio/cost_basis")
        data = r.json()
        keys = [(row["symbol"], row.get("acquired") or "") for row in data]
        assert keys == sorted(keys)


class TestTaxSummaryEndpoint:
    def test_returns_grouped(self, client):
        r = client.get("/portfolio/tax_summary")
        assert r.status_code == 200
        data = r.json()
        assert len(data) > 0
        for row in data:
            assert "term" in row
            assert row["term"].strip() != ""

    def test_has_pct_return(self, client):
        r = client.get("/portfolio/tax_summary")
        for row in r.json():
            assert "pct_return" in row

    def test_filter_by_owner(self, client):
        r = client.get(f"/portfolio/tax_summary?owner={_ONE_OWNER}")
        data = r.json()
        assert all(row["owner"] == _ONE_OWNER for row in data)


class TestPerformanceEndpoint:
    def test_sorted_by_return(self, client):
        r = client.get("/portfolio/performance")
        assert r.status_code == 200
        data = r.json()
        pcts = [row["pct_return"] for row in data]
        assert pcts == sorted(pcts, reverse=True)

    def test_excludes_zero_cost(self, client):
        r = client.get("/portfolio/performance")
        data = r.json()
        assert all(row["total_cost_basis"] > 0 for row in data)


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
            assert "lots" in row
            assert "total_current_value" in row
            assert row["lots"] > 0


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
            mock_obb.base_url = "https://127.0.0.1:6901"
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
                mock_obb.base_url = "https://127.0.0.1:6901"
                r = client.get("/health")
                assert r.json()["status"] == "degraded"
                assert r.json()["database"] is False
