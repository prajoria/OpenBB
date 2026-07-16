"""Python interface integration tests for the techtrade extension."""

import pytest

# pylint: disable=redefined-outer-name


@pytest.fixture(scope="session")
def obb(pytestconfig):
    """Fixture to setup obb."""
    if pytestconfig.getoption("markexpr") != "not integration":
        import openbb  # pylint: disable=import-outside-toplevel

        return openbb.obb


# ---------------------------------------------------------------------------
# Top-level: about
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("params", [({})])
@pytest.mark.integration
def test_techtrade_about(params, obb):
    """about → extension metadata (no parameters)."""
    result = obb.techtrade.about()
    assert result is not None


# ---------------------------------------------------------------------------
# engine/screener_router: segments, movers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "universe_source": "etf_holdings",
                "rank_metric": "pct_change",
                "top_n": 10,
            }
        ),
        (
            {
                "universe_source": "etf_holdings",
                "rank_metric": "volume",
                "top_n": 5,
            }
        ),
    ],
)
@pytest.mark.integration
def test_techtrade_segments(params, obb):
    """segments → list GICS sectors and resolved universes."""
    result = obb.techtrade.segments(**params)
    assert result is not None


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
def test_techtrade_movers(params, obb):
    """movers → rank the day's top movers per segment."""
    result = obb.techtrade.movers(**params)
    assert result is not None


# ---------------------------------------------------------------------------
# engine/signals_router: signals
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
def test_techtrade_signals(params, obb):
    """signals → ranked confluence signals for a segment or symbol set."""
    result = obb.techtrade.signals(**params)
    assert result is not None


# ---------------------------------------------------------------------------
# engine/plan_router: plan, orders, simulate, scan
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
def test_techtrade_plan(params, obb):
    """plan → per-symbol trade plans for a symbol set or GICS segment."""
    result = obb.techtrade.plan(**params)
    assert result is not None


@pytest.mark.parametrize("params", [({"plan": {}})])
@pytest.mark.integration
def test_techtrade_orders(params, obb):
    """orders → materialize broker-ready order legs from a plan.

    Realistic usage requires a valid TradePlan from `obb.techtrade.plan()`;
    the placeholder-dict here exercises the wiring only. Real workflow:

        plans = obb.techtrade.plan(segment=\"Information Technology\").results
        orders = obb.techtrade.orders(plan=plans[0]).results
    """
    result = obb.techtrade.orders(**params)
    assert result is not None


@pytest.mark.parametrize("params", [({"orders": [], "bars": []})])
@pytest.mark.integration
def test_techtrade_simulate(params, obb):
    """simulate → paper-fill order legs against a forward OHLCV window.

    Realistic usage requires a valid order list from `obb.techtrade.orders()`
    and a forward bars window; the empty lists here exercise the wiring only.
    Real workflow:

        plans = obb.techtrade.plan(segment=\"Information Technology\").results
        orders = obb.techtrade.orders(plan=plans[0]).results
        fills = obb.techtrade.simulate(orders=orders, bars=forward_bars).results
    """
    result = obb.techtrade.simulate(**params)
    assert result is not None


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
def test_techtrade_scan(params, obb):
    """scan → cross-segment ranked plan list across all 11 GICS sectors."""
    result = obb.techtrade.scan(**params)
    assert result is not None


# ---------------------------------------------------------------------------
# reporting/export_router: export
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        ({"plans": [], "path": None, "engine": "openpyxl"}),
        (
            {
                "plans": [],
                "path": "/tmp/plans.xlsx",
                "engine": "xlsxwriter",
            }
        ),
    ],
)
@pytest.mark.integration
def test_techtrade_export(params, obb):
    """export → write the 6-sheet recommendation workbook."""
    result = obb.techtrade.export(**params)
    assert result is not None


# ---------------------------------------------------------------------------
# validation/validate_router: validate
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
def test_techtrade_validate(params, obb):
    """validate → robustness verdict via openbb-backtest."""
    result = obb.techtrade.validate(**params)
    assert result is not None


# ---------------------------------------------------------------------------
# tuning/tune_router: tune
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
def test_techtrade_tune(params, obb):
    """tune → tune indicator periods for a segment, gated by validate."""
    result = obb.techtrade.tune(**params)
    assert result is not None
