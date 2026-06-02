"""Service layer for FinancialToolkit technicals domain."""

from typing import Any

from openbb_financialtoolkit.adapters.mapper import to_records
from openbb_financialtoolkit.adapters.toolkit_factory import create_toolkit
from openbb_financialtoolkit.common.enums import CoverageStatus
from openbb_financialtoolkit.exceptions import FinancialToolkitExecutionError
from openbb_financialtoolkit.technicals.technicals_models import DomainCapability


class TechnicalsService:
    """Service wrapper for FinanceToolkit technical indicators."""

    @staticmethod
    def capabilities() -> list[DomainCapability]:
        """Return currently scaffolded technicals capabilities."""
        return [
            DomainCapability(
                command="collect_all",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.collect_all_indicators.",
            ),
            DomainCapability(
                command="momentum",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.collect_momentum_indicators.",
            ),
            DomainCapability(
                command="overlap",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.collect_overlap_indicators.",
            ),
            DomainCapability(
                command="volatility",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.collect_volatility_indicators.",
            ),
            DomainCapability(
                command="breadth",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.collect_breadth_indicators.",
            ),
            DomainCapability(
                command="rsi",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.get_relative_strength_index.",
            ),
            DomainCapability(
                command="macd",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.get_moving_average_convergence_divergence.",
            ),
            DomainCapability(
                command="bollinger_bands",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.get_bollinger_bands.",
            ),
            DomainCapability(
                command="moving_average",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.get_moving_average.",
            ),
            DomainCapability(
                command="ema",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.get_exponential_moving_average.",
            ),
            DomainCapability(
                command="atr",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.get_average_true_range.",
            ),
            DomainCapability(
                command="stochastic",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.get_stochastic_oscillator.",
            ),
            DomainCapability(
                command="ichimoku",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.get_ichimoku_cloud.",
            ),
            DomainCapability(
                command="adx",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.get_average_directional_index.",
            ),
            DomainCapability(
                command="obv",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.get_on_balance_volume.",
            ),
            DomainCapability(
                command="support_resistance",
                coverage=CoverageStatus.implemented,
                notes="Wrapped to FinanceToolkit technicals.get_support_resistance_levels.",
            ),
        ]

    @staticmethod
    def _technicals_controller(
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
        return toolkit.technicals

    @staticmethod
    def collect_all(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: int = 14,
        rounding: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect all technical indicators."""
        try:
            technicals = TechnicalsService._technicals_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            kwargs: dict[str, Any] = {"period": period}
            if rounding is not None:
                kwargs["rounding"] = rounding
            output = technicals.collect_all_indicators(**kwargs)
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to collect all indicators: {exc}"
            ) from exc

    @staticmethod
    def momentum(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: int = 14,
        close_column: str = "Adj Close",
        rounding: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect momentum indicators (RSI, MACD, Stochastic, etc.)."""
        try:
            technicals = TechnicalsService._technicals_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            kwargs: dict[str, Any] = {"period": period, "close_column": close_column}
            if rounding is not None:
                kwargs["rounding"] = rounding
            output = technicals.collect_momentum_indicators(**kwargs)
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to collect momentum indicators: {exc}"
            ) from exc

    @staticmethod
    def overlap(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: int = 14,
        close_column: str = "Adj Close",
        rounding: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect overlap indicators (MA, EMA, Bollinger Bands, etc.)."""
        try:
            technicals = TechnicalsService._technicals_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            kwargs: dict[str, Any] = {"period": period, "close_column": close_column}
            if rounding is not None:
                kwargs["rounding"] = rounding
            output = technicals.collect_overlap_indicators(**kwargs)
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to collect overlap indicators: {exc}"
            ) from exc

    @staticmethod
    def volatility(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: int = 14,
        close_column: str = "Adj Close",
        rounding: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect volatility indicators (ATR, Keltner Channels, etc.)."""
        try:
            technicals = TechnicalsService._technicals_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            kwargs: dict[str, Any] = {"period": period, "close_column": close_column}
            if rounding is not None:
                kwargs["rounding"] = rounding
            output = technicals.collect_volatility_indicators(**kwargs)
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to collect volatility indicators: {exc}"
            ) from exc

    @staticmethod
    def breadth(
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        period: int = 14,
        close_column: str = "Adj Close",
        rounding: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect breadth indicators (OBV, McClellan Oscillator, etc.)."""
        try:
            technicals = TechnicalsService._technicals_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            kwargs: dict[str, Any] = {"period": period, "close_column": close_column}
            if rounding is not None:
                kwargs["rounding"] = rounding
            output = technicals.collect_breadth_indicators(**kwargs)
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to collect breadth indicators: {exc}"
            ) from exc

    # --- Individual indicator helpers ---

    @staticmethod
    def _single_indicator(
        method_name: str,
        symbols: list[str],
        api_key: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        quarterly: bool = False,
        **extra_kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Generic helper to call any single technical indicator."""
        try:
            technicals = TechnicalsService._technicals_controller(
                symbols=symbols,
                api_key=api_key,
                start_date=start_date,
                end_date=end_date,
                quarterly=quarterly,
            )
            method = getattr(technicals, method_name)
            # Remove None values to use FinanceToolkit defaults
            clean_kwargs = {k: v for k, v in extra_kwargs.items() if v is not None}
            output = method(**clean_kwargs)
            return to_records(output)
        except Exception as exc:
            raise FinancialToolkitExecutionError(
                f"Failed to compute {method_name}: {exc}"
            ) from exc

    @staticmethod
    def rsi(symbols, api_key="", start_date=None, end_date=None,
            quarterly=False, period=14, close_column="Adj Close",
            rounding=None) -> list[dict[str, Any]]:
        """Calculate Relative Strength Index (RSI)."""
        return TechnicalsService._single_indicator(
            "get_relative_strength_index", symbols, api_key, start_date, end_date,
            quarterly, period=period, close_column=close_column, rounding=rounding)

    @staticmethod
    def macd(symbols, api_key="", start_date=None, end_date=None,
             quarterly=False, period_fast=12, period_slow=26, period_signal=9,
             close_column="Adj Close", rounding=None) -> list[dict[str, Any]]:
        """Calculate MACD indicator."""
        return TechnicalsService._single_indicator(
            "get_moving_average_convergence_divergence", symbols, api_key,
            start_date, end_date, quarterly,
            period_fast=period_fast, period_slow=period_slow,
            period_signal=period_signal, close_column=close_column, rounding=rounding)

    @staticmethod
    def bollinger_bands(symbols, api_key="", start_date=None, end_date=None,
                        quarterly=False, period=20, std_dev=2,
                        close_column="Adj Close", rounding=None) -> list[dict[str, Any]]:
        """Calculate Bollinger Bands."""
        return TechnicalsService._single_indicator(
            "get_bollinger_bands", symbols, api_key, start_date, end_date,
            quarterly, period=period, std_dev=std_dev,
            close_column=close_column, rounding=rounding)

    @staticmethod
    def moving_average(symbols, api_key="", start_date=None, end_date=None,
                       quarterly=False, period=20, close_column="Adj Close",
                       rounding=None) -> list[dict[str, Any]]:
        """Calculate Simple Moving Average (SMA)."""
        return TechnicalsService._single_indicator(
            "get_moving_average", symbols, api_key, start_date, end_date,
            quarterly, period=period, close_column=close_column, rounding=rounding)

    @staticmethod
    def ema(symbols, api_key="", start_date=None, end_date=None,
            quarterly=False, period=20, close_column="Adj Close",
            rounding=None) -> list[dict[str, Any]]:
        """Calculate Exponential Moving Average (EMA)."""
        return TechnicalsService._single_indicator(
            "get_exponential_moving_average", symbols, api_key, start_date, end_date,
            quarterly, period=period, close_column=close_column, rounding=rounding)

    @staticmethod
    def atr(symbols, api_key="", start_date=None, end_date=None,
            quarterly=False, period=14, close_column="Adj Close",
            rounding=None) -> list[dict[str, Any]]:
        """Calculate Average True Range (ATR)."""
        return TechnicalsService._single_indicator(
            "get_average_true_range", symbols, api_key, start_date, end_date,
            quarterly, period=period, close_column=close_column, rounding=rounding)

    @staticmethod
    def stochastic(symbols, api_key="", start_date=None, end_date=None,
                   quarterly=False, period=14, smooth_k=3, smooth_d=3,
                   close_column="Adj Close", rounding=None) -> list[dict[str, Any]]:
        """Calculate Stochastic Oscillator."""
        return TechnicalsService._single_indicator(
            "get_stochastic_oscillator", symbols, api_key, start_date, end_date,
            quarterly, period=period, smooth_k=smooth_k, smooth_d=smooth_d,
            close_column=close_column, rounding=rounding)

    @staticmethod
    def ichimoku(symbols, api_key="", start_date=None, end_date=None,
                 quarterly=False, conversion_period=9, base_period=26,
                 lagging_period=52, displacement=26, rounding=None) -> list[dict[str, Any]]:
        """Calculate Ichimoku Cloud."""
        return TechnicalsService._single_indicator(
            "get_ichimoku_cloud", symbols, api_key, start_date, end_date,
            quarterly, conversion_period=conversion_period,
            base_period=base_period, lagging_period=lagging_period,
            displacement=displacement, rounding=rounding)

    @staticmethod
    def adx(symbols, api_key="", start_date=None, end_date=None,
            quarterly=False, period=14, rounding=None) -> list[dict[str, Any]]:
        """Calculate Average Directional Index (ADX)."""
        return TechnicalsService._single_indicator(
            "get_average_directional_index", symbols, api_key, start_date, end_date,
            quarterly, period=period, rounding=rounding)

    @staticmethod
    def obv(symbols, api_key="", start_date=None, end_date=None,
            quarterly=False, close_column="Adj Close", rounding=None) -> list[dict[str, Any]]:
        """Calculate On Balance Volume (OBV)."""
        return TechnicalsService._single_indicator(
            "get_on_balance_volume", symbols, api_key, start_date, end_date,
            quarterly, close_column=close_column, rounding=rounding)

    @staticmethod
    def support_resistance(symbols, api_key="", start_date=None, end_date=None,
                           quarterly=False, close_column="Adj Close",
                           sensitivity=0.02, rounding=None) -> list[dict[str, Any]]:
        """Calculate Support and Resistance levels."""
        return TechnicalsService._single_indicator(
            "get_support_resistance_levels", symbols, api_key, start_date, end_date,
            quarterly, close_column=close_column, sensitivity=sensitivity, rounding=rounding)
