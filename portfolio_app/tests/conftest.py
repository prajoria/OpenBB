"""
Shared pytest fixtures — built from generated mock data.

All data is synthetic (anonymized symbols, accounts, owners, values).
Fixtures are auto-generated on first run if JSON files are missing.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Make portfolio_app source importable
_portfolio_app_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_portfolio_app_dir / "src"))
sys.path.insert(0, str(_portfolio_app_dir))

from tests.mock_data_generator import (  # noqa: E402
    load_account_owner,
    load_equity_historical,
    load_espp,
    load_positions,
)


# --------------------------------------------------------------------------- #
#  Core DataFrames built from generated fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def positions_df() -> pd.DataFrame:
    """All Position lots (both snapshots).  Same shape as ``get_positions_df()``."""
    return pd.DataFrame(load_positions())


@pytest.fixture
def latest_positions_df(positions_df) -> pd.DataFrame:
    """Only the latest snapshot per account — mirrors default ``get_positions_df()``."""
    max_snap = (
        positions_df.groupby("account_name")["snapshot_date"]
        .transform("max")
    )
    return positions_df[positions_df["snapshot_date"] == max_snap].reset_index(drop=True)


@pytest.fixture
def snapshots_df(positions_df) -> pd.DataFrame:
    """Multi-snapshot data for trend tests (columns match ``get_all_snapshots_df()``)."""
    cols = [
        "account_name", "symbol", "quantity",
        "cost_basis_total", "current_value", "total_gain_loss",
        "snapshot_date",
    ]
    return positions_df[cols].reset_index(drop=True)


@pytest.fixture
def espp_df() -> pd.DataFrame:
    """ESPP purchase fixture."""
    return pd.DataFrame(load_espp())


@pytest.fixture
def equity_hist_df() -> pd.DataFrame:
    """Equity historical daily OHLCV fixture."""
    return pd.DataFrame(load_equity_historical())


@pytest.fixture
def account_owner_data() -> list[dict]:
    """Raw Account_Owner rows (for dropdown / filter helpers)."""
    return load_account_owner()


@pytest.fixture
def empty_df() -> pd.DataFrame:
    """Empty DataFrame with standard position columns."""
    return pd.DataFrame(columns=[
        "symbol", "description", "account_name", "owner",
        "quantity", "avg_cost_basis", "cost_basis_total",
        "current_value", "total_gain_loss", "pct_gain_loss",
        "term", "acquired", "share_source",
        "grant_date", "transfer_avail_date", "snapshot_date",
    ])


# --------------------------------------------------------------------------- #
#  Derived lookup helpers (available in tests for assertions)
# --------------------------------------------------------------------------- #

@pytest.fixture
def all_symbols(positions_df) -> set[str]:
    return set(positions_df["symbol"].unique())


@pytest.fixture
def all_accounts(positions_df) -> set[str]:
    return set(positions_df["account_name"].unique())


@pytest.fixture
def all_owners(positions_df) -> set[str]:
    return set(positions_df["owner"].unique())
