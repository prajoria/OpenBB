"""Typed provider-owned routes for FMP Cached models."""

from openbb_core.app.router import Router

from openbb_fmp_cached.routers.reference_router import (
    router as reference_router,
    stock_list,
)

router = Router(
    prefix="",
    description="Typed routes for FMP and the FMP Cached provider.",
)
router.include_router(reference_router)

__all__ = ["router", "stock_list"]
