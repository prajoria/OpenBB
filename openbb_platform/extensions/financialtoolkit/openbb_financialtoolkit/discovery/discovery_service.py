"""Service layer for FinancialToolkit discovery domain."""

from typing import Any

from openbb_financialtoolkit.adapters.mapper import to_records
from openbb_financialtoolkit.common.enums import CoverageStatus
from openbb_financialtoolkit.exceptions import (
    FinancialToolkitConfigurationError,
    FinancialToolkitExecutionError,
)
from openbb_financialtoolkit.discovery.discovery_models import DomainCapability


class DiscoveryService:
    """Service wrapper for FinanceToolkit discovery capabilities."""

    @staticmethod
    def capabilities() -> list[DomainCapability]:
        """Return currently scaffolded discovery capabilities."""
        return [
            DomainCapability(
                command="screen",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit Discovery.get_stock_screener.",
            ),
            DomainCapability(
                command="search",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit Discovery.search_instruments.",
            ),
        ]

    @staticmethod
    def _discovery_controller(api_key: str) -> Any:
        if not api_key:
            raise FinancialToolkitConfigurationError(
                "Discovery endpoints require an API key."
            )

        try:
            from financetoolkit import Discovery  # pylint: disable=import-outside-toplevel
        except ImportError as exc:  # pragma: no cover - dependency environment specific
            raise FinancialToolkitExecutionError(
                "financetoolkit discovery dependency is unavailable."
            ) from exc

        return Discovery(api_key=api_key)

    @staticmethod
    def screen(
        api_key: str,
        market_cap_higher: int | None = None,
        market_cap_lower: int | None = None,
        price_higher: int | None = None,
        price_lower: int | None = None,
        beta_higher: int | None = None,
        beta_lower: int | None = None,
        volume_higher: int | None = None,
        volume_lower: int | None = None,
        dividend_higher: int | None = None,
        dividend_lower: int | None = None,
        is_etf: bool | None = None,
    ) -> list[dict[str, Any]]:
        try:
            discovery = DiscoveryService._discovery_controller(api_key=api_key)
            output = discovery.get_stock_screener(
                market_cap_higher=market_cap_higher,
                market_cap_lower=market_cap_lower,
                price_higher=price_higher,
                price_lower=price_lower,
                beta_higher=beta_higher,
                beta_lower=beta_lower,
                volume_higher=volume_higher,
                volume_lower=volume_lower,
                dividend_higher=dividend_higher,
                dividend_lower=dividend_lower,
                is_etf=is_etf,
            )
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to run discovery screener: {exc}"
            ) from exc

    @staticmethod
    def search(
        api_key: str,
        query: str,
        search_method: str = "name",
    ) -> list[dict[str, Any]]:
        try:
            discovery = DiscoveryService._discovery_controller(api_key=api_key)
            output = discovery.search_instruments(query=query, search_method=search_method)
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to search discovery instruments: {exc}"
            ) from exc
