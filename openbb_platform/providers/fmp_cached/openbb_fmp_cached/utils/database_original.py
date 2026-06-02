"""Database configuration and connection utilities for FMP Cached provider."""

import os
from typing import Any, Dict, Optional
import aiomysql
import asyncio
from contextlib import asynccontextmanager
import json
import logging

logger = logging.getLogger(__name__)


class DatabaseConfig:
    """Database configuration manager."""
    
    def __init__(self):
        """Initialize database configuration from user settings."""
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load database configuration from OpenBB user settings, with environment variable fallback."""
        
        default_config = {
            "host": "localhost",
            "port": 3306,
            "user": "fmp_user",
            "password": "fmp_password",
            "database": "openbb_fmp_cache",
            "charset": "utf8mb4"
        }
        
        # First try OpenBB user settings (preferred)
        settings_path = os.path.expanduser("~/.openbb_platform/user_settings.json")
        
        try:
            if os.path.exists(settings_path):
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                    credentials = settings.get("credentials", {})
                    
                    # Check if MySQL credentials are configured
                    mysql_keys = ["mysql_host", "mysql_user", "mysql_password", "mysql_database"]
                    if any(key in credentials for key in mysql_keys):
                        config = {
                            "host": credentials.get("mysql_host", default_config["host"]),
                            "port": int(credentials.get("mysql_port", default_config["port"])),  # Ensure int for aiomysql
                            "user": credentials.get("mysql_user", default_config["user"]),
                            "password": credentials.get("mysql_password", default_config["password"]),
                            "database": credentials.get("mysql_database", default_config["database"]),
                            "charset": default_config["charset"]
                        }
                        logger.info("Using MySQL configuration from OpenBB user settings")
                        return config
        except Exception as e:
            logger.warning(f"Failed to load OpenBB user settings: {e}")
        
        # Fallback to environment variables
        env_config = {
            "host": os.getenv("DB_HOST", default_config["host"]),
            "port": int(os.getenv("DB_PORT", str(default_config["port"]))),
            "user": os.getenv("DB_USER", default_config["user"]),
            "password": os.getenv("DB_PASSWORD", default_config["password"]),
            "database": os.getenv("DB_NAME", default_config["database"]),
            "charset": default_config["charset"]
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
        """Get connection parameters for aiomysql."""
        params = self.config.copy()
        # aiomysql uses 'db' instead of 'database'
        if 'database' in params:
            params['db'] = params.pop('database')
        return params


class ConnectionPool:
    """MySQL connection pool manager."""
    
    def __init__(self, config: DatabaseConfig):
        """Initialize connection pool."""
        self.config = config
        self._pool: Optional[aiomysql.Pool] = None
    
    async def create_pool(self) -> aiomysql.Pool:
        """Create connection pool."""
        if self._pool is None:
            self._pool = await aiomysql.create_pool(
                **self.config.connection_params,
                minsize=5,
                maxsize=20,
                autocommit=True
            )
        return self._pool
    
    async def close_pool(self):
        """Close connection pool."""
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
    
    @asynccontextmanager
    async def get_connection(self):
        """Get database connection from pool."""
        pool = await self.create_pool()
        async with pool.acquire() as conn:
            yield conn


# Global connection pool instance
_connection_pool: Optional[ConnectionPool] = None


def get_connection_pool() -> ConnectionPool:
    """Get global connection pool instance."""
    global _connection_pool
    if _connection_pool is None:
        config = DatabaseConfig()
        _connection_pool = ConnectionPool(config)
    return _connection_pool


async def execute_query(query: str, params: tuple = ()) -> Any:
    """Execute a query and return results."""
    pool = get_connection_pool()
    async with pool.get_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(query, params)
            if query.strip().upper().startswith('SELECT'):
                return await cursor.fetchall()
            return cursor.rowcount


async def execute_many(query: str, params_list: list) -> int:
    """Execute a query with multiple parameter sets."""
    pool = get_connection_pool()
    async with pool.get_connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.executemany(query, params_list)
            return cursor.rowcount


async def init_database():
    """Initialize database and create tables if they don't exist."""
    pool = get_connection_pool()
    
    # Create database if it doesn't exist
    config = DatabaseConfig()
    temp_config = config.connection_params.copy()
    # The connection_params returns 'db' not 'database'
    database_name = temp_config.pop("db", temp_config.pop("database", "openbb_fmp_cache"))
    
    # Connect without specifying database to create it
    temp_pool = await aiomysql.create_pool(**temp_config)
    async with temp_pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(f"CREATE DATABASE IF NOT EXISTS {database_name}")
    
    temp_pool.close()
    await temp_pool.wait_closed()
    
    # Now create tables in the target database
    from .cache_schema import create_all_tables
    await create_all_tables()