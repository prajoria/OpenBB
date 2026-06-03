"""Service layer for FinancialToolkit ratios domain."""

from typing import Any

from openbb_financialtoolkit.adapters.mapper import to_records
from openbb_financialtoolkit.adapters.toolkit_factory import create_toolkit
from openbb_financialtoolkit.common.enums import CoverageStatus
from openbb_financialtoolkit.exceptions import FinancialToolkitExecutionError
from openbb_financialtoolkit.ratios.ratios_models import DomainCapability


class RatiosService:
    """Service wrapper for FinanceToolkit ratios capabilities."""

    @staticmethod
    def capabilities() -> list[DomainCapability]:
        """Return currently scaffolded ratios capabilities."""
        return [
            DomainCapability(
                command="collect_all",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.collect_all_ratios.",
            ),
            DomainCapability(
                command="efficiency",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.collect_efficiency_ratios.",
            ),
            DomainCapability(
                command="liquidity",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.collect_liquidity_ratios.",
            ),
            DomainCapability(
                command="profitability",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.collect_profitability_ratios.",
            ),
            DomainCapability(
                command="solvency",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.collect_solvency_ratios.",
            ),
            DomainCapability(
                command="valuation",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.collect_valuation_ratios.",
            ),
            DomainCapability(
                command="asset_turnover",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.get_asset_turnover_ratio.",
            ),
            DomainCapability(
                command="current_ratio",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.get_current_ratio.",
            ),
            DomainCapability(
                command="return_on_equity",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.get_return_on_equity.",
            ),
            DomainCapability(
                command="return_on_assets",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.get_return_on_assets.",
            ),
            DomainCapability(
                command="return_on_invested_capital",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.get_return_on_invested_capital.",
            ),
            DomainCapability(
                command="price_to_earnings",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.get_price_to_earnings_ratio.",
            ),
            DomainCapability(
                command="price_to_book",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.get_price_to_book_ratio.",
            ),
            DomainCapability(
                command="debt_to_equity",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.get_debt_to_equity_ratio.",
            ),
            DomainCapability(
                command="gross_margin",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.get_gross_margin.",
            ),
            DomainCapability(
                command="net_profit_margin",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.get_net_profit_margin.",
            ),
            DomainCapability(
                command="free_cash_flow_yield",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.get_free_cash_flow_yield.",
            ),
            DomainCapability(
                command="quick_ratio",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit ratios.get_quick_ratio.",
            ),
        ]

    @staticmethod
    def _ratios_controller(
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
        return toolkit.ratios

    @staticmethod
    def collect_all(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: str | None = None,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
        trailing: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect all financial ratios at once."""
        try:
            ratios = RatiosService._ratios_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            kwargs: dict[str, Any] = {}
            if period is not None:
                kwargs["period"] = period
            if rounding is not None:
                kwargs["rounding"] = rounding
            if trailing is not None:
                kwargs["trailing"] = trailing
            kwargs["growth"] = growth
            kwargs["lag"] = lag
            output = ratios.collect_all_ratios(**kwargs)
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to collect all ratios: {exc}"
            ) from exc

    @staticmethod
    def efficiency(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: str | None = None,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
        trailing: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect efficiency ratios."""
        try:
            ratios = RatiosService._ratios_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            kwargs: dict[str, Any] = {}
            if period is not None:
                kwargs["period"] = period
            if rounding is not None:
                kwargs["rounding"] = rounding
            if trailing is not None:
                kwargs["trailing"] = trailing
            kwargs["growth"] = growth
            kwargs["lag"] = lag
            output = ratios.collect_efficiency_ratios(**kwargs)
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to collect efficiency ratios: {exc}"
            ) from exc

    @staticmethod
    def liquidity(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: str | None = None,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
        trailing: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect liquidity ratios."""
        try:
            ratios = RatiosService._ratios_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            kwargs: dict[str, Any] = {}
            if period is not None:
                kwargs["period"] = period
            if rounding is not None:
                kwargs["rounding"] = rounding
            if trailing is not None:
                kwargs["trailing"] = trailing
            kwargs["growth"] = growth
            kwargs["lag"] = lag
            output = ratios.collect_liquidity_ratios(**kwargs)
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to collect liquidity ratios: {exc}"
            ) from exc

    @staticmethod
    def profitability(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: str | None = None,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
        trailing: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect profitability ratios."""
        try:
            ratios = RatiosService._ratios_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            kwargs: dict[str, Any] = {}
            if period is not None:
                kwargs["period"] = period
            if rounding is not None:
                kwargs["rounding"] = rounding
            if trailing is not None:
                kwargs["trailing"] = trailing
            kwargs["growth"] = growth
            kwargs["lag"] = lag
            output = ratios.collect_profitability_ratios(**kwargs)
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to collect profitability ratios: {exc}"
            ) from exc

    @staticmethod
    def solvency(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: str | None = None,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
        trailing: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect solvency ratios."""
        try:
            ratios = RatiosService._ratios_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            kwargs: dict[str, Any] = {}
            if period is not None:
                kwargs["period"] = period
            if rounding is not None:
                kwargs["rounding"] = rounding
            if trailing is not None:
                kwargs["trailing"] = trailing
            kwargs["growth"] = growth
            kwargs["lag"] = lag
            output = ratios.collect_solvency_ratios(**kwargs)
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to collect solvency ratios: {exc}"
            ) from exc

    @staticmethod
    def valuation(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: str | None = None,
        rounding: int | None = None,
        growth: bool = False,
        lag: int = 1,
        trailing: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect valuation ratios."""
        try:
            ratios = RatiosService._ratios_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            kwargs: dict[str, Any] = {}
            if period is not None:
                kwargs["period"] = period
            if rounding is not None:
                kwargs["rounding"] = rounding
            if trailing is not None:
                kwargs["trailing"] = trailing
            kwargs["growth"] = growth
            kwargs["lag"] = lag
            output = ratios.collect_valuation_ratios(**kwargs)
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to collect valuation ratios: {exc}"
            ) from exc

    # --- Individual ratio helpers ---

    @staticmethod
    def _single_ratio(
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
        trailing: int | None = None,
    ) -> list[dict[str, Any]]:
        """Generic helper to call any single-ratio getter on the ratios controller."""
        try:
            ratios = RatiosService._ratios_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            method = getattr(ratios, method_name)
            kwargs: dict[str, Any] = {}
            if period is not None:
                kwargs["period"] = period
            if rounding is not None:
                kwargs["rounding"] = rounding
            if trailing is not None:
                kwargs["trailing"] = trailing
            kwargs["growth"] = growth
            kwargs["lag"] = lag
            output = method(**kwargs)
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to compute {method_name}: {exc}"
            ) from exc

    @staticmethod
    def asset_turnover(symbols, api_key="", start_date=None, end_date=None,
                       quarterly=False, period=None, rounding=None,
                       growth=False, lag=1, trailing=None) -> list[dict[str, Any]]:
        """Calculate asset turnover ratio."""
        return RatiosService._single_ratio(
            "get_asset_turnover_ratio", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag, trailing)

    @staticmethod
    def current_ratio(symbols, api_key="", start_date=None, end_date=None,
                      quarterly=False, period=None, rounding=None,
                      growth=False, lag=1, trailing=None) -> list[dict[str, Any]]:
        """Calculate current ratio."""
        return RatiosService._single_ratio(
            "get_current_ratio", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag, trailing)

    @staticmethod
    def quick_ratio(symbols, api_key="", start_date=None, end_date=None,
                    quarterly=False, period=None, rounding=None,
                    growth=False, lag=1, trailing=None) -> list[dict[str, Any]]:
        """Calculate quick ratio."""
        return RatiosService._single_ratio(
            "get_quick_ratio", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag, trailing)

    @staticmethod
    def return_on_equity(symbols, api_key="", start_date=None, end_date=None,
                         quarterly=False, period=None, rounding=None,
                         growth=False, lag=1, trailing=None) -> list[dict[str, Any]]:
        """Calculate return on equity."""
        return RatiosService._single_ratio(
            "get_return_on_equity", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag, trailing)

    @staticmethod
    def return_on_assets(symbols, api_key="", start_date=None, end_date=None,
                         quarterly=False, period=None, rounding=None,
                         growth=False, lag=1, trailing=None) -> list[dict[str, Any]]:
        """Calculate return on assets."""
        return RatiosService._single_ratio(
            "get_return_on_assets", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag, trailing)

    @staticmethod
    def return_on_invested_capital(symbols, api_key="", start_date=None, end_date=None,
                                   quarterly=False, period=None, rounding=None,
                                   growth=False, lag=1, trailing=None) -> list[dict[str, Any]]:
        """Calculate return on invested capital."""
        return RatiosService._single_ratio(
            "get_return_on_invested_capital", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag, trailing)

    @staticmethod
    def price_to_earnings(symbols, api_key="", start_date=None, end_date=None,
                          quarterly=False, period=None, rounding=None,
                          growth=False, lag=1, trailing=None) -> list[dict[str, Any]]:
        """Calculate price-to-earnings ratio."""
        return RatiosService._single_ratio(
            "get_price_to_earnings_ratio", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag, trailing)

    @staticmethod
    def price_to_book(symbols, api_key="", start_date=None, end_date=None,
                      quarterly=False, period=None, rounding=None,
                      growth=False, lag=1, trailing=None) -> list[dict[str, Any]]:
        """Calculate price-to-book ratio."""
        return RatiosService._single_ratio(
            "get_price_to_book_ratio", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag, trailing)

    @staticmethod
    def debt_to_equity(symbols, api_key="", start_date=None, end_date=None,
                       quarterly=False, period=None, rounding=None,
                       growth=False, lag=1, trailing=None) -> list[dict[str, Any]]:
        """Calculate debt-to-equity ratio."""
        return RatiosService._single_ratio(
            "get_debt_to_equity_ratio", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag, trailing)

    @staticmethod
    def gross_margin(symbols, api_key="", start_date=None, end_date=None,
                     quarterly=False, period=None, rounding=None,
                     growth=False, lag=1, trailing=None) -> list[dict[str, Any]]:
        """Calculate gross margin."""
        return RatiosService._single_ratio(
            "get_gross_margin", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag, trailing)

    @staticmethod
    def net_profit_margin(symbols, api_key="", start_date=None, end_date=None,
                          quarterly=False, period=None, rounding=None,
                          growth=False, lag=1, trailing=None) -> list[dict[str, Any]]:
        """Calculate net profit margin."""
        return RatiosService._single_ratio(
            "get_net_profit_margin", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag, trailing)

    @staticmethod
    def free_cash_flow_yield(symbols, api_key="", start_date=None, end_date=None,
                             quarterly=False, period=None, rounding=None,
                             growth=False, lag=1, trailing=None) -> list[dict[str, Any]]:
        """Calculate free cash flow yield."""
        return RatiosService._single_ratio(
            "get_free_cash_flow_yield", symbols, api_key, start_date, end_date,
            quarterly, period, rounding, growth, lag, trailing)
