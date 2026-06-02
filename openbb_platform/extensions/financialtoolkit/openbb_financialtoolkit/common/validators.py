"""Validation helpers for FinancialToolkit extension commands."""

from openbb_financialtoolkit.exceptions import FinancialToolkitConfigurationError


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
