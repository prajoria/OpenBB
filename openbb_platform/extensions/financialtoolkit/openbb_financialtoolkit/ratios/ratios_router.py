"""Ratios sub-router for FinancialToolkit extension."""

from typing import Literal

from openbb_core.app.model.example import APIEx, PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from openbb_core.provider.abstract.data import Data
from pydantic import PositiveInt

from openbb_financialtoolkit.common.transform import records_to_data
from openbb_financialtoolkit.common.validators import validate_symbols
from openbb_financialtoolkit.ratios.ratios_models import DomainCapability
from openbb_financialtoolkit.ratios.ratios_service import RatiosService

router = Router(prefix="/ratios", description="FinancialToolkit financial ratios.")

# Common type alias used across all ratio commands
_PERIOD = Literal["daily", "weekly", "monthly", "quarterly", "yearly"] | None


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="List available ratios commands.",
            code=["obb.financialtoolkit.ratios.capabilities()"],
        ),
        APIEx(parameters={}),
    ],
)
def capabilities() -> OBBject[list[DomainCapability]]:
    """Get available FinancialToolkit ratios capabilities."""
    return OBBject(results=RatiosService.capabilities())


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Collect all financial ratios via FinanceToolkit.",
            code=["obb.financialtoolkit.ratios.collect_all(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def collect_all(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Collect all financial ratios in a single call."""
    records = RatiosService.collect_all(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        rounding=rounding,
        growth=growth,
        lag=lag,
        trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Collect efficiency ratios via FinanceToolkit.",
            code=["obb.financialtoolkit.ratios.efficiency(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def efficiency(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Collect efficiency ratios (asset turnover, CCC, etc.)."""
    records = RatiosService.efficiency(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        rounding=rounding,
        growth=growth,
        lag=lag,
        trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Collect liquidity ratios via FinanceToolkit.",
            code=["obb.financialtoolkit.ratios.liquidity(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def liquidity(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Collect liquidity ratios (current, quick, cash ratio)."""
    records = RatiosService.liquidity(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        rounding=rounding,
        growth=growth,
        lag=lag,
        trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Collect profitability ratios via FinanceToolkit.",
            code=["obb.financialtoolkit.ratios.profitability(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def profitability(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Collect profitability ratios (gross margin, ROE, ROIC, etc.)."""
    records = RatiosService.profitability(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        rounding=rounding,
        growth=growth,
        lag=lag,
        trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Collect solvency ratios via FinanceToolkit.",
            code=["obb.financialtoolkit.ratios.solvency(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def solvency(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Collect solvency ratios (debt/equity, interest coverage, etc.)."""
    records = RatiosService.solvency(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        rounding=rounding,
        growth=growth,
        lag=lag,
        trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Collect valuation ratios via FinanceToolkit.",
            code=["obb.financialtoolkit.ratios.valuation(symbols=['AAPL','MSFT'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL", "MSFT"]}),
    ],
)
def valuation(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Collect valuation ratios (P/E, P/B, EV/EBITDA, etc.)."""
    records = RatiosService.valuation(
        symbols=validate_symbols(symbols),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        quarterly=quarterly,
        period=period,
        rounding=rounding,
        growth=growth,
        lag=lag,
        trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


# --- Individual single-metric commands ---


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Get asset turnover ratio.",
            code=["obb.financialtoolkit.ratios.asset_turnover(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def asset_turnover(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Calculate asset turnover ratio."""
    records = RatiosService.asset_turnover(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, rounding=rounding, growth=growth, lag=lag, trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Get current ratio.",
            code=["obb.financialtoolkit.ratios.current_ratio(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def current_ratio(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Calculate current ratio."""
    records = RatiosService.current_ratio(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, rounding=rounding, growth=growth, lag=lag, trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Get quick ratio.",
            code=["obb.financialtoolkit.ratios.quick_ratio(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def quick_ratio(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Calculate quick ratio."""
    records = RatiosService.quick_ratio(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, rounding=rounding, growth=growth, lag=lag, trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Get return on equity.",
            code=["obb.financialtoolkit.ratios.return_on_equity(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def return_on_equity(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Calculate return on equity (ROE)."""
    records = RatiosService.return_on_equity(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, rounding=rounding, growth=growth, lag=lag, trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Get return on assets.",
            code=["obb.financialtoolkit.ratios.return_on_assets(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def return_on_assets(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Calculate return on assets (ROA)."""
    records = RatiosService.return_on_assets(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, rounding=rounding, growth=growth, lag=lag, trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Get return on invested capital.",
            code=["obb.financialtoolkit.ratios.return_on_invested_capital(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def return_on_invested_capital(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Calculate return on invested capital (ROIC)."""
    records = RatiosService.return_on_invested_capital(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, rounding=rounding, growth=growth, lag=lag, trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Get price-to-earnings ratio.",
            code=["obb.financialtoolkit.ratios.price_to_earnings(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def price_to_earnings(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Calculate price-to-earnings (P/E) ratio."""
    records = RatiosService.price_to_earnings(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, rounding=rounding, growth=growth, lag=lag, trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Get price-to-book ratio.",
            code=["obb.financialtoolkit.ratios.price_to_book(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def price_to_book(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Calculate price-to-book (P/B) ratio."""
    records = RatiosService.price_to_book(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, rounding=rounding, growth=growth, lag=lag, trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Get debt-to-equity ratio.",
            code=["obb.financialtoolkit.ratios.debt_to_equity(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def debt_to_equity(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Calculate debt-to-equity ratio."""
    records = RatiosService.debt_to_equity(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, rounding=rounding, growth=growth, lag=lag, trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Get gross margin.",
            code=["obb.financialtoolkit.ratios.gross_margin(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def gross_margin(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Calculate gross margin."""
    records = RatiosService.gross_margin(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, rounding=rounding, growth=growth, lag=lag, trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Get net profit margin.",
            code=["obb.financialtoolkit.ratios.net_profit_margin(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def net_profit_margin(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Calculate net profit margin."""
    records = RatiosService.net_profit_margin(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, rounding=rounding, growth=growth, lag=lag, trailing=trailing,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Get free cash flow yield.",
            code=["obb.financialtoolkit.ratios.free_cash_flow_yield(symbols=['AAPL'])"],
        ),
        APIEx(parameters={"symbols": ["AAPL"]}),
    ],
)
def free_cash_flow_yield(
    symbols: list[str],
    api_key: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    quarterly: bool = False,
    period: _PERIOD = None,
    rounding: int | None = None,
    growth: bool = False,
    lag: PositiveInt = 1,
    trailing: PositiveInt | None = None,
) -> OBBject[list[Data]]:
    """Calculate free cash flow yield."""
    records = RatiosService.free_cash_flow_yield(
        symbols=validate_symbols(symbols), api_key=api_key,
        start_date=start_date, end_date=end_date, quarterly=quarterly,
        period=period, rounding=rounding, growth=growth, lag=lag, trailing=trailing,
    )
    return OBBject(results=records_to_data(records))
