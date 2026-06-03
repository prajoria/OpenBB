"""Factory helpers for creating FinanceToolkit controller instances."""

import logging
from inspect import signature
from typing import Any

from openbb_financialtoolkit.exceptions import FinancialToolkitDependencyError
from openbb_financialtoolkit.common.validators import resolve_api_key

logger = logging.getLogger(__name__)


def create_toolkit(symbols: str | list[str], **kwargs: Any) -> Any:
    """Create a FinanceToolkit Toolkit instance with explicit constructor mapping.

    FinanceToolkit historically named the first argument ``tickers`` and some
    forks renamed it to ``symbols``. We resolve the keyword explicitly by
    inspecting the constructor signature and **fail loudly** if neither known
    parameter is present, rather than silently passing ``symbols`` positionally
    (which could bind to the wrong argument with no error if upstream reorders
    parameters).

    The FMP ``api_key`` (if present in ``kwargs``) is resolved through the
    shared :func:`resolve_api_key` contract so every caller fails consistently
    when no key is available.
    """
    try:
        from financetoolkit import Toolkit  # pylint: disable=import-outside-toplevel
    except ImportError as exc:  # pragma: no cover - dependency environment specific
        raise FinancialToolkitDependencyError(
            "financetoolkit is not installed or not importable."
        ) from exc

    if "api_key" in kwargs:
        kwargs["api_key"] = resolve_api_key(kwargs.get("api_key"))

    params = signature(Toolkit).parameters

    if "tickers" in params:
        logger.debug("create_toolkit: binding via 'tickers' keyword")
        return Toolkit(tickers=symbols, **kwargs)
    if "symbols" in params:
        logger.debug("create_toolkit: binding via 'symbols' keyword")
        return Toolkit(symbols=symbols, **kwargs)

    raise FinancialToolkitDependencyError(
        "Unsupported financetoolkit.Toolkit signature: expected a 'tickers' or "
        f"'symbols' parameter but found {list(params)}. The pinned FinanceToolkit "
        "version may be incompatible with this extension."
    )
