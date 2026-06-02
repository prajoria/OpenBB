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

_MCP_PERF = {"mcp_config": {"tags": ["financialtoolkit", "performance"], "describe_responses": False}}


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_PERF,
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
    openapi_extra=_MCP_PERF,
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
    openapi_extra=_MCP_PERF,
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
    openapi_extra=_MCP_PERF,
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


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_PERF,
    examples=[
        PythonEx(
            description="Calculate alpha (excess return vs benchmark).",
            code=["obb.financialtoolkit.performance.alpha(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def alpha(
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
    """Calculate alpha (excess return relative to benchmark)."""
    records = PerformanceService.alpha(
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
    openapi_extra=_MCP_PERF,
    examples=[
        PythonEx(
            description="Calculate beta (systematic risk).",
            code=["obb.financialtoolkit.performance.beta(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def beta(
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
    """Calculate beta (systematic risk relative to benchmark)."""
    records = PerformanceService.beta(
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
    openapi_extra=_MCP_PERF,
    examples=[
        PythonEx(
            description="Calculate CAPM expected return.",
            code=["obb.financialtoolkit.performance.capm(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def capm(
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
    """Calculate Capital Asset Pricing Model (CAPM) expected return."""
    records = PerformanceService.capm(
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
    openapi_extra=_MCP_PERF,
    examples=[
        PythonEx(
            description="Calculate Jensen's Alpha.",
            code=["obb.financialtoolkit.performance.jensens_alpha(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def jensens_alpha(
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
    """Calculate Jensen's alpha."""
    records = PerformanceService.jensens_alpha(
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
    openapi_extra=_MCP_PERF,
    examples=[
        PythonEx(
            description="Calculate Treynor ratio.",
            code=["obb.financialtoolkit.performance.treynor_ratio(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def treynor_ratio(
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
    """Calculate Treynor ratio (excess return per unit of systematic risk)."""
    records = PerformanceService.treynor_ratio(
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
    openapi_extra=_MCP_PERF,
    examples=[
        PythonEx(
            description="Calculate M2 ratio.",
            code=["obb.financialtoolkit.performance.m2_ratio(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def m2_ratio(
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
    """Calculate M2 (Modigliani-Modigliani) ratio."""
    records = PerformanceService.m2_ratio(
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
    openapi_extra=_MCP_PERF,
    examples=[
        PythonEx(
            description="Calculate tracking error.",
            code=["obb.financialtoolkit.performance.tracking_error(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def tracking_error(
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
    """Calculate tracking error vs benchmark."""
    records = PerformanceService.tracking_error(
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
    openapi_extra=_MCP_PERF,
    examples=[
        PythonEx(
            description="Calculate compound growth rate (CAGR).",
            code=["obb.financialtoolkit.performance.compound_growth_rate(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def compound_growth_rate(
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
    """Calculate Compound Annual Growth Rate (CAGR)."""
    records = PerformanceService.compound_growth_rate(
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
    openapi_extra=_MCP_PERF,
    examples=[
        PythonEx(
            description="Calculate Fama-French three-factor model.",
            code=["obb.financialtoolkit.performance.fama_french(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def fama_french(
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
    """Calculate Fama-French three-factor model exposures."""
    records = PerformanceService.fama_french(
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
    openapi_extra=_MCP_PERF,
    examples=[
        PythonEx(
            description="Calculate factor correlations.",
            code=["obb.financialtoolkit.performance.factor_correlations(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def factor_correlations(
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
    """Calculate factor correlations (Fama-French factors vs portfolio returns)."""
    records = PerformanceService.factor_correlations(
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
