"""Runtime settings for the FinancialToolkit extension."""

from pydantic import BaseModel, Field


class FinancialToolkitSettings(BaseModel):
    """Configuration model for FinancialToolkit extension behavior.

    Note on credentials: the FMP API key is intentionally NOT modeled here.
    Credential resolution is centralized in
    ``openbb_financialtoolkit.common.validators.resolve_api_key`` so every
    sub-router (``ratios``, ``discovery``, ``models``, ...) shares one
    consistent contract (explicit ``api_key`` override, else ``FMP_API_KEY`` /
    configured ``fmp_api_key`` credential, else fail loudly). Centralizing this
    in the resolver keeps key handling consistent and testable rather than
    threading it through every service method.
    """

    allow_internal_fetch: bool = Field(
        default=True,
        description="Allow FinanceToolkit to fetch data internally when needed.",
    )
    mode: str = Field(
        default="strict",
        description="Execution mode for wrapper behavior (e.g., strict/compat).",
    )


DEFAULT_SETTINGS = FinancialToolkitSettings()
