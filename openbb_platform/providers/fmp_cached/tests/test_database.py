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

    def test_default_config(self):
        """Test default configuration when no settings file exists."""
        with patch('os.path.exists', return_value=False), \
             patch.dict(os.environ, {}, clear=True):
            config = DatabaseConfig()
            assert config.config['host'] == 'localhost'
            assert config.config['port'] == 3306
            assert config.config['user'] == 'fmp_user'

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
