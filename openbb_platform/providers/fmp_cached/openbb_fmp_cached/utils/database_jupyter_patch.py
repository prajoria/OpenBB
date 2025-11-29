"""Jupyter-compatible database utilities for FMP cached provider."""

import os
from typing import Any, Dict, Optional, Union
import aiomysql
import asyncio
from contextlib import asynccontextmanager
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
import functools

logger = logging.getLogger(__name__)

# Global variables for Jupyter compatibility
_jupyter_mode = None
_event_loop_thread = None
_executor = None


def detect_jupyter_environment() -> bool:
    """Detect if running in Jupyter notebook environment."""
    try:
        # Check for IPython
        from IPython import get_ipython
        ipython = get_ipython()
        
        if ipython is None:
            return False
            
        # Check if we're in a notebook
        if hasattr(ipython, 'kernel'):
            return True
            
        # Check for Jupyter-specific modules
        try:
            import ipykernel
            return True
        except ImportError:
            pass
            
        return False
    except ImportError:
        return False


def is_jupyter_mode() -> bool:
    """Check if we're running in Jupyter mode."""
    global _jupyter_mode
    if _jupyter_mode is None:
        _jupyter_mode = detect_jupyter_environment()
        if _jupyter_mode:
            logger.info("Jupyter environment detected - using compatibility mode")
        else:
            logger.info("Standard Python environment detected")
    return _jupyter_mode


def get_executor() -> ThreadPoolExecutor:
    """Get thread pool executor for Jupyter async operations."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fmp_cache")
    return _executor


def run_async_in_thread(coro):
    """Run async coroutine in a separate thread with its own event loop."""
    if not is_jupyter_mode():
        # In regular Python, just run normally
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is running, create a task
            return asyncio.create_task(coro)
        else:
            return loop.run_until_complete(coro)
    
    # In Jupyter, run in separate thread
    def run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    
    executor = get_executor()
    future = executor.submit(run_in_thread)
    return future.result()


class DatabaseConfig:
    """Database configuration manager with Jupyter compatibility."""
    
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
                            "port": int(credentials.get("mysql_port", default_config["port"])),
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


class JupyterCompatibleConnectionPool:
    """MySQL connection pool manager with Jupyter compatibility."""
    
    def __init__(self, config: DatabaseConfig):
        """Initialize connection pool."""
        self.config = config
        self._pool: Optional[aiomysql.Pool] = None
        self._lock = threading.Lock()
    
    async def _create_pool_async(self) -> aiomysql.Pool:
        """Create connection pool asynchronously."""
        if self._pool is None:
            # Apply nest_asyncio if in Jupyter
            if is_jupyter_mode():
                try:
                    import nest_asyncio
                    nest_asyncio.apply()
                except ImportError:
                    logger.warning("nest_asyncio not available - install with: pip install nest_asyncio")
            
            self._pool = await aiomysql.create_pool(
                **self.config.connection_params,
                minsize=2,
                maxsize=10,
                autocommit=True
            )
            logger.info("Database connection pool created successfully")
        return self._pool
    
    def create_pool(self) -> aiomysql.Pool:
        """Create connection pool with Jupyter compatibility."""
        if is_jupyter_mode():
            return run_async_in_thread(self._create_pool_async())
        else:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._create_pool_async())
    
    async def close_pool(self):
        """Close connection pool."""
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
    
    @asynccontextmanager
    async def get_connection(self):
        """Get database connection from pool."""
        if self._pool is None:
            await self._create_pool_async()
        
        async with self._pool.acquire() as conn:
            yield conn


# Global connection pool instance
_connection_pool: Optional[JupyterCompatibleConnectionPool] = None


def get_connection_pool() -> JupyterCompatibleConnectionPool:
    """Get global connection pool instance."""
    global _connection_pool
    if _connection_pool is None:
        config = DatabaseConfig()
        _connection_pool = JupyterCompatibleConnectionPool(config)
    return _connection_pool


async def execute_query_async(query: str, params: tuple = ()) -> Any:
    """Execute a query and return results (async version)."""
    pool = get_connection_pool()
    async with pool.get_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(query, params)
            if query.strip().upper().startswith('SELECT'):
                return await cursor.fetchall()
            return cursor.rowcount


def execute_query(query: str, params: tuple = ()) -> Any:
    """Execute a query and return results (Jupyter-compatible)."""
    if is_jupyter_mode():
        return run_async_in_thread(execute_query_async(query, params))
    else:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(execute_query_async(query, params))


async def execute_many_async(query: str, params_list: list) -> int:
    """Execute a query with multiple parameter sets (async version)."""
    pool = get_connection_pool()
    async with pool.get_connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.executemany(query, params_list)
            return cursor.rowcount


def execute_many(query: str, params_list: list) -> int:
    """Execute a query with multiple parameter sets (Jupyter-compatible)."""
    if is_jupyter_mode():
        return run_async_in_thread(execute_many_async(query, params_list))
    else:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(execute_many_async(query, params_list))


async def init_database_async():
    """Initialize database and create tables if they don't exist (async version)."""
    pool = get_connection_pool()
    
    # Create database if it doesn't exist
    config = DatabaseConfig()
    temp_config = config.connection_params.copy()
    database_name = temp_config.pop("db", temp_config.pop("database", "openbb_fmp_cache"))
    
    # Connect without specifying database to create it
    temp_pool = await aiomysql.create_pool(**temp_config)
    async with temp_pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(f"CREATE DATABASE IF NOT EXISTS {database_name}")
    
    temp_pool.close()
    await temp_pool.wait_closed()
    
    # Now create tables in the target database
    from .cache_schema import create_all_tables_async
    await create_all_tables_async()


def init_database():
    """Initialize database and create tables if they don't exist (Jupyter-compatible)."""
    if is_jupyter_mode():
        return run_async_in_thread(init_database_async())
    else:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(init_database_async())


class JupyterAsyncWrapper:
    """Wrapper to make async functions work in Jupyter notebooks."""
    
    @staticmethod
    def run(coro):
        """Run a coroutine in Jupyter-compatible way."""
        return run_async_in_thread(coro)
    
    @staticmethod
    def create_task(coro):
        """Create a task in Jupyter-compatible way."""
        if is_jupyter_mode():
            return run_async_in_thread(coro)
        else:
            return asyncio.create_task(coro)


# Export the wrapper for easy use
jupyter_async = JupyterAsyncWrapper()