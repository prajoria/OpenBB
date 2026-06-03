"""Service layer for FinancialToolkit risk domain."""

from typing import Any

from openbb_financialtoolkit.adapters.mapper import to_records
from openbb_financialtoolkit.adapters.toolkit_factory import create_toolkit
from openbb_financialtoolkit.common.enums import CoverageStatus
from openbb_financialtoolkit.exceptions import FinancialToolkitExecutionError
from openbb_financialtoolkit.risk.risk_models import DomainCapability


class RiskService:
    """Service wrapper for FinanceToolkit risk capabilities."""

    @staticmethod
    def capabilities() -> list[DomainCapability]:
        """Return currently scaffolded risk capabilities."""
        return [
            DomainCapability(
                command="var",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit risk.get_value_at_risk.",
            ),
            DomainCapability(
                command="cvar",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit risk.get_conditional_value_at_risk.",
            ),
            DomainCapability(
                command="evar",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit risk.get_entropic_value_at_risk.",
            ),
            DomainCapability(
                command="garch",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit risk.get_garch.",
            ),
        ]

    @staticmethod
    def _risk_controller(
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
        return toolkit.risk

    @staticmethod
    def var(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: str | None = None,
        alpha: float = 0.05,
        within_period: bool = True,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
        distribution: str = "historic",
    ) -> list[dict[str, Any]]:
        try:
            risk = RiskService._risk_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            output = risk.get_value_at_risk(
                period=period,
                alpha=alpha,
                within_period=within_period,
                rounding=rounding,
                growth=growth,
                lag=lag,
                distribution=distribution,
            )
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(f"Failed to compute VaR: {exc}") from exc

    @staticmethod
    def cvar(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: str | None = None,
        alpha: float = 0.05,
        within_period: bool = True,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
        distribution: str = "historic",
    ) -> list[dict[str, Any]]:
        try:
            risk = RiskService._risk_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            output = risk.get_conditional_value_at_risk(
                period=period,
                alpha=alpha,
                within_period=within_period,
                rounding=rounding,
                growth=growth,
                lag=lag,
                distribution=distribution,
            )
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(f"Failed to compute CVaR: {exc}") from exc

    @staticmethod
    def evar(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: str | None = None,
        alpha: float = 0.05,
        within_period: bool = True,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
    ) -> list[dict[str, Any]]:
        try:
            risk = RiskService._risk_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            output = risk.get_entropic_value_at_risk(
                period=period,
                alpha=alpha,
                within_period=within_period,
                rounding=rounding,
                growth=growth,
                lag=lag,
            )
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(f"Failed to compute EVaR: {exc}") from exc

    @staticmethod
    def garch(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: str | None = None,
        time_steps: int | None = None,
        optimization_t: int | None = None,
        within_period: bool = False,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
    ) -> list[dict[str, Any]]:
        try:
            risk = RiskService._risk_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            output = risk.get_garch(
                period=period,
                time_steps=time_steps,
                optimization_t=optimization_t,
                within_period=within_period,
                rounding=rounding,
                growth=growth,
                lag=lag,
            )
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(f"Failed to compute GARCH: {exc}") from exc
