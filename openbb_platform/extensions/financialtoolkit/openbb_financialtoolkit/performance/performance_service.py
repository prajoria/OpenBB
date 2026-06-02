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
            ),
            DomainCapability(
                command="alpha",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit performance.get_alpha.",
            ),
            DomainCapability(
                command="beta",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit performance.get_beta.",
            ),
            DomainCapability(
                command="capm",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit performance.get_capital_asset_pricing_model.",
            ),
            DomainCapability(
                command="jensens_alpha",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit performance.get_jensens_alpha.",
            ),
            DomainCapability(
                command="treynor_ratio",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit performance.get_treynor_ratio.",
            ),
            DomainCapability(
                command="m2_ratio",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit performance.get_m2_ratio.",
            ),
            DomainCapability(
                command="tracking_error",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit performance.get_tracking_error.",
            ),
            DomainCapability(
                command="compound_growth_rate",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit performance.get_compound_growth_rate.",
            ),
            DomainCapability(
                command="fama_french",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit performance.get_fama_and_french_model.",
            ),
            DomainCapability(
                command="factor_correlations",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit performance.get_factor_correlations.",
            ),
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

    # --- Extended performance commands (Phase 6) ---

    @staticmethod
    def _performance_generic(
        method_name: str,
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: str | None = None,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
        **extra_kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Generic helper for performance controller method calls."""
        try:
            performance = PerformanceService._performance_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            method = getattr(performance, method_name)
            kwargs: dict[str, Any] = {}
            if period is not None:
                kwargs["period"] = period
            if rounding is not None:
                kwargs["rounding"] = rounding
            kwargs["growth"] = growth
            kwargs["lag"] = lag
            # merge any additional method-specific kwargs (remove None values)
            for k, v in extra_kwargs.items():
                if v is not None:
                    kwargs[k] = v
            output = method(**kwargs)
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to compute {method_name}: {exc}"
            ) from exc

    @staticmethod
    def alpha(
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
        """Calculate alpha (excess return vs benchmark)."""
        return PerformanceService._performance_generic(
            "get_alpha", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag)

    @staticmethod
    def beta(
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
        """Calculate beta (systematic risk vs benchmark)."""
        return PerformanceService._performance_generic(
            "get_beta", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag)

    @staticmethod
    def capm(
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
        """Calculate Capital Asset Pricing Model (CAPM) expected return."""
        return PerformanceService._performance_generic(
            "get_capital_asset_pricing_model", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag)

    @staticmethod
    def jensens_alpha(
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
        """Calculate Jensen's alpha."""
        return PerformanceService._performance_generic(
            "get_jensens_alpha", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag)

    @staticmethod
    def treynor_ratio(
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
        """Calculate Treynor ratio."""
        return PerformanceService._performance_generic(
            "get_treynor_ratio", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag)

    @staticmethod
    def m2_ratio(
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
        """Calculate M2 (Modigliani-Modigliani) ratio."""
        return PerformanceService._performance_generic(
            "get_m2_ratio", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag)

    @staticmethod
    def tracking_error(
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
        """Calculate tracking error vs benchmark."""
        return PerformanceService._performance_generic(
            "get_tracking_error", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag)

    @staticmethod
    def compound_growth_rate(
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
        """Calculate Compound Annual Growth Rate (CAGR)."""
        return PerformanceService._performance_generic(
            "get_compound_growth_rate", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag)

    @staticmethod
    def fama_french(
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
        """Calculate Fama-French three-factor model exposures."""
        return PerformanceService._performance_generic(
            "get_fama_and_french_model", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag)

    @staticmethod
    def factor_correlations(
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
        """Calculate factor correlations."""
        return PerformanceService._performance_generic(
            "get_factor_correlations", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag)
