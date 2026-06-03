"""Technicals sub-router for FinancialToolkit extension."""

from openbb_core.app.model.example import APIEx, PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from openbb_core.provider.abstract.data import Data

from openbb_financialtoolkit.common.transform import records_to_data
from openbb_financialtoolkit.common.validators import validate_symbols
from openbb_financialtoolkit.technicals.technicals_models import DomainCapability
from openbb_financialtoolkit.technicals.technicals_service import TechnicalsService

router = Router(prefix="/technicals", description="FinancialToolkit technical indicators.")

_MCP_TECH = {"mcp_config": {"tags": ["financialtoolkit", "technicals"], "describe_responses": False}}


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="List available technicals commands.",
            code=["obb.financialtoolkit.technicals.capabilities()"],
        ),
        APIEx(parameters={}),
    ],
)
def capabilities() -> OBBject[list[DomainCapability]]:
    """Get available FinancialToolkit technicals capabilities."""
    return OBBject(results=TechnicalsService.capabilities())


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Collect all technical indicators.",
            code=["obb.financialtoolkit.technicals.collect_all(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def collect_all(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: int = 14,
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Collect all technical indicators in a single call."""
    records = TechnicalsService.collect_all(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        rounding=rounding,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Collect momentum indicators.",
            code=["obb.financialtoolkit.technicals.momentum(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def momentum(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: int = 14,
    close_column: str = "Adj Close",
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Collect momentum indicators (RSI, MACD, Stochastic, etc.)."""
    records = TechnicalsService.momentum(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        close_column=close_column,
        rounding=rounding,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Collect overlap indicators.",
            code=["obb.financialtoolkit.technicals.overlap(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def overlap(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: int = 14,
    close_column: str = "Adj Close",
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Collect overlap indicators (MA, EMA, Bollinger Bands, etc.)."""
    records = TechnicalsService.overlap(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        close_column=close_column,
        rounding=rounding,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Collect volatility indicators.",
            code=["obb.financialtoolkit.technicals.volatility(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def volatility(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: int = 14,
    close_column: str = "Adj Close",
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Collect volatility indicators (ATR, Keltner Channels, etc.)."""
    records = TechnicalsService.volatility(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        close_column=close_column,
        rounding=rounding,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Collect breadth indicators.",
            code=["obb.financialtoolkit.technicals.breadth(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def breadth(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: int = 14,
    close_column: str = "Adj Close",
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Collect breadth indicators (OBV, McClellan Oscillator, etc.)."""
    records = TechnicalsService.breadth(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        close_column=close_column,
        rounding=rounding,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Calculate RSI.",
            code=["obb.financialtoolkit.technicals.rsi(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def rsi(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: int = 14,
    close_column: str = "Adj Close",
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Calculate Relative Strength Index (RSI)."""
    records = TechnicalsService.rsi(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, close_column=close_column, rounding=rounding,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Calculate MACD.",
            code=["obb.financialtoolkit.technicals.macd(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def macd(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period_fast: int = 12,
    period_slow: int = 26,
    period_signal: int = 9,
    close_column: str = "Adj Close",
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Calculate Moving Average Convergence Divergence (MACD)."""
    records = TechnicalsService.macd(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period_fast=period_fast, period_slow=period_slow, period_signal=period_signal,
        close_column=close_column, rounding=rounding,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Calculate Bollinger Bands.",
            code=["obb.financialtoolkit.technicals.bollinger_bands(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def bollinger_bands(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: int = 20,
    std_dev: float = 2.0,
    close_column: str = "Adj Close",
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Calculate Bollinger Bands."""
    records = TechnicalsService.bollinger_bands(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, std_dev=std_dev, close_column=close_column, rounding=rounding,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Calculate Simple Moving Average.",
            code=["obb.financialtoolkit.technicals.moving_average(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def moving_average(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: int = 20,
    close_column: str = "Adj Close",
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Calculate Simple Moving Average (SMA)."""
    records = TechnicalsService.moving_average(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, close_column=close_column, rounding=rounding,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Calculate Exponential Moving Average.",
            code=["obb.financialtoolkit.technicals.ema(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def ema(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: int = 20,
    close_column: str = "Adj Close",
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Calculate Exponential Moving Average (EMA)."""
    records = TechnicalsService.ema(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, close_column=close_column, rounding=rounding,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Calculate Average True Range.",
            code=["obb.financialtoolkit.technicals.atr(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def atr(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: int = 14,
    close_column: str = "Adj Close",
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Calculate Average True Range (ATR)."""
    records = TechnicalsService.atr(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, close_column=close_column, rounding=rounding,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Calculate Stochastic Oscillator.",
            code=["obb.financialtoolkit.technicals.stochastic(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def stochastic(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: int = 14,
    smooth_k: int = 3,
    smooth_d: int = 3,
    close_column: str = "Adj Close",
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Calculate Stochastic Oscillator (%K and %D)."""
    records = TechnicalsService.stochastic(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, smooth_k=smooth_k, smooth_d=smooth_d,
        close_column=close_column, rounding=rounding,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Calculate Ichimoku Cloud.",
            code=["obb.financialtoolkit.technicals.ichimoku(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def ichimoku(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    conversion_period: int = 9,
    base_period: int = 26,
    lagging_period: int = 52,
    displacement: int = 26,
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Calculate Ichimoku Cloud indicator."""
    records = TechnicalsService.ichimoku(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        conversion_period=conversion_period, base_period=base_period,
        lagging_period=lagging_period, displacement=displacement, rounding=rounding,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Calculate Average Directional Index.",
            code=["obb.financialtoolkit.technicals.adx(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def adx(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: int = 14,
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Calculate Average Directional Index (ADX)."""
    records = TechnicalsService.adx(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, rounding=rounding,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Calculate On Balance Volume.",
            code=["obb.financialtoolkit.technicals.obv(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def obv(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    close_column: str = "Adj Close",
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Calculate On Balance Volume (OBV)."""
    records = TechnicalsService.obv(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        close_column=close_column, rounding=rounding,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    openapi_extra=_MCP_TECH,
    examples=[
        PythonEx(
            description="Get support and resistance levels.",
            code=["obb.financialtoolkit.technicals.support_resistance(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def support_resistance(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    close_column: str = "Adj Close",
    sensitivity: float = 0.02,
    rounding: int | None = None,
) -> OBBject[list[Data]]:
    """Calculate Support and Resistance levels."""
    records = TechnicalsService.support_resistance(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        close_column=close_column, sensitivity=sensitivity, rounding=rounding,
    )
    return OBBject(results=records_to_data(records))
