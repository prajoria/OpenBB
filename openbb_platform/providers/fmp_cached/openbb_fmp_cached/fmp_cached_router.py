"""Typed provider-owned routes for FMP Cached models."""

from openbb_core.app.router import Router

from openbb_fmp_cached.routers.analyst_router import router as analyst_router
from openbb_fmp_cached.routers.intraday_router import router as intraday_router
from openbb_fmp_cached.routers.market_performance_router import (
    router as market_performance_router,
)
from openbb_fmp_cached.routers.quote_router import router as quote_router
from openbb_fmp_cached.routers.reference_history_router import (
    router as reference_history_router,
)
from openbb_fmp_cached.routers.reference_router import (
    router as reference_router,
    stock_list,
)
from openbb_fmp_cached.routers.search_router import router as search_router
from openbb_fmp_cached.routers.statements_router import router as statements_router

router = Router(
    prefix="",
    description="Typed routes for FMP and the FMP Cached provider.",
)
router.include_router(reference_router)
router.include_router(quote_router)
router.include_router(intraday_router)
router.include_router(analyst_router)
router.include_router(market_performance_router)
router.include_router(statements_router)
router.include_router(reference_history_router)
router.include_router(search_router)

__all__ = ["router", "stock_list"]
