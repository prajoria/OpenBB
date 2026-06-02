"""Runtime settings for the FinancialToolkit extension."""

from pydantic import BaseModel, Field


class FinancialToolkitSettings(BaseModel):
    """Configuration model for FinancialToolkit extension behavior."""

    allow_internal_fetch: bool = Field(
        default=True,
        description="Allow FinanceToolkit to fetch data internally when needed.",
    )
    mode: str = Field(
        default="strict",
        description="Execution mode for wrapper behavior (e.g., strict/compat).",
    )


DEFAULT_SETTINGS = FinancialToolkitSettings()
