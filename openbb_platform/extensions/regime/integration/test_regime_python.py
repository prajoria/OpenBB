"""Python interface integration tests for the regime extension."""

import pytest

# pylint: disable=redefined-outer-name


@pytest.fixture(scope="session")
def obb(pytestconfig):
    """Fixture to setup obb."""
    if pytestconfig.getoption("markexpr") != "not integration":
        import openbb  # pylint: disable=import-outside-toplevel

        return openbb.obb


@pytest.mark.parametrize("params", [({})])
@pytest.mark.integration
def test_regime_about(params, obb):
    """about → describe the regime router surface (no parameters)."""
    result = obb.regime.about()
    assert result is not None


@pytest.mark.parametrize(
    "params",
    [
        # Every entry must include every openbb-side param — see
        # extensions/tests/utils/integration_tests_testers.py::check_missing_params
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
def test_regime_detect(params, obb):
    """detect → classify current market regime from SPY + VIX daily bars."""
    result = obb.regime.detect(**params)
    assert result is not None
