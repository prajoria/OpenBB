"""Integration tests for FinancialToolkit extension API endpoints.

Covers the 26 routes flagged by
``test_integration_tests_api::test_missing_api_integration_tests``
(closes #813) plus the pre-existing 6 ``*_capabilities`` / ``about``
smoke tests.

All tests are ``@pytest.mark.integration`` — they exercise real HTTP
requests to a locally-running OpenBB API (port 8000). Under the
default ``-m 'not integration'`` sweep they're deselected; the
``test_missing_api_integration_tests`` discovery check only requires
that a matching ``test_financialtoolkit_<route>`` function exists.
"""

import base64

import pytest
import requests
from openbb_core.env import Env
from openbb_core.provider.utils.helpers import get_querystring


# pylint:disable=redefined-outer-name


def get_headers() -> dict[str, str]:
    """Get headers for API requests."""
    userpass = f"{Env().API_USERNAME}:{Env().API_PASSWORD}"
    userpass_bytes = userpass.encode("ascii")
    base64_bytes = base64.b64encode(userpass_bytes)

    return {"Authorization": f"Basic {base64_bytes.decode('ascii')}"}


def _get(path: str, query_str: str = "", timeout: int = 30):
    """GET against the local financialtoolkit API."""
    url = f"http://0.0.0.0:8000/api/v1/financialtoolkit{path}"
    if query_str:
        url = f"{url}?{query_str}"
    return requests.get(url, headers=get_headers(), timeout=timeout)


# ---------------------------------------------------------------------------
# Top-level: about
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_financialtoolkit_about() -> None:
    """Test FinancialToolkit about endpoint."""
    result = _get("/about")
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# Capabilities endpoints — pre-existing
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_financialtoolkit_models_capabilities() -> None:
    """Test FinancialToolkit models capabilities endpoint."""
    result = _get("/models/capabilities")
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.integration
def test_financialtoolkit_options_capabilities() -> None:
    """Test FinancialToolkit options capabilities endpoint."""
    result = _get("/options/capabilities")
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.integration
def test_financialtoolkit_risk_capabilities() -> None:
    """Test FinancialToolkit risk capabilities endpoint."""
    result = _get("/risk/capabilities")
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.integration
def test_financialtoolkit_performance_capabilities() -> None:
    """Test FinancialToolkit performance capabilities endpoint."""
    result = _get("/performance/capabilities")
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.integration
def test_financialtoolkit_discovery_capabilities() -> None:
    """Test FinancialToolkit discovery capabilities endpoint."""
    result = _get("/discovery/capabilities")
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# discovery: screen, search
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "api_key": None,
                "market_cap_higher": 1_000_000_000,
                "market_cap_lower": None,
                "price_higher": None,
                "price_lower": None,
                "beta_higher": None,
                "beta_lower": None,
                "volume_higher": None,
                "volume_lower": None,
                "dividend_higher": None,
                "dividend_lower": None,
                "is_etf": False,
            }
        ),
    ],
)
@pytest.mark.integration
def test_financialtoolkit_discovery_screen(params) -> None:
    """discovery.screen — filter tickers."""
    query_str = get_querystring(params, [])
    result = _get("/discovery/screen", query_str)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [({"query": "AAPL", "api_key": None, "search_method": "symbol"})],
)
@pytest.mark.integration
def test_financialtoolkit_discovery_search(params) -> None:
    """discovery.search — resolve ticker/name/isin/cusip."""
    query_str = get_querystring(params, [])
    result = _get("/discovery/search", query_str)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# models: altman_z_score, dupont, intrinsic_value, piotroski_score, wacc
# ---------------------------------------------------------------------------

_MODELS_COMMON = {
    "symbols": "AAPL",
    "api_key": None,
    "start_date": "2023-01-01",
    "end_date": "2023-12-31",
    "quarterly": False,
    "rounding": 4,
    "growth": False,
    "lag": 1,
}


@pytest.mark.parametrize(
    "params",
    [({**_MODELS_COMMON, "diluted": True})],
)
@pytest.mark.integration
def test_financialtoolkit_models_altman_z_score(params) -> None:
    """models.altman_z_score."""
    query_str = get_querystring(params, [])
    result = _get("/models/altman_z_score", query_str)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [({**_MODELS_COMMON, "trailing": None})],
)
@pytest.mark.integration
def test_financialtoolkit_models_dupont(params) -> None:
    """models.dupont."""
    query_str = get_querystring(params, [])
    result = _get("/models/dupont", query_str)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "symbols": "AAPL",
                "api_key": None,
                "growth_rate": 0.05,
                "perpetual_growth_rate": 0.025,
                "weighted_average_cost_of_capital": 0.08,
                "start_date": "2023-01-01",
                "end_date": "2023-12-31",
                "quarterly": False,
                "periods": 5,
                "cash_flow_type": "Free Cash Flow",
                "rounding": 2,
            }
        ),
    ],
)
@pytest.mark.integration
def test_financialtoolkit_models_intrinsic_value(params) -> None:
    """models.intrinsic_value."""
    query_str = get_querystring(params, [])
    result = _get("/models/intrinsic_value", query_str)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "symbols": "AAPL",
                "api_key": None,
                "start_date": "2023-01-01",
                "end_date": "2023-12-31",
                "quarterly": False,
            }
        ),
    ],
)
@pytest.mark.integration
def test_financialtoolkit_models_piotroski_score(params) -> None:
    """models.piotroski_score."""
    query_str = get_querystring(params, [])
    result = _get("/models/piotroski_score", query_str)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [({**_MODELS_COMMON, "show_full_results": False, "diluted": True})],
)
@pytest.mark.integration
def test_financialtoolkit_models_wacc(params) -> None:
    """models.wacc."""
    query_str = get_querystring(params, [])
    result = _get("/models/wacc", query_str)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# options: greeks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "symbols": "AAPL",
                "api_key": None,
                "start_date": "2023-01-01",
                "end_date": "2023-12-31",
                "quarterly": False,
                "strike_price_range": 0.25,
                "strike_step_size": 5,
                "expiration_time_range": 30,
                "risk_free_rate": None,
                "dividend_yield": None,
                "put_option": False,
                "show_input_info": False,
                "rounding": 4,
            }
        ),
    ],
)
@pytest.mark.integration
def test_financialtoolkit_options_greeks(params) -> None:
    """options.greeks."""
    query_str = get_querystring(params, [])
    result = _get("/options/greeks", query_str)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# performance: 13 routes
