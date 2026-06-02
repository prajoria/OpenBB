"""Pytest configuration for FMP Cached provider tests."""

import pytest
import asyncio
from typing import Generator
from unittest.mock import MagicMock


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "slow: Slow running tests")
    config.addinivalue_line("markers", "database: Tests requiring database")
    config.addinivalue_line("markers", "api: Tests requiring API access")


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers automatically."""
    for item in items:
        # Add unit marker to tests not marked otherwise
        if not any(mark.name in ["integration", "slow", "database", "api"] for mark in item.iter_markers()):
            item.add_marker(pytest.mark.unit)
        
        # Add slow marker to performance tests
        if "performance" in item.nodeid or "scalability" in item.nodeid:
            item.add_marker(pytest.mark.slow)
        
        # Add database marker to database-related tests
        if "database" in item.nodeid or "cache" in item.nodeid:
            item.add_marker(pytest.mark.database)
        
        # Add API marker to API-related tests
        if "fmp" in item.nodeid or "api" in item.nodeid:
            item.add_marker(pytest.mark.api)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_database():
    """Provide a mock database connection for testing."""
    mock_db = MagicMock()
    mock_db.execute.return_value = None
    mock_db.fetchall.return_value = []
    mock_db.fetchone.return_value = None
    return mock_db


@pytest.fixture
def mock_credentials():
    """Provide mock FMP API credentials for testing."""
    return {"fmp_api_key": "test_api_key_123456"}


@pytest.fixture
def sample_cache_data():
    """Provide sample cached data for testing."""
    return [
        {
            "symbol": "AAPL",
            "date": "2024-01-02",
            "open": 184.0,
            "high": 186.0,
            "low": 183.0,
            "close": 185.0,
            "volume": 45000000,
            "change": 1.0,
            "changePercent": 0.54,
            "vwap": 184.5
        },
        {
            "symbol": "AAPL", 
            "date": "2024-01-03",
            "open": 185.0,
            "high": 187.0,
            "low": 184.0,
            "close": 186.0,
            "volume": 42000000,
            "change": 1.0,
            "changePercent": 0.54,
            "vwap": 185.5
        }
    ]


@pytest.fixture
def sample_fmp_response():
    """Provide sample FMP API response data for testing."""
    return [
        {
            "date": "2024-01-02",
            "open": 184.0,
            "high": 186.0,
            "low": 183.0,
            "close": 185.0,
            "adjClose": 185.0,
            "volume": 45000000,
            "unadjustedVolume": 45000000,
            "change": 1.0,
            "changePercent": 0.54,
            "vwap": 184.5,
            "label": "January 02, 24",
            "changeOverTime": 0.0054
        }
    ]


@pytest.fixture
def cleanup_database():
    """Cleanup fixture that runs after database tests."""
    yield  # Test runs here
    # Cleanup code would go here if needed


def pytest_runtest_setup(item):
    """Setup function that runs before each test."""
    # Skip slow tests unless specifically requested
    if "slow" in [mark.name for mark in item.iter_markers()]:
        if not item.config.getoption("--runslow", default=False):
            pytest.skip("need --runslow option to run slow tests")


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--runslow",
        action="store_true",
        default=False,
        help="run slow tests"
    )
    parser.addoption(
        "--runintegration",
        action="store_true", 
        default=False,
        help="run integration tests"
    )
    parser.addoption(
        "--database-url",
        action="store",
        default="sqlite:///:memory:",
        help="database URL for testing"
    )


# Mock for jupyter environment check removed - no longer needed


@pytest.fixture(scope="session")
def setup_test_database():
    """Set up test database once for the entire test session."""
    import os
    from openbb_fmp_cached.utils.database import init_database, execute_query
    
    # Force test database
    os.environ['FMP_CACHE_TEST_MODE'] = 'true'
    os.environ['MYSQL_DATABASE'] = 'openbb_fmp_cache_test'
    
    # Initialize database and tables
    init_database()
    
    yield
    
    # Cleanup after all tests (optional - comment out if you want to inspect data)
    # try:
    #     execute_query("DROP DATABASE IF EXISTS openbb_fmp_cache_test")
    # except:
    #     pass