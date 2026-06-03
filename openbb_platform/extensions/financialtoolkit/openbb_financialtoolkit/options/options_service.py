"""Service layer for FinancialToolkit options domain."""

from typing import Any

from openbb_financialtoolkit.adapters.mapper import to_records
from openbb_financialtoolkit.adapters.toolkit_factory import create_toolkit
from openbb_financialtoolkit.common.enums import CoverageStatus
from openbb_financialtoolkit.exceptions import FinancialToolkitExecutionError
from openbb_financialtoolkit.options.options_models import DomainCapability


class OptionsService:
    """Service wrapper for FinanceToolkit options capabilities."""

    @staticmethod
    def capabilities() -> list[DomainCapability]:
        """Return currently scaffolded options capabilities."""
        return [
            DomainCapability(
                command="greeks",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit options.collect_all_greeks.",
            )
        ]

    @staticmethod
    def _options_controller(
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
        return toolkit.options

    @staticmethod
    def greeks(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        strike_price_range: float = 0.25,
        strike_step_size: int = 5,
        expiration_time_range: int = 30,
        risk_free_rate: float | None = None,
        dividend_yield: float | None = None,
        put_option: bool = False,
        show_input_info: bool = False,
        rounding: int | None = None,
    ) -> list[dict[str, Any]]:
        try:
            options = OptionsService._options_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            output = options.collect_all_greeks(
                start_date=start_date,
                strike_price_range=strike_price_range,
                strike_step_size=strike_step_size,
                expiration_time_range=expiration_time_range,
                risk_free_rate=risk_free_rate,
                dividend_yield=dividend_yield,
                put_option=put_option,
                show_input_info=show_input_info,
                rounding=rounding,
            )
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to compute options greeks: {exc}"
            ) from exc
