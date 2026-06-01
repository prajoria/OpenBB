"""Options sub-router for FinancialToolkit extension."""

from openbb_core.app.model.example import APIEx, PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from openbb_core.provider.abstract.data import Data
from pydantic import PositiveInt

from openbb_financialtoolkit.common.transform import records_to_data
from openbb_financialtoolkit.common.validators import validate_symbols
from openbb_financialtoolkit.options.options_models import DomainCapability
from openbb_financialtoolkit.options.options_service import OptionsService

router = Router(prefix="/options", description="FinancialToolkit options tools.")

_MCP_OPT = {"mcp_config": {"tags": ["financialtoolkit", "options"], "describe_responses": False}}


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_OPT,
    examples=[
        PythonEx(
            description="List scaffolded options commands for FinancialToolkit wrapper.",
            code=["obb.financialtoolkit.options.capabilities()"],
        ),
        APIEx(parameters={}),
    ],
)
def capabilities() -> OBBject[list[DomainCapability]]:
    """Get available and planned FinancialToolkit options capabilities."""
    return OBBject(results=OptionsService.capabilities())


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_OPT,
    examples=[
        PythonEx(
            description="Calculate options Greeks via FinanceToolkit wrapper.",
            code=["obb.financialtoolkit.options.greeks(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def greeks(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    strike_price_range: float = 0.25,
    strike_step_size: PositiveInt = 5,
    expiration_time_range: PositiveInt = 30,
    risk_free_rate: float | None = None,
    dividend_yield: float | None = None,
    put_option: bool = False,
    show_input_info: bool = False,
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Calculate first, second and third-order Greeks."""
    records = OptionsService.greeks(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        strike_price_range=strike_price_range,
        strike_step_size=strike_step_size,
        expiration_time_range=expiration_time_range,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
        put_option=put_option,
        show_input_info=show_input_info,
        rounding=rounding,
    )
    return OBBject(results=records_to_data(records))
