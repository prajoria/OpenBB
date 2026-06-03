"""Validation helpers for FinancialToolkit extension commands."""

import os

from openbb_financialtoolkit.exceptions import FinancialToolkitConfigurationError


def resolve_api_key(api_key: str | None = None) -> str:
    """Resolve the FMP API key with a single, consistent contract.

    Resolution order:
    1. An explicit, non-empty ``api_key`` argument (per-command override).
    2. The ``FMP_API_KEY`` environment variable (the platform also exports
       configured ``fmp_api_key`` credentials into the environment).

    Raises ``FinancialToolkitConfigurationError`` with a clear message when no
    key is available, so every sub-router (`ratios`, `discovery`, `models`, ...)
    fails the same way instead of silently deferring to FinanceToolkit's
    internal fetch. The key is never logged.
    """
    resolved = (api_key or "").strip() or os.getenv("FMP_API_KEY", "").strip()
    if not resolved:
        raise FinancialToolkitConfigurationError(
            "An FMP API key is required. Pass `api_key=...` or configure "
            "`fmp_api_key` in OpenBB credentials / set the FMP_API_KEY "
            "environment variable."
        )
    return resolved


def validate_symbol(symbol: str) -> str:
    """Validate and normalize a symbol input."""
    normalized = symbol.strip().upper()

    if not normalized:
        raise FinancialToolkitConfigurationError("Symbol cannot be empty.")

    return normalized


def validate_symbols(symbols: list[str]) -> list[str]:
    """Validate and normalize a list of symbols."""
    normalized = [symbol.strip().upper() for symbol in symbols if symbol.strip()]

    if not normalized:
        raise FinancialToolkitConfigurationError("At least one symbol is required.")

    return normalized
