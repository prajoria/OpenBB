"""Performance sub-router for FinancialToolkit extension."""

from typing import Literal

from openbb_core.app.model.example import APIEx, PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from openbb_core.provider.abstract.data import Data
from pydantic import PositiveInt

from openbb_financialtoolkit.common.transform import records_to_data
from openbb_financialtoolkit.common.validators import validate_symbols
from openbb_financialtoolkit.performance.performance_models import DomainCapability
from openbb_financialtoolkit.performance.performance_service import PerformanceService

router = Router(prefix="/performance", description="FinancialToolkit performance tools.")


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="List performance commands for FinancialToolkit wrapper.",
            code=["obb.financialtoolkit.performance.capabilities()"],
        ),
        APIEx(parameters={}),
    ],
)
def capabilities() -> OBBject[list[DomainCapability]]:
    """Get available and planned FinancialToolkit performance capabilities."""
    return OBBject(results=PerformanceService.capabilities())


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Calculate Sharpe ratio using FinanceToolkit wrapper.",
            code=["obb.financialtoolkit.performance.sharpe_ratio(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def sharpe_ratio(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: Literal["daily", "weekly", "monthly", "quarterly", "yearly"] | None = None,
    rolling: PositiveInt | None = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
) -> OBBject[list[Data]]:
    """Calculate Sharpe ratio."""
    records = PerformanceService.sharpe_ratio(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        rolling=rolling,
        rounding=rounding,
        growth=growth,
        lag=lag,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Calculate Sortino ratio using FinanceToolkit wrapper.",
            code=["obb.financialtoolkit.performance.sortino_ratio(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def sortino_ratio(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: Literal["daily", "weekly", "monthly", "quarterly", "yearly"] | None = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
) -> OBBject[list[Data]]:
    """Calculate Sortino ratio."""
    records = PerformanceService.sortino_ratio(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        rounding=rounding,
        growth=growth,
        lag=lag,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Calculate Information ratio using FinanceToolkit wrapper.",
            code=["obb.financialtoolkit.performance.information_ratio(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def information_ratio(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: Literal["daily", "weekly", "monthly", "quarterly", "yearly"] | None = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
) -> OBBject[list[Data]]:
    """Calculate Information ratio."""
    records = PerformanceService.information_ratio(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        rounding=rounding,
        growth=growth,
        lag=lag,
    )
    return OBBject(results=records_to_data(records))
