"""Typed provider-owned routes for FMP Cached models."""

from openbb_core.app.router import Router

from openbb_fmp_cached.routers.quote_router import router as quote_router
from openbb_fmp_cached.routers.reference_history_router import (
    router as reference_history_router,
)
from openbb_fmp_cached.routers.reference_router import (
    router as reference_router,
    stock_list,
)
from openbb_fmp_cached.routers.search_router import router as search_router

router = Router(
    prefix="",
    description="Typed routes for FMP and the FMP Cached provider.",
)
router.include_router(reference_router)
router.include_router(quote_router)
router.include_router(reference_history_router)
router.include_router(search_router)

__all__ = ["router", "stock_list"]
