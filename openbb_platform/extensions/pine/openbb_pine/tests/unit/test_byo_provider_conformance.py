"""E3.3: BYODataProvider inherits pynecore.providers.Provider (mode-1,
construction-scoped) and passes the shared behavioral conformance suite
(bd-cko / E1.4)."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

pytest.importorskip("pynecore.providers")

from pynecore.providers.provider import Provider  # noqa: E402
from openbb_pine.runtime.byo_provider import BYODataProvider  # noqa: E402


def _daily_frame(
    start: datetime = datetime(2024, 1, 1, tzinfo=timezone.utc),
    rows: int = 5,
) -> pd.DataFrame:
    idx = pd.DatetimeIndex(
        [start + pd.Timedelta(days=i) for i in range(rows)], name="date"
    )
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(rows)],
            "high": [101.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
            "volume": [1_000_000.0 + i for i in range(rows)],
        },
        index=idx,
    )


# --- Subclass / signature contract ------------------------------------------


def test_byo_is_provider_subclass() -> None:
    assert issubclass(BYODataProvider, Provider), (
        "E3.3 incomplete: BYODataProvider must inherit pynecore.providers.Provider"
    )


def test_byo_stream_signature_matches_provider_base() -> None:
    import inspect

    sig = inspect.signature(BYODataProvider.stream)
    params = list(sig.parameters)
    for expected in ("symbol", "timeframe", "start", "end"):
        assert expected in params, f"missing param: {expected!r}"


def test_byo_mode1_rejects_mismatched_symbol() -> None:
    """Mode-1: stream() for a different symbol → ValueError (spec §5.2)."""
    df = _daily_frame()
    p = BYODataProvider(df, symbol="AAPL", interval="1D")
    with pytest.raises(ValueError, match="symbol|timeframe"):
        list(p.stream(symbol="MSFT", timeframe="1D"))


def test_byo_mode1_rejects_mismatched_timeframe() -> None:
    df = _daily_frame()
    p = BYODataProvider(df, symbol="AAPL", interval="1D")
    with pytest.raises(ValueError, match="timeframe|symbol"):
        list(p.stream(symbol="AAPL", timeframe="5m"))


# --- Conformance suite -------------------------------------------------------


def test_byo_passes_conformance_suite() -> None:
    from pynecore.providers.tests.test_conformance import _conformance_suite

    df = _daily_frame(rows=5)  # 2024-01-01 .. 2024-01-05 daily
    provider = BYODataProvider(df, symbol="TESTSYM", interval="1D")
    _conformance_suite(provider, closed_only=True)
