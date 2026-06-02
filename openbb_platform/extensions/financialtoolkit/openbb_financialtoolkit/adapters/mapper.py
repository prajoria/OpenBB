"""Mapping helpers from FinanceToolkit outputs to OpenBB data-friendly payloads."""

from typing import Any


def to_records(payload: Any) -> list[dict[str, Any]]:
    """Normalize DataFrame-like and dict-like outputs into record dictionaries."""
    if hasattr(payload, "reset_index") and hasattr(payload, "to_dict"):
        normalized = payload.reset_index(drop=False)
        return normalized.to_dict(orient="records")

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        return [payload]

    return [{"value": payload}]
