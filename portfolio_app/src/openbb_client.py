"""
OpenBB API Client — proxy helper for calling the OpenBB Platform API.

The Portfolio App runs on a separate port (:6903) and calls back to the
OpenBB Platform API (:6902) for market data like live quotes, historical
prices, and fundamentals.  Both services use self-signed HTTPS certs,
so we set verify=False for inter-service calls.

Usage:
    from openbb_client import OpenBBClient

    obb = OpenBBClient()  # defaults to https://127.0.0.1:6902
    quote = await obb.get("/api/v1/equity/price/quote", symbol="MSFT")
"""

import logging
import os
from typing import Any, Dict, Optional

import httpx
import pandas as pd

logger = logging.getLogger(__name__)


class OpenBBClient:
    """Async HTTP client for the OpenBB Platform API."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv(
            "OPENBB_API_URL", "https://127.0.0.1:6902"
        )

    async def get(
        self, path: str, **params: Any
    ) -> Optional[Dict]:
        """GET request to the OpenBB API. Returns parsed JSON or None on error."""
        url = f"{self.base_url}{path}"
        timeout = float(params.pop("timeout", 30.0))
        try:
            async with httpx.AsyncClient(verify=False) as client:
                resp = await client.get(url, params=params, timeout=timeout)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("OpenBB API %s returned %d: %s", path, e.response.status_code, e)
            return None
        except httpx.ConnectError:
            logger.warning("OpenBB API not reachable at %s", self.base_url)
            return None
        except Exception as e:
            logger.error("OpenBB API request failed: %s", e, exc_info=True)
            return None

    async def post(
        self, path: str, body: Optional[Dict] = None, timeout: float = 30.0, **params: Any
    ) -> Optional[Dict]:
        """POST request to the OpenBB API."""
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(verify=False) as client:
                resp = await client.post(url, json=body, params=params, timeout=timeout)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error("OpenBB API POST %s failed: %s", path, e)
            return None

    async def get_df(
        self, path: str, timeout: float = 30.0, **params: Any
    ) -> pd.DataFrame:
        """GET request to the OpenBB API, returning results as a DataFrame.

        Extracts the ``results`` key from the standard OpenBB response
        envelope and converts it to a pandas DataFrame.
        """
        import pandas as pd

        data = await self.get(path, timeout=timeout, **params)
        if data is None:
            return pd.DataFrame()
        # OpenBB API returns {"results": [...]} or just a list
        if isinstance(data, dict):
            results = data.get("results", data.get("data", [data]))
        elif isinstance(data, list):
            results = data
        else:
            results = [data]
        return pd.DataFrame(results) if results else pd.DataFrame()

    async def health(self) -> bool:
        """Check if the OpenBB API is reachable."""
        url = f"{self.base_url}/docs"
        try:
            async with httpx.AsyncClient(verify=False) as client:
                resp = await client.get(url, timeout=5.0)
                return resp.status_code == 200
        except Exception:
            return False
