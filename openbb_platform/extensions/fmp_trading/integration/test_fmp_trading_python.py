"""Python interface integration tests for the fmp_trading extension."""

import pytest

# pylint: disable=redefined-outer-name


@pytest.fixture(scope="session")
def obb(pytestconfig):
    """Fixture to setup obb."""
    if pytestconfig.getoption("markexpr") != "not integration":
        import openbb  # pylint: disable=import-outside-toplevel

        return openbb.obb


# ---------------------------------------------------------------------------
# doctor — environment health probe (no params)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("params", [({})])
@pytest.mark.integration
def test_fmp_trading_doctor(params, obb):
    """doctor → FMP credentials + MySQL + bandwidth budget health."""
    result = obb.fmp_trading.doctor()
    assert result is not None


# ---------------------------------------------------------------------------
# report — render session artifacts (session_id + format kwargs)
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
def test_fmp_trading_report(params, obb):
    """report → render MD + XLSX + JSON artifacts for a completed session."""
    result = obb.fmp_trading.report(**params)
    assert result is not None


# ---------------------------------------------------------------------------
# replay — deterministic journal replay by session_id
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
def test_fmp_trading_replay(params, obb):
    """replay → reconstruct a session from its journal file."""
    result = obb.fmp_trading.replay(**params)
    assert result is not None
