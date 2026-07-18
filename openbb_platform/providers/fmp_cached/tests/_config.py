"""Test configuration for FMP Cached provider tests."""

import os
import pytest
from pathlib import Path

# Test markers
pytest_markers = [
    "unit: Unit tests that don't require external dependencies",
    "integration: Integration tests that require database connection", 
    "slow: Slow-running tests",
    "database: Tests that require database setup",
    "api: Tests that make actual API calls"
]

# Test directories
TEST_DIR = Path(__file__).parent
PROVIDER_DIR = TEST_DIR.parent
CACHE_DIR = TEST_DIR / "cache"

# Ensure cache directory exists
CACHE_DIR.mkdir(exist_ok=True)

# Test database configuration (for integration tests)
TEST_DB_CONFIG = {
    "host": os.getenv("TEST_DB_HOST", "localhost"),
    "port": int(os.getenv("TEST_DB_PORT", "3306")),
    "user": os.getenv("TEST_DB_USER", "test_user"),
    "password": os.getenv("TEST_DB_PASSWORD", "test_password"),
    "database": os.getenv("TEST_DB_NAME", "test_openbb_fmp_cache"),
}

# Mock credentials for testing
TEST_CREDENTIALS = {
    "fmp_cached_api_key": "test_api_key_123456",
    "fmp_api_key": "test_api_key_123456"
}

# Test data samples
SAMPLE_SYMBOLS = ["AAPL", "GOOGL", "MSFT", "TSLA", "AMZN"]
SAMPLE_DATE_RANGES = [
    ("2024-01-01", "2024-01-05"),
    ("2024-01-15", "2024-01-31"),
    ("2023-12-01", "2023-12-31"),
]
SAMPLE_INTERVALS = ["1d", "1h", "5m"]
SAMPLE_ADJUSTMENTS = ["splits_only", "splits_and_dividends", "unadjusted"]

# Performance test thresholds
PERFORMANCE_THRESHOLDS = {
    "cache_hit_response_time_ms": 100,    # Cache hits should be < 100ms
    "api_call_timeout_s": 30,             # API calls should complete < 30s
    "gap_detection_time_ms": 50,          # Gap detection should be < 50ms
    "max_cache_size_mb": 1000,            # Cache shouldn't exceed 1GB
}

# Test fixtures configuration
FIXTURE_CONFIG = {
    "use_real_database": os.getenv("USE_REAL_DATABASE", "false").lower() == "true",
    "use_real_api": os.getenv("USE_REAL_API", "false").lower() == "true", 
    "cleanup_after_tests": os.getenv("CLEANUP_AFTER_TESTS", "true").lower() == "true",
}