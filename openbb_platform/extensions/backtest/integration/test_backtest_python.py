"""Python interface integration tests for the backtest extension."""

import pytest

# pylint: disable=redefined-outer-name


@pytest.fixture(scope="session")
def obb(pytestconfig):
    """Fixture to setup obb."""
    if pytestconfig.getoption("markexpr") != "not integration":
        import openbb  # pylint: disable=import-outside-toplevel

        return openbb.obb


# ---------------------------------------------------------------------------
# Top-level metadata
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("params", [({})])
@pytest.mark.integration
def test_backtest_about(params, obb):
    """Extension-metadata endpoint. No parameters."""
    result = obb.backtest.about()
    assert result is not None


# ---------------------------------------------------------------------------
# run_router — run, sweep, reconcile
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "config": {
                    "strategy": "buy_and_hold",
                    "symbol": "SPY",
                    "start_date": "2020-01-01",
                    "end_date": "2020-12-31",
                    "starting_cash": 100000,
                    "provider": "yfinance",
                }
            }
        )
    ],
)
@pytest.mark.integration
def test_backtest_run(params, obb):
    """Run a single backtest."""
    result = obb.backtest.run(**params)
    assert result is not None


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "config": {
                    "strategy": "buy_and_hold",
                    "symbol": "SPY",
                    "start_date": "2020-01-01",
                    "end_date": "2020-12-31",
                    "starting_cash": 100000,
                    "provider": "yfinance",
                },
                "grid": {},
            }
        )
    ],
)
@pytest.mark.integration
def test_backtest_sweep(params, obb):
    """Parameter-sweep over strategy configs."""
    result = obb.backtest.sweep(**params)
    assert result is not None


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "config": {
                    "strategy": "buy_and_hold",
                    "symbol": "SPY",
                    "start_date": "2020-01-01",
                    "end_date": "2020-12-31",
                    "starting_cash": 100000,
                    "provider": "yfinance",
                },
                "reference": {},
            }
        )
    ],
)
@pytest.mark.integration
def test_backtest_reconcile(params, obb):
    """Reconcile paper-vs-live discrepancies."""
    result = obb.backtest.reconcile(**params)
    assert result is not None


# ---------------------------------------------------------------------------
# factor_router — pipeline, factor_eval
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "config": {
                    "strategy": "buy_and_hold",
                    "symbol": "SPY",
                    "start_date": "2020-01-01",
                    "end_date": "2020-12-31",
                    "starting_cash": 100000,
                    "provider": "yfinance",
                },
                "factor": {"name": "momentum"},
            }
        )
    ],
)
@pytest.mark.integration
def test_backtest_pipeline(params, obb):
    """Full factor pipeline (compute → forward returns → alphalens metrics)."""
    result = obb.backtest.pipeline(**params)
    assert result is not None


@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "config": {
                    "strategy": "buy_and_hold",
                    "symbol": "SPY",
                    "start_date": "2020-01-01",
                    "end_date": "2020-12-31",
                    "starting_cash": 100000,
                    "provider": "yfinance",
                },
                "factor": {"name": "momentum"},
            }
        )
    ],
)
@pytest.mark.integration
def test_backtest_factor_eval(params, obb):
    """Standalone factor-evaluation stats."""
    result = obb.backtest.factor_eval(**params)
    assert result is not None


# ---------------------------------------------------------------------------
# validate_router — validate, tearsheet
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "config": {
                    "strategy": "buy_and_hold",
                    "symbol": "SPY",
                    "start_date": "2020-01-01",
                    "end_date": "2020-12-31",
                    "starting_cash": 100000,
                    "provider": "yfinance",
                },
                "method": "walk_forward",
            }
        )
    ],
)
@pytest.mark.integration
def test_backtest_validate(params, obb):
    """Run out-of-sample validation."""
    result = obb.backtest.validate(**params)
    assert result is not None


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
def test_backtest_tearsheet(params, obb):
    """Render an HTML tearsheet."""
    result = obb.backtest.tearsheet(**params)
    assert result is not None


# ---------------------------------------------------------------------------
# bundle_router — bundle.ingest, bundle.list
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        (
            {
                "config": {
                    "strategy": "buy_and_hold",
                    "symbol": "SPY",
                    "start_date": "2020-01-01",
                    "end_date": "2020-12-31",
                    "starting_cash": 100000,
                    "provider": "yfinance",
                },
                "name": "test-bundle",
            }
        )
    ],
)
@pytest.mark.integration
def test_backtest_bundle_ingest(params, obb):
    """Ingest a data bundle for offline backtests."""
    result = obb.backtest.bundle.ingest(**params)
    assert result is not None


@pytest.mark.parametrize("params", [({})])
@pytest.mark.integration
def test_backtest_bundle_list(params, obb):
    """List available data bundles."""
    result = obb.backtest.bundle.list()
    assert result is not None
