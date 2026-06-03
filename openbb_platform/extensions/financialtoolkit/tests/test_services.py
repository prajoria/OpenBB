"""Unit tests for FinancialToolkit domain services."""

import pandas as pd

from openbb_financialtoolkit.discovery.discovery_service import DiscoveryService
from openbb_financialtoolkit.exceptions import FinancialToolkitConfigurationError
from openbb_financialtoolkit.models.models_service import ModelsService
from openbb_financialtoolkit.options.options_service import OptionsService
from openbb_financialtoolkit.performance.performance_service import PerformanceService
from openbb_financialtoolkit.risk.risk_service import RiskService


def test_models_service_capabilities_non_empty() -> None:
    """Models service should return scaffolded commands."""
    result = ModelsService.capabilities()

    assert len(result) > 0
    assert any(item.command == "altman_z_score" for item in result)


def test_options_service_has_greeks() -> None:
    """Options service should include greeks capability."""
    result = OptionsService.capabilities()

    assert any(item.command == "greeks" for item in result)


def test_risk_service_has_core_risk_models() -> None:
    """Risk service should include VaR-family capabilities."""
    result = RiskService.capabilities()

    commands = {item.command for item in result}
    assert {"var", "cvar", "evar", "garch"}.issubset(commands)


def test_performance_service_capabilities_include_ratios() -> None:
    """Performance service should expose implemented ratio capabilities."""
    result = PerformanceService.capabilities()

    commands = {item.command for item in result}
    assert {"risk_adjusted_return", "sharpe_ratio", "sortino_ratio", "information_ratio"}.issubset(commands)


def test_performance_service_capabilities_include_extended_commands() -> None:
    """Performance service should expose all Phase-6 extended commands."""
    result = PerformanceService.capabilities()

    commands = {item.command for item in result}
    expected = {
        "alpha", "beta", "capm", "jensens_alpha",
        "treynor_ratio", "m2_ratio", "tracking_error",
        "compound_growth_rate", "fama_french", "factor_correlations",
    }
    assert expected.issubset(commands), f"Missing: {expected - commands}"


def test_performance_generic_wrapper(monkeypatch) -> None:
    """_performance_generic should call the named method and return records."""

    class StubPerformance:
        """Stub performance controller with a single test method."""

        @staticmethod
        def get_alpha(**_kwargs):
            return pd.DataFrame({"AAPL": [0.05, 0.07]}, index=["2024", "2025"])

    monkeypatch.setattr(
        PerformanceService,
        "_performance_controller",
        lambda **_kwargs: StubPerformance(),
    )

    result = PerformanceService.alpha(symbols=["AAPL"])

    assert isinstance(result, list)
    assert len(result) == 2


def test_performance_beta_wrapper(monkeypatch) -> None:
    """beta() wrapper should delegate to get_beta and return records."""

    class StubPerformance:
        @staticmethod
        def get_beta(**_kwargs):
            return pd.DataFrame({"AAPL": [1.1]}, index=["2024"])

    monkeypatch.setattr(
        PerformanceService,
        "_performance_controller",
        lambda **_kwargs: StubPerformance(),
    )

    result = PerformanceService.beta(symbols=["AAPL"])

    assert isinstance(result, list)
    assert len(result) == 1


def test_performance_capm_wrapper(monkeypatch) -> None:
    """capm() should delegate to get_capital_asset_pricing_model."""

    class StubPerformance:
        @staticmethod
        def get_capital_asset_pricing_model(**_kwargs):
            return pd.DataFrame({"AAPL": [0.09]}, index=["2024"])

    monkeypatch.setattr(
        PerformanceService,
        "_performance_controller",
        lambda **_kwargs: StubPerformance(),
    )

    result = PerformanceService.capm(symbols=["AAPL"])

    assert isinstance(result, list)
    assert len(result) == 1


def test_discovery_service_capabilities_include_screen_search() -> None:
    """Discovery service should expose screen and search capabilities."""
    result = DiscoveryService.capabilities()

    commands = {item.command for item in result}
    assert {"screen", "search"}.issubset(commands)


def test_discovery_controller_requires_api_key(monkeypatch) -> None:
    """Discovery service should require api key for controller creation."""
    # Ensure no ambient FMP_API_KEY leaks in and satisfies the resolver.
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    try:
        DiscoveryService._discovery_controller(api_key="")
        assert False, "Expected FinancialToolkitConfigurationError"
    except FinancialToolkitConfigurationError:
        assert True


def test_performance_sharpe_ratio_wrapper(monkeypatch) -> None:
    """Sharpe ratio wrapper should map DataFrame output to records."""

    class StubPerformance:
        """Stub performance controller."""

        @staticmethod
        def get_sharpe_ratio(**_kwargs):
            return pd.DataFrame({"AAPL": [1.1, 1.2]}, index=["2024", "2025"])

    monkeypatch.setattr(
        PerformanceService,
        "_performance_controller",
        lambda **_kwargs: StubPerformance(),
    )

    result = PerformanceService.sharpe_ratio(symbols=["AAPL"])

    assert isinstance(result, list)
    assert len(result) == 2


def test_discovery_search_wrapper(monkeypatch) -> None:
    """Discovery search wrapper should map DataFrame output to records."""

    class StubDiscovery:
        """Stub discovery controller."""

        @staticmethod
        def search_instruments(query: str, search_method: str = "name"):
            assert query == "META"
            assert search_method == "name"
            return pd.DataFrame(
                [{"Symbol": "META", "Name": "Meta Platforms, Inc."}]
            )

    monkeypatch.setattr(
        DiscoveryService,
        "_discovery_controller",
        lambda api_key: StubDiscovery(),
    )

    result = DiscoveryService.search(api_key="key", query="META")

    assert isinstance(result, list)
    assert result[0]["Symbol"] == "META"
