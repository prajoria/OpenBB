"""Models sub-router for FinancialToolkit extension."""

from openbb_core.app.model.example import APIEx, PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from openbb_core.provider.abstract.data import Data
from pydantic import PositiveInt

from openbb_financialtoolkit.common.transform import records_to_data
from openbb_financialtoolkit.common.validators import validate_symbols
from openbb_financialtoolkit.models.models_models import DomainCapability
from openbb_financialtoolkit.models.models_service import ModelsService

router = Router(prefix="/models", description="FinancialToolkit company model tools.")

_MCP_MODELS = {"mcp_config": {"tags": ["financialtoolkit", "models"], "describe_responses": False}}


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_MODELS,
    examples=[
        PythonEx(
            description="List scaffolded models commands for FinancialToolkit wrapper.",
            code=["obb.financialtoolkit.models.capabilities()"],
        ),
        APIEx(parameters={}),
    ],
)
def capabilities() -> OBBject[list[DomainCapability]]:
    """Get available and planned FinancialToolkit model capabilities."""
    return OBBject(results=ModelsService.capabilities())


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_MODELS,
    examples=[
        PythonEx(
            description="Calculate Altman Z-Score using FinanceToolkit wrapper.",
            code=[
                "obb.financialtoolkit.models.altman_z_score(symbols=['AAPL','MSFT'], api_key='YOUR_FMP_KEY')"
            ],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def altman_z_score(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    diluted: bool = True,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
) -> OBBject[list[Data]]:
    """Calculate Altman Z-Score and related components."""
    validated_symbols = validate_symbols(symbols)
    records = ModelsService.altman_z_score(
        symbols=validated_symbols,
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        diluted=diluted,
        rounding=rounding,
        growth=growth,
        lag=lag,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_MODELS,
    examples=[
        PythonEx(
            description="Calculate Piotroski score using FinanceToolkit wrapper.",
            code=[
                "obb.financialtoolkit.models.piotroski_score(symbols=['AAPL','MSFT'], api_key='YOUR_FMP_KEY')"
            ],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def piotroski_score(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
) -> OBBject[list[Data]]:
    """Calculate Piotroski F-score components."""
    validated_symbols = validate_symbols(symbols)
    records = ModelsService.piotroski_score(
        symbols=validated_symbols,
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_MODELS,
    examples=[
        PythonEx(
            description="Run Dupont analysis using FinanceToolkit wrapper.",
            code=[
                "obb.financialtoolkit.models.dupont(symbols=['AAPL','MSFT'], api_key='YOUR_FMP_KEY')"
            ],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def dupont(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Calculate Dupont analysis components."""
    validated_symbols = validate_symbols(symbols)
    records = ModelsService.dupont(
        symbols=validated_symbols,
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        rounding=rounding,
        growth=growth,
        lag=lag,
        trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_MODELS,
    examples=[
        PythonEx(
            description="Calculate WACC using FinanceToolkit wrapper.",
            code=[
                "obb.financialtoolkit.models.wacc(symbols=['AAPL','MSFT'], api_key='YOUR_FMP_KEY')"
            ],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
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
    lag: PositiveInt = 1,
) -> OBBject[list[Data]]:
    """Calculate weighted average cost of capital."""
    validated_symbols = validate_symbols(symbols)
    records = ModelsService.wacc(
        symbols=validated_symbols,
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        show_full_results=show_full_results,
        diluted=diluted,
        rounding=rounding,
        growth=growth,
        lag=lag,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_MODELS,
    examples=[
        PythonEx(
            description="Calculate intrinsic valuation (DCF) using FinanceToolkit wrapper.",
            code=[
                "obb.financialtoolkit.models.intrinsic_value(symbols=['AAPL'], growth_rate=0.05, perpetual_growth_rate=0.025, weighted_average_cost_of_capital=0.09, api_key='YOUR_FMP_KEY')"
            ],
        ),
        APIEx(
            parameters={
                "symbols": ["AAPL"],
                "growth_rate": 0.05,
                "perpetual_growth_rate": 0.025,
                "weighted_average_cost_of_capital": 0.09,
            }
        ),
    ],
)
def intrinsic_value(
    symbols: list[str],
    growth_rate: float,
    perpetual_growth_rate: float,
    weighted_average_cost_of_capital: float,
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    periods: PositiveInt = 5,
    cash_flow_type: str = "Free Cash Flow",
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Calculate intrinsic valuation from discounted cash flow assumptions."""
    validated_symbols = validate_symbols(symbols)
    records = ModelsService.intrinsic_value(
        symbols=validated_symbols,
        growth_rate=growth_rate,
        perpetual_growth_rate=perpetual_growth_rate,
        weighted_average_cost_of_capital=weighted_average_cost_of_capital,
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        periods=periods,
        cash_flow_type=cash_flow_type,
        rounding=rounding,
    )
    return OBBject(results=records_to_data(records))
