"""OpenBB Backtest extension for the OpenBB Platform."""

__version__ = "0.1.0"


def _rebuild_router_return_types() -> None:
    """Force pydantic to resolve the OBBject[X] return-annotation types
    used by this extension's routers.

    Under ``from __future__ import annotations`` in the router modules,
    ``-> OBBject[BacktestResult]`` is stored as a string ForwardRef.
    FastAPI's TypeAdapter (which drives ``app.openapi()``) then fails with:

        PydanticUserError: TypeAdapter[ForwardRef('OBBject[BacktestResult]')]
        is not fully defined

    Eagerly evaluating each OBBject[X] parameterization here — after the
    inner models are fully imported — resolves the ForwardRef and caches
    a real ``OBBject[X]`` class on ``OBBject``'s __class_getitem__ cache.
    Later TypeAdapter calls hit the cached concrete type and skip the
    unresolvable string.

    See issue #824.
    """
    from openbb_core.app.model.obbject import OBBject  # noqa: PLC0415

    from openbb_backtest.models import (  # noqa: PLC0415
        BacktestResult,
        FactorPanel,
        FactorReport,
        FoldResult,
        ReconciliationReport,
        SweepPoint,
        SweepResult,
        TearSheet,
        ValidationReport,
    )

    for _model in (
        BacktestResult, SweepResult, SweepPoint,
        ReconciliationReport, FactorPanel, FactorReport,
        ValidationReport, FoldResult, TearSheet,
    ):
        _parameterized = OBBject[_model]
        if hasattr(_parameterized, "model_rebuild"):
            try:
                _parameterized.model_rebuild()
            except Exception:  # noqa: BLE001
                pass


_rebuild_router_return_types()
