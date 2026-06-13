"""DataFrame <-> Data plumbing and small numeric helpers.

Leaf-ish utilities used across components. See
``docs/designs/backtest-design/02-data-models.md``.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import TypeVar

import pandas as pd
from openbb_core.provider.abstract.data import Data

_D = TypeVar("_D", bound=Data)


def to_records(models: Sequence[Data]) -> list[dict]:
    """Serialize a sequence of ``Data`` models to plain dicts."""
    return [m.model_dump() for m in models]


def to_frame(models: Sequence[Data]) -> pd.DataFrame:
    """Build a DataFrame from a sequence of ``Data`` models."""
    return pd.DataFrame(to_records(models))


def from_frame(model_cls: type[_D], frame: pd.DataFrame) -> list[_D]:
    """Construct ``model_cls`` instances from each row of ``frame``."""
    return [model_cls(**row) for row in frame.to_dict(orient="records")]


def returns_from_prices(prices: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Simple period returns from a price series/frame (NaN-safe first row)."""
    return prices.pct_change().fillna(0.0)


def sign(value: Decimal) -> int:
    """Return -1, 0 or 1 for the sign of a ``Decimal``."""
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0
