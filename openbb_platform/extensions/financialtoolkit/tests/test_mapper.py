"""Unit tests for FinancialToolkit output mapping helpers."""

from openbb_financialtoolkit.adapters.mapper import to_records


def test_to_records_from_dict() -> None:
    """Map dictionary payload to single record list."""
    payload = {"symbol": "AAPL", "value": 123.4}

    result = to_records(payload)

    assert isinstance(result, list)
    assert result[0]["symbol"] == "AAPL"


def test_to_records_from_scalar() -> None:
    """Map scalar payload to wrapped record list."""
    result = to_records(10)

    assert result == [{"value": 10}]
