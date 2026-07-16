"""API integration tests for the backtest extension."""

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
    """Small helper — GET the local backtest API endpoint."""
    url = f"http://0.0.0.0:8000/api/v1/backtest{path}"
    return requests.get(url, headers=headers, timeout=timeout)


def _post(path: str, headers, json_body, timeout: int = 60):
    """Small helper — POST JSON to the local backtest API endpoint."""
    url = f"http://0.0.0.0:8000/api/v1/backtest{path}"
    return requests.post(url, headers=headers, json=json_body, timeout=timeout)


# ---------------------------------------------------------------------------
# Reusable config bodies
# ---------------------------------------------------------------------------

_BASE_CONFIG = {
    "strategy": "buy_and_hold",
    "symbol": "SPY",
    "start_date": "2020-01-01",
    "end_date": "2020-12-31",
    "starting_cash": 100000,
    "provider": "yfinance",
}


# ---------------------------------------------------------------------------
# Top-level metadata
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("params", [({})])
@pytest.mark.integration
def test_backtest_about(params, headers):
    """about → extension metadata (no query parameters)."""
    query_str = get_querystring(params, [])
    result = _get(f"/about?{query_str}", headers)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# run_router
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("params", [({"config": _BASE_CONFIG})])
@pytest.mark.integration
def test_backtest_run(params, headers):
    """run → single backtest execution."""
    result = _post("/run", headers, params)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params", [({"config": _BASE_CONFIG, "grid": {}})]
)
@pytest.mark.integration
def test_backtest_sweep(params, headers):
    """sweep → parameter-sweep over strategy configs."""
    result = _post("/sweep", headers, params)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params", [({"config": _BASE_CONFIG, "reference": {}})]
)
@pytest.mark.integration
def test_backtest_reconcile(params, headers):
    """reconcile → paper-vs-live comparison."""
    result = _post("/reconcile", headers, params)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# factor_router
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params", [({"config": _BASE_CONFIG, "factor": {"name": "momentum"}})]
)
@pytest.mark.integration
def test_backtest_pipeline(params, headers):
    """pipeline → full factor pipeline."""
    result = _post("/pipeline", headers, params)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params", [({"config": _BASE_CONFIG, "factor": {"name": "momentum"}})]
)
@pytest.mark.integration
def test_backtest_factor_eval(params, headers):
    """factor_eval → standalone factor-evaluation stats."""
    result = _post("/factor_eval", headers, params)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# validate_router
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params", [({"config": _BASE_CONFIG, "method": "walk_forward"})]
)
@pytest.mark.integration
def test_backtest_validate(params, headers):
    """validate → out-of-sample validation."""
    result = _post("/validate", headers, params)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "returns": [0.01, -0.005, 0.02, 0.003, -0.01],
                "title": "Sample tearsheet",
            }
        )
    ],
)
@pytest.mark.integration
def test_backtest_tearsheet(params, headers):
    """tearsheet → HTML tearsheet render."""
    result = _post("/tearsheet", headers, params)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# bundle_router — ingest / list
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params", [({"config": _BASE_CONFIG, "name": "test-bundle"})]
)
@pytest.mark.integration
def test_backtest_bundle_ingest(params, headers):
    """bundle.ingest → materialize a data bundle."""
    result = _post("/bundle/ingest", headers, params)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize("params", [({})])
@pytest.mark.integration
def test_backtest_bundle_list(params, headers):
    """bundle.list → enumerate available data bundles."""
    query_str = get_querystring(params, [])
    result = _get(f"/bundle/list?{query_str}", headers)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200
