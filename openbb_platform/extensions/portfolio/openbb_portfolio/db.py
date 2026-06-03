"""
Database utilities for the Portfolio App.

Reads MySQL connection config from environment variables or .env file.
Provides a simple connection helper and query runner.
"""

import json
import logging
import os
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pymysql
import pymysql.cursors

logger = logging.getLogger(__name__)


class DBConfig:
    """MySQL connection configuration."""

    def __init__(self):
        self.host = os.getenv("MYSQL_HOST", "localhost")
        self.port = int(os.getenv("MYSQL_PORT", "3306"))
        # Credentials are REQUIRED — no hardcoded defaults. A committed
        # fallback password (formerly "fmp_password") is a security smell:
        # if the env var is unset the app would silently connect with a
        # known literal credential. Fail fast instead.
        self.user = os.getenv("MYSQL_USER")
        self.password = os.getenv("MYSQL_PASSWORD")
        self._require_credentials()
        # Portfolio data lives in the test database; allow override via
        # PORTFOLIO_DATABASE → MYSQL_TEST_DATABASE → MYSQL_DATABASE
        self.database = os.getenv(
            "PORTFOLIO_DATABASE",
            os.getenv("MYSQL_TEST_DATABASE",
                       os.getenv("MYSQL_DATABASE", "openbb_fmp_cache_test"))
        )
        self.charset = "utf8mb4"

    def _require_credentials(self) -> None:
        """Fail fast if MySQL credentials are not configured."""
        missing = [
            name
            for name, val in (("MYSQL_USER", self.user), ("MYSQL_PASSWORD", self.password))
            if not val
        ]
        if missing:
            raise ValueError(
                "Missing MySQL credential(s): "
                f"{', '.join(missing)}. Set them via environment variables "
                "(or a .env file). No default credentials are provided."
            )

    @property
    def params(self) -> Dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "charset": self.charset,
        }

    def __repr__(self):
        return f"DBConfig({self.user}@{self.host}:{self.port}/{self.database})"


@contextmanager
def get_connection(config: Optional[DBConfig] = None):
    """Get a pymysql connection as a context manager."""
    cfg = config or DBConfig()
    conn = pymysql.connect(
        **cfg.params,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )
    try:
        yield conn
    finally:
        conn.close()


def query(sql: str, params: tuple = (), config: Optional[DBConfig] = None) -> List[dict]:
    """Execute a read query and return rows as list[dict].

    Converts Decimal → float and date/datetime → ISO string automatically.
    """
    with get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            result = []
            for row in rows:
                d = {}
                for col, val in row.items():
                    if isinstance(val, Decimal):
                        d[col] = float(val)
                    elif isinstance(val, (date, datetime)):
                        d[col] = val.isoformat()
                    else:
                        d[col] = val
                result.append(d)
            return result
