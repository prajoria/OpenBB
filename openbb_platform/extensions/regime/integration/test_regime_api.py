"""API integration tests for the regime extension."""

import base64

import pytest
import requests
from openbb_core.env import Env
from openbb_core.provider.utils.helpers import get_querystring

# pylint: disable=redefined-outer-name


@pytest.fixture(scope="session")
def headers():
    """Get the headers for the API request."""
    userpass = f"{Env().API_USERNAME}:{Env().API_PASSWORD}"
    userpass_bytes = userpass.encode("ascii")
    base64_bytes = base64.b64encode(userpass_bytes)
    return {"Authorization": f"Basic {base64_bytes.decode('ascii')}"}


def _get(path: str, headers, timeout: int = 30):
    """GET helper against the local regime API."""
    url = f"http://0.0.0.0:8000/api/v1/regime{path}"
    return requests.get(url, headers=headers, timeout=timeout)


@pytest.mark.parametrize("params", [({})])
@pytest.mark.integration
def test_regime_about(params, headers):
    """about → metadata endpoint."""
    query_str = get_querystring(params, [])
    result = _get(f"/about?{query_str}", headers)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "as_of": None,
                "lookback_days": 500,
                "spy_symbol": "SPY",
                "vix_symbol": "^VIX",
                "provider": "fmp_cached",
            }
        ),
        (
            {
                "as_of": "2020-03-16",
                "lookback_days": 500,
                "spy_symbol": "SPY",
                "vix_symbol": "^VIX",
                "provider": "fmp_cached",
            }
        ),
    ],
)
@pytest.mark.integration
def test_regime_detect(params, headers):
    """detect → classify current market regime."""
    params = {k: v for k, v in params.items() if v is not None}
    query_str = get_querystring(params, [])
    result = _get(f"/detect?{query_str}", headers)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200
