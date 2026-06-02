"""FinancialToolkit Router."""

from importlib.metadata import PackageNotFoundError, version

from openbb_core.app.model.example import APIEx, PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from pydantic import BaseModel

from openbb_financialtoolkit.discovery.discovery_router import (
    router as discovery_router,
)
from openbb_financialtoolkit.models.models_router import router as models_router
from openbb_financialtoolkit.options.options_router import router as options_router
from openbb_financialtoolkit.performance.performance_router import (
    router as performance_router,
)
from openbb_financialtoolkit.risk.risk_router import router as risk_router

router = Router(prefix="", description="FinancialToolkit analysis tools.")
router.include_router(models_router)
router.include_router(options_router)
router.include_router(risk_router)
router.include_router(performance_router)
router.include_router(discovery_router)


class FinancialToolkitAbout(BaseModel):
    """General extension metadata."""

    extension_name: str
    extension_version: str
    toolkit_installed: bool
    toolkit_version: str | None = None


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="Get FinancialToolkit extension metadata.",
            code=["obb.financialtoolkit.about()"],
        ),
        APIEx(parameters={}),
    ],
)
def about() -> OBBject[FinancialToolkitAbout]:
    """Get extension and dependency metadata."""
    extension_version = "0.1.0"

    try:
        toolkit_version = version("financetoolkit")
        installed = True
    except PackageNotFoundError:
        toolkit_version = None
        installed = False

    return OBBject(
        results=FinancialToolkitAbout(
            extension_name="financialtoolkit",
            extension_version=extension_version,
            toolkit_installed=installed,
            toolkit_version=toolkit_version,
        )
    )
