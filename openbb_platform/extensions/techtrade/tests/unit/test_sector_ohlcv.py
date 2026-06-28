"""Unit tests for openbb_techtrade.tuning.sector_ohlcv (#83 L4, Q-B, Q-C)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest


def _synth_ohlcv(symbol: str, start: date, end: date, *, base: float = 100.0) -> pd.DataFrame:
    """Synthetic deterministic OHLCV: linearly drifting close + small daily noise.

    Used as the injected fetcher's return value so unit tests stay fully offline
    and reproducible across runs (same inputs -> same OHLCV bytes).
    """
    dates = pd.date_range(start=start, end=end, freq="B")  # business-day calendar
    n = len(dates)
    drift = np.linspace(base, base * 1.05, n)
    closes = drift + np.sin(np.arange(n) * 0.1)
    opens = closes - 0.2
    highs = closes + 0.3
    lows = closes - 0.4
    volume = np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volume},
        index=dates,
    )


def _fake_fetcher_two_symbols(symbol: str, *, start: date, end: date) -> pd.DataFrame:
    return _synth_ohlcv(symbol, start, end, base={"AAPL": 100.0, "MSFT": 200.0}.get(symbol, 50.0))


def test_pool_returns_multiindex_date_symbol(monkeypatch: pytest.MonkeyPatch):
    """L4: X is indexed by (date, symbol) with OHLCV columns."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.sector_ohlcv.universe_for_segment",
        lambda seg, source="etf_holdings": ["AAPL", "MSFT"],
    )
    from openbb_techtrade.tuning.sector_ohlcv import pool_sector_ohlcv

    X, y = pool_sector_ohlcv(
        "Information Technology",
        as_of=date(2025, 6, 20),
        horizon_years=1,
        fetcher=_fake_fetcher_two_symbols,
    )
    assert isinstance(X.index, pd.MultiIndex)
    assert list(X.index.names) == ["date", "symbol"]
    assert set(X.columns) == {"open", "high", "low", "close", "volume"}
    # Both symbols are present.
    assert set(X.index.get_level_values("symbol").unique()) == {"AAPL", "MSFT"}


def test_pool_uses_injected_fetcher_for_every_symbol(monkeypatch: pytest.MonkeyPatch):
    """The fetcher is called once per symbol with the derived start/end window."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.sector_ohlcv.universe_for_segment",
        lambda seg, source="etf_holdings": ["AAPL", "MSFT", "NVDA"],
    )
    from openbb_techtrade.tuning.sector_ohlcv import pool_sector_ohlcv

    calls: list[tuple[str, date, date]] = []

    def _spy(symbol: str, *, start: date, end: date) -> pd.DataFrame:
        calls.append((symbol, start, end))
        return _synth_ohlcv(symbol, start, end)

    pool_sector_ohlcv("IT", as_of=date(2025, 6, 20), horizon_years=2, fetcher=_spy)
    assert {c[0] for c in calls} == {"AAPL", "MSFT", "NVDA"}
    # Window: start = as_of - horizon_years, end = as_of.
    assert all(c[2] == date(2025, 6, 20) for c in calls)
    assert all(c[1] == date(2023, 6, 20) for c in calls)


def test_pool_drops_tail_rows_with_nan_forward_returns(monkeypatch: pytest.MonkeyPatch):
    """Q-B: the last `forward_horizon_bars` rows per symbol drop out of (X, y)."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.sector_ohlcv.universe_for_segment",
        lambda seg, source="etf_holdings": ["AAPL"],
    )
    from openbb_techtrade.tuning.sector_ohlcv import pool_sector_ohlcv

    horizon = 5
    X, y = pool_sector_ohlcv(
        "IT",
        as_of=date(2025, 6, 20),
        horizon_years=1,
        forward_horizon_bars=horizon,
        fetcher=_fake_fetcher_two_symbols,
    )
    # y is finite everywhere it appears (no NaN tail rows survived).
    assert y.notna().all()
    # X and y are aligned.
    assert X.index.equals(y.index)
    # The last bar in the fetcher's OHLCV is NOT in X (forward-return is NaN there).
    last_bar_in_fetch = _fake_fetcher_two_symbols(
        "AAPL", start=date(2024, 6, 20), end=date(2025, 6, 20)
    ).index.max()
    aapl_idx = X.xs("AAPL", level="symbol").index
    assert aapl_idx.max() < last_bar_in_fetch


def test_pool_y_is_cumulative_forward_return(monkeypatch: pytest.MonkeyPatch):
    """Q-B B3: y[t] == close[t + horizon] / close[t] - 1 (per-symbol cumulative)."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.sector_ohlcv.universe_for_segment",
        lambda seg, source="etf_holdings": ["AAPL"],
    )
    from openbb_techtrade.tuning.sector_ohlcv import pool_sector_ohlcv

    horizon = 5
    X, y = pool_sector_ohlcv(
        "IT", as_of=date(2025, 6, 20), horizon_years=1,
        forward_horizon_bars=horizon, fetcher=_fake_fetcher_two_symbols,
    )
    # Pick the first bar in the result and check y by hand.
    aapl = X.xs("AAPL", level="symbol")
    aapl_fetch = _fake_fetcher_two_symbols(
        "AAPL", start=date(2024, 6, 20), end=date(2025, 6, 20)
    )
    first_date = aapl.index.min()
    fetch_idx = aapl_fetch.index.get_loc(first_date)
    expected = (
        float(aapl_fetch["close"].iloc[fetch_idx + horizon])
        / float(aapl_fetch["close"].iloc[fetch_idx])
    ) - 1.0
    actual = float(y.loc[(first_date, "AAPL")])
    assert actual == pytest.approx(expected, rel=1e-9)


def test_pool_empty_universe_returns_empty_frames(monkeypatch: pytest.MonkeyPatch):
    """A segment whose universe resolver returns [] yields empty (X, y) — no raise."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.sector_ohlcv.universe_for_segment",
        lambda seg, source="etf_holdings": [],
    )
    from openbb_techtrade.tuning.sector_ohlcv import pool_sector_ohlcv

    X, y = pool_sector_ohlcv("IT", as_of=date(2025, 6, 20), horizon_years=1,
                              fetcher=_fake_fetcher_two_symbols)
    assert len(X) == 0
    assert len(y) == 0
    assert list(X.columns) == ["open", "high", "low", "close", "volume"]
