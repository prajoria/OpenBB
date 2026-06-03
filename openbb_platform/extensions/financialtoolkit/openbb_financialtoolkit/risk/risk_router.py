"""Risk sub-router for FinancialToolkit extension."""

from typing import Literal

from openbb_core.app.model.example import APIEx, PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from openbb_core.provider.abstract.data import Data
from pydantic import PositiveInt

from openbb_financialtoolkit.common.transform import records_to_data
from openbb_financialtoolkit.common.validators import validate_symbols
from openbb_financialtoolkit.risk.risk_models import DomainCapability
from openbb_financialtoolkit.risk.risk_service import RiskService

router = Router(prefix="/risk", description="FinancialToolkit risk tools.")

_MCP_RISK = {"mcp_config": {"tags": ["financialtoolkit", "risk"], "describe_responses": False}}


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_RISK,
    examples=[
        PythonEx(
            description="List scaffolded risk commands for FinancialToolkit wrapper.",
            code=["obb.financialtoolkit.risk.capabilities()"],
        ),
        APIEx(parameters={}),
    ],
)
def capabilities() -> OBBject[list[DomainCapability]]:
    """Get available and planned FinancialToolkit risk capabilities."""
    return OBBject(results=RiskService.capabilities())


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_RISK,
    examples=[
        PythonEx(
            description="Calculate Value at Risk via FinanceToolkit.",
            code=["obb.financialtoolkit.risk.var(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def var(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: Literal["daily", "weekly", "monthly", "quarterly", "yearly"] | None = None,
    alpha: float = 0.05,
    within_period: bool = True,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    distribution: Literal["historic", "gaussian", "cf", "studentt"] = "historic",
) -> OBBject[list[Data]]:
    """Calculate Value at Risk (VaR)."""
    records = RiskService.var(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        alpha=alpha,
        within_period=within_period,
        rounding=rounding,
        growth=growth,
        lag=lag,
        distribution=distribution,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_RISK,
    examples=[
        PythonEx(
            description="Calculate Conditional Value at Risk via FinanceToolkit.",
            code=["obb.financialtoolkit.risk.cvar(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def cvar(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: Literal["daily", "weekly", "monthly", "quarterly", "yearly"] | None = None,
    alpha: float = 0.05,
    within_period: bool = True,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    distribution: Literal["historic", "gaussian", "studentt", "laplace", "logistic"] = "historic",
) -> OBBject[list[Data]]:
    """Calculate Conditional Value at Risk (CVaR)."""
    records = RiskService.cvar(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        alpha=alpha,
        within_period=within_period,
        rounding=rounding,
        growth=growth,
        lag=lag,
        distribution=distribution,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_RISK,
    examples=[
        PythonEx(
            description="Calculate Entropic Value at Risk via FinanceToolkit.",
            code=["obb.financialtoolkit.risk.evar(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def evar(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: Literal["daily", "weekly", "monthly", "quarterly", "yearly"] | None = None,
    alpha: float = 0.05,
    within_period: bool = True,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
) -> OBBject[list[Data]]:
    """Calculate Entropic Value at Risk (EVaR)."""
    records = RiskService.evar(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        alpha=alpha,
        within_period=within_period,
        rounding=rounding,
        growth=growth,
        lag=lag,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_RISK,
    examples=[
        PythonEx(
            description="Calculate GARCH volatility metric via FinanceToolkit.",
            code=["obb.financialtoolkit.risk.garch(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def garch(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: Literal["daily", "weekly", "monthly", "quarterly", "yearly"] | None = None,
    time_steps: PositiveInt | None = None,
    optimization_t: PositiveInt | None = None,
    within_period: bool = False,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
) -> OBBject[list[Data]]:
    """Calculate GARCH volatility estimate."""
    records = RiskService.garch(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        time_steps=time_steps,
        optimization_t=optimization_t,
        within_period=within_period,
        rounding=rounding,
        growth=growth,
        lag=lag,
    )
    return OBBject(results=records_to_data(records))
