"""Service layer for FinancialToolkit models domain."""

from typing import Any

from openbb_financialtoolkit.adapters.mapper import to_records
from openbb_financialtoolkit.adapters.toolkit_factory import create_toolkit
from openbb_financialtoolkit.common.enums import CoverageStatus
from openbb_financialtoolkit.exceptions import FinancialToolkitExecutionError
from openbb_financialtoolkit.models.models_models import DomainCapability


class ModelsService:
    """Service wrapper for FinanceToolkit model capabilities."""

    @staticmethod
    def capabilities() -> list[DomainCapability]:
        """Return currently scaffolded model capabilities."""
        return [
            DomainCapability(
                command="altman_z_score",
                coverage=CoverageStatus.implemented,
                notes="Implemented through FinanceToolkit models wrapper.",
            ),
            DomainCapability(
                command="piotroski_score",
                coverage=CoverageStatus.implemented,
                notes="Implemented through FinanceToolkit models wrapper.",
            ),
            DomainCapability(
                command="dupont",
                coverage=CoverageStatus.implemented,
                notes="Implemented through FinanceToolkit models wrapper.",
            ),
            DomainCapability(
                command="wacc",
                coverage=CoverageStatus.implemented,
                notes="Implemented through FinanceToolkit models wrapper.",
            ),
            DomainCapability(
                command="intrinsic_value",
                coverage=CoverageStatus.implemented,
                notes="Implemented through FinanceToolkit models wrapper.",
            ),
        ]

    @staticmethod
    def _models_controller(
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
        return toolkit.models

    @staticmethod
    def altman_z_score(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        diluted: bool = True,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
    ) -> list[dict[str, Any]]:
        try:
            models = ModelsService._models_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            output = models.get_altman_z_score(
                diluted=diluted,
                rounding=rounding,
                growth=growth,
                lag=lag,
            )
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to compute Altman Z-Score: {exc}"
            ) from exc

    @staticmethod
    def piotroski_score(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
    ) -> list[dict[str, Any]]:
        try:
            models = ModelsService._models_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            output = models.get_piotroski_score()
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to compute Piotroski score: {exc}"
            ) from exc

    @staticmethod
    def dupont(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
        trailing: int | None = None,
    ) -> list[dict[str, Any]]:
        try:
            models = ModelsService._models_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            output = models.get_dupont_analysis(
                rounding=rounding,
                growth=growth,
                lag=lag,
                trailing=trailing,
            )
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to compute Dupont analysis: {exc}"
            ) from exc

    @staticmethod
    def wacc(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        show_full_results: bool = True,
        diluted: bool = True,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
    ) -> list[dict[str, Any]]:
        try:
            models = ModelsService._models_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            output = models.get_weighted_average_cost_of_capital(
                show_full_results=show_full_results,
                diluted=diluted,
                rounding=rounding,
                growth=growth,
                lag=lag,
            )
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(f"Failed to compute WACC: {exc}") from exc

    @staticmethod
    def intrinsic_value(
        symbols: list[str],
        growth_rate: float,
        perpetual_growth_rate: float,
        weighted_average_cost_of_capital: float,
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        periods: int = 5,
        cash_flow_type: str = "Free Cash Flow",
        rounding: int | None = None,
    ) -> list[dict[str, Any]]:
        try:
            models = ModelsService._models_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            output = models.get_intrinsic_valuation(
                growth_rate=growth_rate,
                perpetual_growth_rate=perpetual_growth_rate,
                weighted_average_cost_of_capital=weighted_average_cost_of_capital,
                periods=periods,
                cash_flow_type=cash_flow_type,
                rounding=rounding,
            )
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to compute intrinsic valuation: {exc}"
            ) from exc
