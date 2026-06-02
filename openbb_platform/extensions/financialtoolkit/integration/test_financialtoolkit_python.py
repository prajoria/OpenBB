"""Integration tests for FinancialToolkit extension (Python interface)."""

import pytest
from openbb_core.app.model.obbject import OBBject


@pytest.fixture(scope="session")
def obb(pytestconfig):
    """Fixture to setup obb."""
    if pytestconfig.getoption("markexpr") != "not integration":
        import openbb  # pylint:disable=import-outside-toplevel

        return openbb.obb


@pytest.mark.integration
def test_financialtoolkit_about(obb):
    """Test financialtoolkit about command."""
    result = obb.financialtoolkit.about()
    assert result
    assert isinstance(result, OBBject)


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
