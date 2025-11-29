"""Simple synchronous MySQL database utilities for FMP cached provider."""

import os
from typing import Any, Dict, Optional
import json
import logging
from contextlib import contextmanager
import pymysql.cursors

logger = logging.getLogger(__name__)


class DatabaseConfig:
    """Database configuration manager."""
    
    def __init__(self):
        """Initialize database configuration from user settings."""
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load database configuration from OpenBB user settings, with environment variable fallback."""
        
        # Check if we're in test mode
        is_test_mode = os.getenv("FMP_CACHE_TEST_MODE", "false").lower() == "true"
        test_database = "openbb_fmp_cache_test" if is_test_mode else "openbb_fmp_cache"
        
        default_config = {
            "host": "localhost",
            "port": 3306,
            "user": "fmp_user",
            "password": "fmp_password",
            "database": test_database,
            "charset": "utf8mb4",
            "test_mode": is_test_mode
        }
        
        # First try OpenBB user settings (preferred)
        settings_path = os.path.expanduser("~/.openbb_platform/user_settings.json")
        
        try:
            if os.path.exists(settings_path):
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                    credentials = settings.get("credentials", {})
                    
                    # Check if MySQL credentials are configured (try multiple naming patterns)
                    mysql_keys = [
                        "mysql_host", "mysql_user", "mysql_password", "mysql_database",
                        "db_host", "db_user", "db_password", "db_database",
                        "database_host", "database_user", "database_password", "database_name"
                    ]
                    
                    if any(key in credentials for key in mysql_keys):
                        # Try multiple naming patterns for each field
                        host = (credentials.get("mysql_host") or 
                               credentials.get("db_host") or 
                               credentials.get("database_host") or 
                               default_config["host"])
                        
                        port = int(credentials.get("mysql_port") or 
                                  credentials.get("db_port") or 
                                  credentials.get("database_port") or 
                                  default_config["port"])
                        
                        user = (credentials.get("mysql_user") or 
                               credentials.get("db_user") or 
                               credentials.get("database_user") or 
                               default_config["user"])
                        
                        password = (credentials.get("mysql_password") or 
                                   credentials.get("db_password") or 
                                   credentials.get("database_password") or 
                                   default_config["password"])
                        
                        database = (credentials.get("mysql_database") or 
                                   credentials.get("db_database") or 
                                   credentials.get("database_name") or 
                                   default_config["database"])
                        
                        # Override with test database if in test mode
                        if is_test_mode:
                            database = "openbb_fmp_cache_test"
                        
                        config = {
                            "host": host,
                            "port": port,
                            "user": user,
                            "password": password,
                            "database": database,
                            "charset": default_config["charset"],
                            "test_mode": is_test_mode
                        }
                        
                        logger.info(f"Using MySQL configuration from OpenBB user settings: {user}@{host}:{port}/{database}")
                        return config
        except Exception as e:
            logger.warning(f"Failed to load OpenBB user settings: {e}")
        
        # Fallback to environment variables
        env_database = os.getenv("DB_NAME", default_config["database"])
        if is_test_mode:
            env_database = "openbb_fmp_cache_test"
            
        env_config = {
            "host": os.getenv("DB_HOST", default_config["host"]),
            "port": int(os.getenv("DB_PORT", str(default_config["port"]))),
            "user": os.getenv("DB_USER", default_config["user"]),
            "password": os.getenv("DB_PASSWORD", default_config["password"]),
            "database": env_database,
            "charset": default_config["charset"],
            "test_mode": is_test_mode
        }
        
        # If any environment variables are set, use them
        if any(os.getenv(var) for var in ["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"]):
            logger.info("Using MySQL configuration from environment variables")
            return env_config
        
        # Final fallback to defaults
        logger.info("Using default MySQL configuration")
        return default_config
    
    @property
    def connection_params(self) -> Dict[str, Any]:
        """Get connection parameters for pymysql."""
        params = self.config.copy()
        # Remove non-pymysql parameters
        params.pop('test_mode', None)
        return params


class ConnectionPool:
    """Simple synchronous MySQL connection manager."""
    
    def __init__(self, config: DatabaseConfig):
        """Initialize MySQL connection manager."""
        self.config = config
    
    @contextmanager
    def get_connection(self):
        """Get MySQL database connection (context manager)."""
        connection = pymysql.connect(
            **self.config.connection_params,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )
        try:
            yield connection
        except Exception as e:
            logger.error(f"MySQL connection error: {e}")
            raise
        finally:
            connection.close()


# Global connection pool instance
_connection_pool: Optional[ConnectionPool] = None


def get_connection_pool() -> ConnectionPool:
    """Get global connection pool instance."""
    global _connection_pool
    if _connection_pool is None:
        config = DatabaseConfig()
        _connection_pool = ConnectionPool(config)
    return _connection_pool


def execute_query(query: str, params: tuple = ()) -> Any:
    """Execute a MySQL query and return results."""
    pool = get_connection_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            if query.strip().upper().startswith('SELECT'):
                return cursor.fetchall()
            return cursor.rowcount


def execute_many(query: str, params_list: list) -> int:
    """Execute a MySQL query with multiple parameter sets."""
    pool = get_connection_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(query, params_list)
            return cursor.rowcount


def init_database():
    """Initialize MySQL database and create tables if they don't exist."""
    config = DatabaseConfig()
    temp_config = config.connection_params.copy()
    database_name = temp_config.pop("database", "openbb_fmp_cache")
    
    # Connect to MySQL without specifying database to create it
    connection = pymysql.connect(**temp_config)
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {database_name}")
    finally:
        connection.close()
    
    # Now create tables in the target database
    from .cache_schema import create_all_tables
    return create_all_tables()
