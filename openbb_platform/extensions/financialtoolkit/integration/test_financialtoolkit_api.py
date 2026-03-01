"""Integration tests for FinancialToolkit extension API endpoints."""

import base64

import pytest
import requests
from openbb_core.env import Env


# pylint:disable=redefined-outer-name

def get_headers() -> dict[str, str]:
    """Get headers for API requests."""
    userpass = f"{Env().API_USERNAME}:{Env().API_PASSWORD}"
    userpass_bytes = userpass.encode("ascii")
    base64_bytes = base64.b64encode(userpass_bytes)

    return {"Authorization": f"Basic {base64_bytes.decode('ascii')}"}


@pytest.mark.integration
def test_financialtoolkit_about_api() -> None:
    """Test FinancialToolkit about endpoint."""
    url = "http://0.0.0.0:8000/api/v1/financialtoolkit/about"
    result = requests.get(url, headers=get_headers(), timeout=10)

    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.integration
def test_financialtoolkit_models_capabilities_api() -> None:
    """Test FinancialToolkit models capabilities endpoint."""
    url = "http://0.0.0.0:8000/api/v1/financialtoolkit/models/capabilities"
    result = requests.get(url, headers=get_headers(), timeout=10)

    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.integration
def test_financialtoolkit_options_capabilities_api() -> None:
    """Test FinancialToolkit options capabilities endpoint."""
    url = "http://0.0.0.0:8000/api/v1/financialtoolkit/options/capabilities"
    result = requests.get(url, headers=get_headers(), timeout=10)

    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.integration
def test_financialtoolkit_risk_capabilities_api() -> None:
    """Test FinancialToolkit risk capabilities endpoint."""
    url = "http://0.0.0.0:8000/api/v1/financialtoolkit/risk/capabilities"
    result = requests.get(url, headers=get_headers(), timeout=10)

    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.integration
def test_financialtoolkit_performance_capabilities_api() -> None:
    """Test FinancialToolkit performance capabilities endpoint."""
    url = "http://0.0.0.0:8000/api/v1/financialtoolkit/performance/capabilities"
    result = requests.get(url, headers=get_headers(), timeout=10)

    assert isinstance(result, requests.Response)
    assert result.status_code == 200


@pytest.mark.integration
def test_financialtoolkit_discovery_capabilities_api() -> None:
    """Test FinancialToolkit discovery capabilities endpoint."""
    url = "http://0.0.0.0:8000/api/v1/financialtoolkit/discovery/capabilities"
    result = requests.get(url, headers=get_headers(), timeout=10)

    assert isinstance(result, requests.Response)
    assert result.status_code == 200
