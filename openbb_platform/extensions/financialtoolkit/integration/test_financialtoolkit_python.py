"""Integration tests for FinancialToolkit extension (Python interface).

Covers the 25 routes flagged by
``test_integration_tests_python::test_missing_python_integration_tests``
(closes #813) plus the pre-existing 6 ``*_capabilities`` / ``about``
smoke tests.

All tests are ``@pytest.mark.integration`` — they exercise real
FinancialToolkit calls (which fan out to FMP under the hood via the
adapter layer) so a default ``-m 'not integration'`` sweep deselects
them. The `test_missing_python_integration_tests` discovery check only
requires that a matching ``test_financialtoolkit_<route>`` function
exists; the network path is only walked when the marker is opted in.
"""

import pytest
from openbb_core.app.model.obbject import OBBject

# pylint:disable=redefined-outer-name


@pytest.fixture(scope="session")
def obb(pytestconfig):
    """Fixture to setup obb."""
    if pytestconfig.getoption("markexpr") != "not integration":
        import openbb  # pylint:disable=import-outside-toplevel

        return openbb.obb


# ---------------------------------------------------------------------------
# Top-level: about
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_financialtoolkit_about(obb):
    """Test financialtoolkit about command."""
    result = obb.financialtoolkit.about()
    assert result
    assert isinstance(result, OBBject)


# ---------------------------------------------------------------------------
# Capabilities endpoints — pre-existing
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_financialtoolkit_models_capabilities(obb):
    """Test financialtoolkit models capabilities command."""
    result = obb.financialtoolkit.models.capabilities()
    assert result
    assert isinstance(result, OBBject)


@pytest.mark.integration
def test_financialtoolkit_options_capabilities(obb):
    """Test financialtoolkit options capabilities command."""
    result = obb.financialtoolkit.options.capabilities()
    assert result
    assert isinstance(result, OBBject)


@pytest.mark.integration
def test_financialtoolkit_risk_capabilities(obb):
    """Test financialtoolkit risk capabilities command."""
    result = obb.financialtoolkit.risk.capabilities()
    assert result
    assert isinstance(result, OBBject)


@pytest.mark.integration
def test_financialtoolkit_performance_capabilities(obb):
    """Test financialtoolkit performance capabilities command."""
    result = obb.financialtoolkit.performance.capabilities()
    assert result
    assert isinstance(result, OBBject)


@pytest.mark.integration
def test_financialtoolkit_discovery_capabilities(obb):
    """Test financialtoolkit discovery capabilities command."""
    result = obb.financialtoolkit.discovery.capabilities()
    assert result
    assert isinstance(result, OBBject)


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
def test_financialtoolkit_discovery_screen(params, obb):
    """discovery.screen — filter tickers by market cap / price / volume."""
    result = obb.financialtoolkit.discovery.screen(**params)
    assert result is not None


@pytest.mark.parametrize(
    "params",
    [({"query": "AAPL", "api_key": None, "search_method": "symbol"})],
)
@pytest.mark.integration
def test_financialtoolkit_discovery_search(params, obb):
    """discovery.search — find tickers by symbol/name/isin/cusip."""
    result = obb.financialtoolkit.discovery.search(**params)
    assert result is not None


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
def test_financialtoolkit_models_altman_z_score(params, obb):
    """models.altman_z_score — bankruptcy-risk composite."""
    result = obb.financialtoolkit.models.altman_z_score(**params)
    assert result is not None


@pytest.mark.parametrize(
    "params",
    [({**_MODELS_COMMON, "trailing": None})],
)
@pytest.mark.integration
def test_financialtoolkit_models_dupont(params, obb):
    """models.dupont — ROE decomposition."""
    result = obb.financialtoolkit.models.dupont(**params)
    assert result is not None


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
def test_financialtoolkit_models_intrinsic_value(params, obb):
    """models.intrinsic_value — DCF fair-value estimate."""
    result = obb.financialtoolkit.models.intrinsic_value(**params)
    assert result is not None


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
def test_financialtoolkit_models_piotroski_score(params, obb):
    """models.piotroski_score — 9-point fundamentals score."""
    result = obb.financialtoolkit.models.piotroski_score(**params)
    assert result is not None


