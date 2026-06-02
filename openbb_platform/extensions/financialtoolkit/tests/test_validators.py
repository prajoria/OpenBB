"""Unit tests for FinancialToolkit validators."""

import pytest

from openbb_financialtoolkit.common.validators import validate_symbol, validate_symbols
from openbb_financialtoolkit.exceptions import FinancialToolkitConfigurationError


def test_validate_symbol_normalizes() -> None:
    """Symbol should be normalized to uppercase."""
    assert validate_symbol(" aapl ") == "AAPL"


def test_validate_symbol_empty_raises() -> None:
    """Empty symbol should raise configuration error."""
    with pytest.raises(FinancialToolkitConfigurationError):
        validate_symbol(" ")


def test_validate_symbols_filters_and_normalizes() -> None:
    """List normalization keeps valid symbols only."""
    assert validate_symbols([" aapl ", "", "msft"]) == ["AAPL", "MSFT"]
