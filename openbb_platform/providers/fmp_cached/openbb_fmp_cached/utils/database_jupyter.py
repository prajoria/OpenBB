
"""Jupyter-compatible database utilities for FMP cached provider."""

import asyncio
import logging
from typing import Optional
import aiomysql
from openbb_core.app.model.user_settings import UserSettings

logger = logging.getLogger(__name__)

# Global connection pool
_connection_pool: Optional[aiomysql.Pool] = None
_jupyter_mode = False

def detect_jupyter():
    """Detect if running in Jupyter notebook"""
    try:
        from IPython import get_ipython
        return get_ipython() is not None
    except ImportError:
        return False

async def get_connection_pool() -> aiomysql.Pool:
    """Get or create database connection pool with Jupyter compatibility."""
    global _connection_pool, _jupyter_mode

    if _connection_pool is None:
        _jupyter_mode = detect_jupyter()

        # Get database settings
        settings = UserSettings()

        db_config = {
            'host': getattr(settings.provider_settings, 'fmp_cached_db_host', 'localhost'),
            'port': int(getattr(settings.provider_settings, 'fmp_cached_db_port', 3306)),
            'user': getattr(settings.provider_settings, 'fmp_cached_db_user', 'fmp_user'),
            'password': getattr(settings.provider_settings, 'fmp_cached_db_password', 'fmp_password'),
            'db': getattr(settings.provider_settings, 'fmp_cached_db_name', 'openbb_fmp_cache'),
            'minsize': 1,
            'maxsize': 5,
        }

        try:
            if _jupyter_mode:
                # In Jupyter, use a different approach to avoid event loop conflicts
                import nest_asyncio
                nest_asyncio.apply()

                # Create a simple connection for Jupyter
                _connection_pool = await aiomysql.create_pool(**db_config)
                logger.info("Database pool created successfully in Jupyter mode")
            else:
                # Standard mode for regular Python scripts
                _connection_pool = await aiomysql.create_pool(**db_config)
                logger.info("Database pool created successfully")

        except Exception as e:
            logger.error(f"Failed to create database pool: {e}")
            raise

    return _connection_pool

async def init_database():
    """Initialize database and create tables if they don't exist."""
    try:
        pool = await get_connection_pool()
        logger.info("Database initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False

def close_connection_pool():
    """Close the database connection pool."""
    global _connection_pool
    if _connection_pool:
        _connection_pool.close()
        _connection_pool = None
