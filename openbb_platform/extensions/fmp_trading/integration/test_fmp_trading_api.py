"""API integration tests for the fmp_trading extension."""

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
    """GET against fmp_trading API."""
    url = f"http://0.0.0.0:8000/api/v1/fmp_trading{path}"
    return requests.get(url, headers=headers, timeout=timeout)


def _post(path: str, headers, json_body, timeout: int = 60):
    """POST against fmp_trading API."""
    url = f"http://0.0.0.0:8000/api/v1/fmp_trading{path}"
    return requests.post(url, headers=headers, json=json_body, timeout=timeout)


# ---------------------------------------------------------------------------
# doctor — GET (no params)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("params", [({})])
@pytest.mark.integration
def test_fmp_trading_doctor(params, headers):
    """doctor → environment health probe."""
    query_str = get_querystring(params, [])
    result = _get(f"/doctor?{query_str}", headers)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# report — POST
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "session_id": "s20260101120000",
                "format": "all",
                "output_dir": None,
                "include_agent_narrative": True,
                "overwrite": False,
            }
        ),
        (
            {
                "session_id": "s20260101120000",
                "format": "xlsx",
                "output_dir": None,
                "include_agent_narrative": False,
                "overwrite": True,
            }
        ),
    ],
)
@pytest.mark.integration
def test_fmp_trading_report(params, headers):
    """report → render MD + XLSX + JSON artifacts."""
    body = {k: v for k, v in params.items() if v is not None}
    result = _post("/report", headers, body)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# replay — POST
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "session_id": "s20260101120000",
                "from_tick": 0,
                "to_tick": None,
            }
        ),
        (
            {
                "session_id": "s20260101120000",
                "from_tick": 0,
                "to_tick": 100,
            }
        ),
    ],
)
@pytest.mark.integration
def test_fmp_trading_replay(params, headers):
    """replay → deterministic journal reconstruction."""
    body = {k: v for k, v in params.items() if v is not None}
    result = _post("/replay", headers, body)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200
