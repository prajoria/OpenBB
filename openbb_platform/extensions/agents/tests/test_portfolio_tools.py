"""Tests for openbb_agents.tools.portfolio_tools.

Unit tests inject a fake fetch/profile callable so no MySQL or network is
needed. The single integration test (marked) hits the real portfolio basket via
fmp_cached / MySQL.
"""

import sys
from pathlib import Path

import pytest

# Ensure the extension package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _fake_basket():
    """Minimal sanitized-basket rows (as data.get_portfolio_basket_df would return)."""
    import pandas as pd

    return pd.DataFrame(
        [
            {"symbol": "MSFT", "total_quantity": 10, "total_cost_basis": 2000.0,
             "total_current_value": 4000.0, "pct_return": 100.0,
             "portfolio_weight_pct": 40.0},
            {"symbol": "AAPL", "total_quantity": 20, "total_cost_basis": 3000.0,
             "total_current_value": 3000.0, "pct_return": 0.0,
             "portfolio_weight_pct": 30.0},
            {"symbol": "JPM", "total_quantity": 5, "total_cost_basis": 1500.0,
             "total_current_value": 3000.0, "pct_return": 100.0,
             "portfolio_weight_pct": 30.0},
        ]
    )


def _fake_profile(symbol: str) -> dict:
    sectors = {"MSFT": "Technology", "AAPL": "Technology", "JPM": "Financial Services"}
    return {"symbol": symbol, "sector": sectors.get(symbol, "Unknown")}


class TestGetPositions:
    def test_returns_list_of_dicts_with_expected_keys(self):
        from openbb_agents.tools.portfolio_tools import get_positions

        rows = get_positions(_fetch=_fake_basket)
        assert isinstance(rows, list)
        assert len(rows) == 3
        first = rows[0]
        for key in ("symbol", "shares", "cost_basis", "current_value",
                    "unrealized_gain_pct", "weight_pct"):
            assert key in first, f"missing key: {key}"

    def test_values_mapped_from_basket_columns(self):
        from openbb_agents.tools.portfolio_tools import get_positions

        rows = get_positions(_fetch=_fake_basket)
        msft = next(r for r in rows if r["symbol"] == "MSFT")
        assert msft["shares"] == 10
        assert msft["current_value"] == 4000.0
        assert msft["unrealized_gain_pct"] == 100.0
        assert msft["weight_pct"] == 40.0

    def test_empty_basket_returns_empty_list(self):
        import pandas as pd
        from openbb_agents.tools.portfolio_tools import get_positions

        rows = get_positions(_fetch=lambda: pd.DataFrame())
        assert rows == []


class TestGetSectorExposure:
    def test_aggregates_market_value_by_sector(self):
        from openbb_agents.tools.portfolio_tools import get_sector_exposure

        rows = get_sector_exposure(_fetch=_fake_basket, _profile=_fake_profile)
        by_sector = {r["sector"]: r for r in rows}
        # Technology = MSFT(4000) + AAPL(3000) = 7000; Financial = 3000; total = 10000
        assert "Technology" in by_sector
        assert by_sector["Technology"]["market_value"] == 7000.0
        assert by_sector["Financial Services"]["market_value"] == 3000.0

    def test_weights_sum_to_100(self):
        from openbb_agents.tools.portfolio_tools import get_sector_exposure

        rows = get_sector_exposure(_fetch=_fake_basket, _profile=_fake_profile)
        total = sum(r["weight_pct"] for r in rows)
        assert total == pytest.approx(100.0, abs=0.01)


@pytest.mark.integration
class TestPortfolioToolsIntegration:
    def test_get_positions_live_basket(self):
        from openbb_agents.tools.portfolio_tools import get_positions

        rows = get_positions()
        assert isinstance(rows, list)
        if rows:  # DB may be empty in some envs; only assert shape when populated
            assert "symbol" in rows[0]
            assert "weight_pct" in rows[0]
