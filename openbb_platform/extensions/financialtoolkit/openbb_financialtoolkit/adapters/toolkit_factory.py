"""Factory helpers for creating FinanceToolkit controller instances."""

from inspect import signature
from typing import Any

from openbb_financialtoolkit.exceptions import FinancialToolkitDependencyError


def create_toolkit(symbols: str | list[str], **kwargs: Any) -> Any:
    """Create a FinanceToolkit Toolkit instance with tolerant constructor mapping."""
    try:
        from financetoolkit import Toolkit  # pylint: disable=import-outside-toplevel
    except ImportError as exc:  # pragma: no cover - dependency environment specific
        raise FinancialToolkitDependencyError(
            "financetoolkit is not installed or not importable."
        ) from exc

    toolkit_signature = signature(Toolkit)
    params = toolkit_signature.parameters

    if "tickers" in params:
        return Toolkit(tickers=symbols, **kwargs)
    if "symbols" in params:
        return Toolkit(symbols=symbols, **kwargs)

    return Toolkit(symbols, **kwargs)
