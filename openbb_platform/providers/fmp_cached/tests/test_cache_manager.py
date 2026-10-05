"""DatabaseManager hit, miss, and failure-state contracts."""

from unittest.mock import patch

from openbb_fmp_cached.utils.cache_manager import DatabaseManager


@patch(
    "openbb_fmp_cached.utils.cache_manager.get_table_for_endpoint",
    return_value="equity_historical",
)
@patch("openbb_fmp_cached.utils.cache_manager.execute_query")
def test_cache_hit_and_miss_update_operator_stats(mock_query, _mock_table):
    """Read outcomes remain visible without changing schemas."""
    manager = DatabaseManager()
    mock_query.return_value = [{"symbol": "SYNTH", "close": 100.0}]
    assert manager.get_stored_data("EquityHistorical", symbol="SYNTH")
    assert manager.stats == {"hits": 1, "misses": 0, "stores": 0, "errors": 0}

    mock_query.return_value = []
    assert manager.get_stored_data("EquityHistorical", symbol="MISSING") is None
    assert manager.stats == {"hits": 1, "misses": 1, "stores": 0, "errors": 0}


@patch(
    "openbb_fmp_cached.utils.cache_manager.get_table_for_endpoint",
    return_value="equity_historical",
)
@patch(
    "openbb_fmp_cached.utils.cache_manager.execute_query",
    side_effect=RuntimeError("synthetic read failure"),
)
def test_failed_read_is_visible_in_stats(_mock_query, _mock_table):
    """A failed read is not reported as a cache miss."""
    manager = DatabaseManager()
    assert manager.get_stored_data("EquityHistorical", symbol="SYNTH") is None
    assert manager.stats["errors"] == 1
    assert manager.stats["misses"] == 0


@patch(
    "openbb_fmp_cached.utils.cache_manager.get_table_for_endpoint",
    return_value="equity_historical",
)
@patch(
    "openbb_fmp_cached.utils.cache_manager.execute_query",
    side_effect=RuntimeError("synthetic write failure"),
)
def test_failed_write_is_visible_in_stats(_mock_query, _mock_table):
    """Write failures remain distinct from zero-row stores."""
    manager = DatabaseManager()
    assert (
        manager.store_data(
            "EquityHistorical",
            [{"symbol": "SYNTH", "close": 100.0}],
        )
        is False
    )
    assert manager.stats["errors"] == 1
    assert manager.stats["stores"] == 0