@pytest.mark.parametrize(
    "params",
    [({**_MODELS_COMMON, "show_full_results": False, "diluted": True})],
)
@pytest.mark.integration
def test_financialtoolkit_models_wacc(params, obb):
    """models.wacc — weighted average cost of capital."""
    result = obb.financialtoolkit.models.wacc(**params)
    assert result is not None


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
def test_financialtoolkit_options_greeks(params, obb):
    """options.greeks — Black-Scholes greeks table."""
    result = obb.financialtoolkit.options.greeks(**params)
    assert result is not None


# ---------------------------------------------------------------------------
# performance: alpha, beta, capm, compound_growth_rate, factor_correlations,
#              fama_french, information_ratio, jensens_alpha, m2_ratio,
#              sharpe_ratio, sortino_ratio, tracking_error, treynor_ratio
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


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_alpha(params, obb):
    """performance.alpha — Jensen's alpha (subset)."""
    result = obb.financialtoolkit.performance.alpha(**params)
    assert result is not None


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_beta(params, obb):
    """performance.beta — market beta."""
    result = obb.financialtoolkit.performance.beta(**params)
    assert result is not None


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_capm(params, obb):
    """performance.capm — CAPM expected return."""
    result = obb.financialtoolkit.performance.capm(**params)
    assert result is not None


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_compound_growth_rate(params, obb):
    """performance.compound_growth_rate — CAGR."""
    result = obb.financialtoolkit.performance.compound_growth_rate(**params)
    assert result is not None


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_factor_correlations(params, obb):
    """performance.factor_correlations — correlations to Fama-French factors."""
    result = obb.financialtoolkit.performance.factor_correlations(**params)
    assert result is not None


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_fama_french(params, obb):
    """performance.fama_french — three/five factor regression."""
    result = obb.financialtoolkit.performance.fama_french(**params)
    assert result is not None


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_information_ratio(params, obb):
    """performance.information_ratio — active-return / tracking-error."""
    result = obb.financialtoolkit.performance.information_ratio(**params)
    assert result is not None


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_jensens_alpha(params, obb):
    """performance.jensens_alpha — Jensen's alpha."""
    result = obb.financialtoolkit.performance.jensens_alpha(**params)
    assert result is not None


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_m2_ratio(params, obb):
    """performance.m2_ratio — Modigliani risk-adjusted return."""
    result = obb.financialtoolkit.performance.m2_ratio(**params)
    assert result is not None


@pytest.mark.parametrize(
    "params",
    [({**_PERF_COMMON, "rolling": None})],
)
@pytest.mark.integration
def test_financialtoolkit_performance_sharpe_ratio(params, obb):
    """performance.sharpe_ratio — excess return per unit volatility."""
    result = obb.financialtoolkit.performance.sharpe_ratio(**params)
    assert result is not None


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_sortino_ratio(params, obb):
    """performance.sortino_ratio — excess return per downside volatility."""
    result = obb.financialtoolkit.performance.sortino_ratio(**params)
    assert result is not None


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_tracking_error(params, obb):
    """performance.tracking_error — std of active returns."""
    result = obb.financialtoolkit.performance.tracking_error(**params)
    assert result is not None


@pytest.mark.parametrize("params", [(_PERF_COMMON)])
@pytest.mark.integration
def test_financialtoolkit_performance_treynor_ratio(params, obb):
    """performance.treynor_ratio — excess return per unit beta."""
    result = obb.financialtoolkit.performance.treynor_ratio(**params)
    assert result is not None


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
def test_financialtoolkit_risk_cvar(params, obb):
    """risk.cvar — conditional (expected shortfall) VaR."""
    result = obb.financialtoolkit.risk.cvar(**params)
    assert result is not None


@pytest.mark.parametrize(
    "params",
    [({**_RISK_COMMON, "alpha": 0.05})],
)
@pytest.mark.integration
def test_financialtoolkit_risk_evar(params, obb):
    """risk.evar — entropic VaR."""
    result = obb.financialtoolkit.risk.evar(**params)
    assert result is not None


@pytest.mark.parametrize(
    "params",
    [({**_RISK_COMMON, "time_steps": 10, "optimization_t": 10})],
)
@pytest.mark.integration
def test_financialtoolkit_risk_garch(params, obb):
    """risk.garch — GARCH(1,1) volatility."""
    result = obb.financialtoolkit.risk.garch(**params)
    assert result is not None


@pytest.mark.parametrize(
    "params",
    [({**_RISK_COMMON, "alpha": 0.05, "distribution": "historical"})],
)
@pytest.mark.integration
def test_financialtoolkit_risk_var(params, obb):
    """risk.var — value at risk."""
    result = obb.financialtoolkit.risk.var(**params)
    assert result is not None
