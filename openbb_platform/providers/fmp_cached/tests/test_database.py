"""Unit tests for synchronous MySQL database utilities."""

import pytest
import json
import os
from unittest.mock import patch, mock_open, MagicMock
from openbb_fmp_cached.utils.database import (
    DatabaseConfig,
    ConnectionPool,
    get_connection_pool,
    execute_query,
    execute_many,
    init_database
)

class TestDatabaseConfig:
    """Test database configuration management."""

    def test_missing_credentials_fail_fast(self):
        """No settings + no env vars must raise (no hardcoded credential defaults)."""
        with patch('os.path.exists', return_value=False), \
             patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError):
                DatabaseConfig()

    def test_credentials_from_env(self):
        """Credentials are sourced from DB_USER/DB_PASSWORD env vars."""
        env = {"DB_USER": "tester", "DB_PASSWORD": "secret"}
        with patch('os.path.exists', return_value=False), \
             patch.dict(os.environ, env, clear=True):
            config = DatabaseConfig()
            assert config.config['host'] == 'localhost'
            assert config.config['port'] == 3306
            assert config.config['user'] == 'tester'

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
