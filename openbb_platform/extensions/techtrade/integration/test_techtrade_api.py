"""API integration tests for the techtrade extension."""

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
    """GET against the local techtrade API."""
    url = f"http://0.0.0.0:8000/api/v1/techtrade{path}"
    return requests.get(url, headers=headers, timeout=timeout)


def _post(path: str, headers, json_body, timeout: int = 60):
    """POST JSON against the local techtrade API."""
    url = f"http://0.0.0.0:8000/api/v1/techtrade{path}"
    return requests.post(url, headers=headers, json=json_body, timeout=timeout)


# ---------------------------------------------------------------------------
# about — GET (no params)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("params", [({})])
@pytest.mark.integration
def test_techtrade_about(params, headers):
    """about → extension metadata."""
    query_str = get_querystring(params, [])
    result = _get(f"/about?{query_str}", headers)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# screener_router: segments, movers — GET
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        ({"universe_source": "etf_holdings", "rank_metric": "pct_change", "top_n": 10}),
        ({"universe_source": "etf_holdings", "rank_metric": "volume", "top_n": 5}),
    ],
)
@pytest.mark.integration
def test_techtrade_segments(params, headers):
    """segments → list GICS sectors + universes."""
    query_str = get_querystring(params, [])
    result = _get(f"/segments?{query_str}", headers)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "segment": None,
                "metric": "pct_change",
                "top_n": 10,
                "as_of": None,
            }
        ),
        (
            {
                "segment": "Information Technology",
                "metric": "volume",
                "top_n": 5,
                "as_of": "2026-01-15",
            }
        ),
    ],
)
@pytest.mark.integration
def test_techtrade_movers(params, headers):
    """movers → rank top movers per segment."""
    params = {k: v for k, v in params.items() if v is not None}
    query_str = get_querystring(params, [])
    result = _get(f"/movers?{query_str}", headers)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# signals_router: signals — GET
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "segment": "Information Technology",
                "symbols": None,
                "preset": "trend_follow",
                "as_of": None,
            }
        ),
        (
            {
                "segment": None,
                "symbols": ["AAPL", "MSFT"],
                "preset": "mean_revert",
                "as_of": "2026-01-15",
            }
        ),
    ],
)
@pytest.mark.integration
def test_techtrade_signals(params, headers):
    """signals → ranked confluence signals."""
    params = {k: v for k, v in params.items() if v is not None}
    query_str = get_querystring(params, [])
    result = _get(f"/signals?{query_str}", headers)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# plan_router: plan, orders, simulate, scan
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "segment": "Information Technology",
                "symbols": None,
                "preset": "trend_follow",
                "risk": 0.01,
                "as_of": None,
            }
        ),
        (
            {
                "segment": None,
                "symbols": ["AAPL", "MSFT"],
                "preset": "mean_revert",
                "risk": 0.005,
                "as_of": "2026-01-15",
            }
        ),
    ],
)
@pytest.mark.integration
def test_techtrade_plan(params, headers):
    """plan → per-symbol trade plans."""
    params = {k: v for k, v in params.items() if v is not None}
    query_str = get_querystring(params, [])
    result = _get(f"/plan?{query_str}", headers)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize("params", [({"plan": {}})])
@pytest.mark.integration
def test_techtrade_orders(params, headers):
    """orders → materialize order legs. Requires a valid TradePlan for realistic use."""
    query_str = get_querystring(params, [])
    result = _get(f"/orders?{query_str}", headers)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize("params", [({"orders": [], "bars": []})])
@pytest.mark.integration
def test_techtrade_simulate(params, headers):
    """simulate → paper-fill against a forward OHLCV window."""
    query_str = get_querystring(params, [])
    result = _get(f"/simulate?{query_str}", headers)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "metric": "pct_change",
                "top_n": 10,
                "preset": "trend_follow",
                "risk": None,
                "as_of": None,
                "simulate": True,
                "limit": None,
            }
        ),
        (
            {
                "metric": "volume",
                "top_n": 5,
                "preset": "breakout",
                "risk": 0.005,
                "as_of": "2026-01-15",
                "simulate": False,
                "limit": 20,
            }
        ),
    ],
)
@pytest.mark.integration
def test_techtrade_scan(params, headers):
    """scan → cross-segment ranked plan list."""
    params = {k: v for k, v in params.items() if v is not None}
    query_str = get_querystring(params, [])
    result = _get(f"/scan?{query_str}", headers)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# export_router: export — POST
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        ({"plans": [], "path": None, "engine": "openpyxl"}),
        ({"plans": [], "path": "/tmp/plans.xlsx", "engine": "xlsxwriter"}),
    ],
)
@pytest.mark.integration
def test_techtrade_export(params, headers):
    """export → write the 6-sheet recommendation workbook."""
    body = {k: v for k, v in params.items() if v is not None}
    result = _post("/export", headers, body)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# validate_router: validate — POST
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "plan": {},
                "method": "wfo",
                "thresholds": None,
                "horizon_years": 5,
                "provider": None,
            }
        ),
        (
            {
                "plan": {},
                "method": "cpcv",
                "thresholds": None,
                "horizon_years": 3,
                "provider": "fmp_cached",
            }
        ),
    ],
)
@pytest.mark.integration
def test_techtrade_validate(params, headers):
    """validate → robustness verdict via openbb-backtest."""
    body = {k: v for k, v in params.items() if v is not None}
    result = _post("/validate", headers, body)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# tune_router: tune — POST
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "segment": "Information Technology",
                "as_of": None,
                "horizon_years": 5,
                "forward_horizon_bars": 5,
                "trials": 100,
                "early_stop": 20,
                "method": "wfo",
                "thresholds": None,
                "provider": None,
            }
        ),
        (
            {
                "segment": "Financials",
                "as_of": "2026-01-15",
                "horizon_years": 3,
                "forward_horizon_bars": 5,
                "trials": 50,
                "early_stop": 10,
                "method": "cpcv",
                "thresholds": None,
                "provider": "fmp_cached",
            }
        ),
    ],
)
@pytest.mark.integration
def test_techtrade_tune(params, headers):
    """tune → tune indicator periods for a segment, gated by validate."""
    body = {k: v for k, v in params.items() if v is not None}
    result = _post("/tune", headers, body)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200
