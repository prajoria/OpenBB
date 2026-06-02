"""Data transformation helpers for FinancialToolkit wrappers."""

from typing import Any

from openbb_core.provider.abstract.data import Data


def records_to_data(records: list[dict[str, Any]]) -> list[Data]:
    """Convert record dictionaries into OpenBB Data models."""
    return [Data(**record) for record in records]


def object_to_data(payload: dict[str, Any]) -> Data:
    """Convert a dictionary payload into an OpenBB Data model."""
    return Data(**payload)