# ---------------------------------------------------------------------------

_PERF_COMMON = {
    "symbols": "AAPL",
    "api_key": None,
    "start_date": "2023-01-01",
    "end_date": "2023-12-31",
    "quarterly": False,
    "period": "yearly",
    "rounding": 4,
    "growth": False,
    "lag": 1,
}


def _perf_test(path: str, params: dict) -> None:
    query_str = get_querystring(params, [])
    result = _get(path, query_str)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_alpha(params) -> None:
    """performance.alpha."""
    _perf_test("/performance/alpha", params)


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_beta(params) -> None:
    """performance.beta."""
    _perf_test("/performance/beta", params)


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_capm(params) -> None:
    """performance.capm."""
    _perf_test("/performance/capm", params)


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_compound_growth_rate(params) -> None:
    """performance.compound_growth_rate."""
    _perf_test("/performance/compound_growth_rate", params)


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_factor_correlations(params) -> None:
    """performance.factor_correlations."""
    _perf_test("/performance/factor_correlations", params)


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_fama_french(params) -> None:
    """performance.fama_french."""
    _perf_test("/performance/fama_french", params)


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_information_ratio(params) -> None:
    """performance.information_ratio."""
    _perf_test("/performance/information_ratio", params)


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_jensens_alpha(params) -> None:
    """performance.jensens_alpha."""
    _perf_test("/performance/jensens_alpha", params)


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_m2_ratio(params) -> None:
    """performance.m2_ratio."""
    _perf_test("/performance/m2_ratio", params)


@pytest.mark.parametrize(
    "params",
    [({**_PERF_COMMON, "rolling": None})],
)
@pytest.mark.integration
def test_financialtoolkit_performance_sharpe_ratio(params) -> None:
    """performance.sharpe_ratio."""
    _perf_test("/performance/sharpe_ratio", params)


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_sortino_ratio(params) -> None:
    """performance.sortino_ratio."""
    _perf_test("/performance/sortino_ratio", params)


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_tracking_error(params) -> None:
    """performance.tracking_error."""
    _perf_test("/performance/tracking_error", params)


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_treynor_ratio(params) -> None:
    """performance.treynor_ratio."""
    _perf_test("/performance/treynor_ratio", params)


# ---------------------------------------------------------------------------
# risk: cvar, evar, garch, var
# ---------------------------------------------------------------------------

_RISK_COMMON = {
    "symbols": "AAPL",
    "api_key": None,
    "start_date": "2023-01-01",
    "end_date": "2023-12-31",
    "quarterly": False,
    "period": "yearly",
    "within_period": True,
    "rounding": 4,
    "growth": False,
    "lag": 1,
}


@pytest.mark.parametrize(
    "params",
    [({**_RISK_COMMON, "alpha": 0.05, "distribution": "historical"})],
)
@pytest.mark.integration
def test_financialtoolkit_risk_cvar(params) -> None:
    """risk.cvar."""
    query_str = get_querystring(params, [])
    result = _get("/risk/cvar", query_str)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [({**_RISK_COMMON, "alpha": 0.05})],
)
@pytest.mark.integration
def test_financialtoolkit_risk_evar(params) -> None:
    """risk.evar."""
    query_str = get_querystring(params, [])
    result = _get("/risk/evar", query_str)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [({**_RISK_COMMON, "time_steps": 10, "optimization_t": 10})],
)
@pytest.mark.integration
def test_financialtoolkit_risk_garch(params) -> None:
    """risk.garch."""
    query_str = get_querystring(params, [])
    result = _get("/risk/garch", query_str)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.parametrize(
    "params",
    [({**_RISK_COMMON, "alpha": 0.05, "distribution": "historical"})],
)
@pytest.mark.integration
def test_financialtoolkit_risk_var(params) -> None:
    """risk.var."""
    query_str = get_querystring(params, [])
    result = _get("/risk/var", query_str)
    assert isinstance(result, requests.Response)
    assert result.status_code == 200
