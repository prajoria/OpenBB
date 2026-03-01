"""Discovery sub-router for FinancialToolkit extension."""

from typing import Literal

from openbb_core.app.model.example import APIEx, PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from openbb_core.provider.abstract.data import Data

from openbb_financialtoolkit.common.transform import records_to_data
from openbb_financialtoolkit.discovery.discovery_models import DomainCapability
from openbb_financialtoolkit.discovery.discovery_service import DiscoveryService

router = Router(prefix="/discovery", description="FinancialToolkit discovery tools.")


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="List discovery commands for FinancialToolkit wrapper.",
            code=["obb.financialtoolkit.discovery.capabilities()"],
        ),
        APIEx(parameters={}),
    ],
)
def capabilities() -> OBBject[list[DomainCapability]]:
    """Get available and planned FinancialToolkit discovery capabilities."""
    return OBBject(results=DiscoveryService.capabilities())


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Run FinanceToolkit stock screener wrapper.",
            code=[
                "obb.financialtoolkit.discovery.screen(api_key='YOUR_FMP_KEY', market_cap_higher=1000000000, is_etf=False)"
            ],
        ),
        APIEx(parameters={"api_key": "YOUR_FMP_KEY", "market_cap_higher": 1000000000}),
    ],
)
def screen(
    api_key: str,
    market_cap_higher: int | None = None,
    market_cap_lower: int | None = None,
    price_higher: int | None = None,
    price_lower: int | None = None,
    beta_higher: int | None = None,
    beta_lower: int | None = None,
    volume_higher: int | None = None,
    volume_lower: int | None = None,
    dividend_higher: int | None = None,
    dividend_lower: int | None = None,
    is_etf: bool | None = None,
) -> OBBject[list[Data]]:
    """Screen instruments using FinanceToolkit discovery criteria."""
    records = DiscoveryService.screen(
        api_key=api_key,
        market_cap_higher=market_cap_higher,
        market_cap_lower=market_cap_lower,
        price_higher=price_higher,
        price_lower=price_lower,
        beta_higher=beta_higher,
        beta_lower=beta_lower,
        volume_higher=volume_higher,
        volume_lower=volume_lower,
        dividend_higher=dividend_higher,
        dividend_lower=dividend_lower,
        is_etf=is_etf,
    )
    return OBBject(results=records_to_data(records))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Search instruments using FinanceToolkit discovery wrapper.",
            code=[
                "obb.financialtoolkit.discovery.search(api_key='YOUR_FMP_KEY', query='META', search_method='name')"
            ],
        ),
        APIEx(parameters={"api_key": "YOUR_FMP_KEY", "query": "META", "search_method": "name"}),
    ],
)
def search(
    api_key: str,
    query: str,
    search_method: Literal["symbol", "name", "cik", "cusip", "isin"] = "name",
) -> OBBject[list[Data]]:
    """Search instruments by symbol/name/cik/cusip/isin."""
    records = DiscoveryService.search(
        api_key=api_key,
        query=query,
        search_method=search_method,
    )
    return OBBject(results=records_to_data(records))
