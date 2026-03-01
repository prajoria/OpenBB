"""Service layer for FinancialToolkit performance domain."""

from typing import Any

from openbb_financialtoolkit.adapters.mapper import to_records
from openbb_financialtoolkit.adapters.toolkit_factory import create_toolkit
from openbb_financialtoolkit.common.enums import CoverageStatus
from openbb_financialtoolkit.exceptions import FinancialToolkitExecutionError
from openbb_financialtoolkit.performance.performance_models import DomainCapability


class PerformanceService:
    """Service wrapper for FinanceToolkit performance capabilities."""

    @staticmethod
    def capabilities() -> list[DomainCapability]:
        """Return currently scaffolded performance capabilities."""
        return [
            DomainCapability(
                command="risk_adjusted_return",
                coverage=CoverageStatus.implemented,
                notes="Implemented via sharpe/sortino/information ratio wrappers.",
            ),
            DomainCapability(
                command="sharpe_ratio",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit performance.get_sharpe_ratio.",
            ),
            DomainCapability(
                command="sortino_ratio",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit performance.get_sortino_ratio.",
            ),
            DomainCapability(
                command="information_ratio",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit performance.get_information_ratio.",
            )
        ]

    @staticmethod
    def _performance_controller(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
    ) -> Any:
        toolkit = create_toolkit(
            symbols=symbols,
            api_key=api_key,
            start_date=start_date,
            end_date=end_date,
            quarterly=quarterly,
        )
        return toolkit.performance

    @staticmethod
    def sharpe_ratio(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: str | None = None,
        rolling: int | None = None,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
    ) -> list[dict[str, Any]]:
        try:
            performance = PerformanceService._performance_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            output = performance.get_sharpe_ratio(
                period=period,
                rolling=rolling,
                rounding=rounding,
                growth=growth,
                lag=lag,
            )
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to compute sharpe ratio: {exc}"
            ) from exc

    @staticmethod
    def sortino_ratio(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: str | None = None,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
    ) -> list[dict[str, Any]]:
        try:
            performance = PerformanceService._performance_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            output = performance.get_sortino_ratio(
                period=period,
                rounding=rounding,
                growth=growth,
                lag=lag,
            )
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to compute sortino ratio: {exc}"
            ) from exc

    @staticmethod
    def information_ratio(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: str | None = None,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
    ) -> list[dict[str, Any]]:
        try:
            performance = PerformanceService._performance_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            output = performance.get_information_ratio(
                period=period,
                rounding=rounding,
                growth=growth,
                lag=lag,
            )
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to compute information ratio: {exc}"
            ) from exc
