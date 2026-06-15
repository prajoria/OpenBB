"""Hermetic coverage for the technical leg of the #73 adapter (PRD §8/§11).

``openbb_technical`` is not installed in this checkout, so the real technical path
in :func:`technical_panel` never runs locally and its column-prefix contract would
otherwise be untested until CI. This module closes that gap **offline** by injecting
a faithful fake ``obb`` through the ``obb_loader`` seam: the fake's ``technical.*``
commands run pandas-ta-classic exactly as the first-party ``technical`` extension
does -- crucially passing ``prefix=target`` (``"close"``) on the target-based
commands (``macd`` / ``ema`` / ``rsi`` / ``bbands``), which is what renames their
output columns to ``close_MACDh_…`` / ``close_EMA_20`` / ``close_RSI_14`` /
``close_BBP_…``. The tests then assert the adapter populates every technical-covered
key (proving the prefixes match) and that those values agree with the #72 classic
builder within tolerance (proving cross-source parity), with no network or optional
extension required.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

pytest.importorskip("pandas_ta_classic")

from openbb_techtrade.engine.indicators import build_indicator_panel
from openbb_techtrade.engine.indicators_technical import technical_panel
from openbb_techtrade.models import IndicatorPanel

_AS_OF = date(2024, 1, 12)
_TOL = 1e-6

# The technical-covered keys per family (volume/candles are classic-only).
_COVERED = {
    "trend": {"macd_hist", "adx", "ema_fast", "ema_slow", "ema_cross"},
    "momentum": {"rsi", "stoch_k", "stoch_d"},
    "volatility": {"bb_pctb", "atr", "kc_upper", "kc_lower"},
}


def _rows(n: int = 220) -> list[dict]:
    """Build a deterministic synthetic OHLCV frame."""
    rng = np.random.default_rng(20240112)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.6, n))
    low = close - np.abs(rng.normal(0, 0.6, n))
    open_ = close + rng.normal(0, 0.4, n)
    vol = rng.integers(1_000, 8_000, n).astype(float)
    return [
        {"open": float(open_[i]), "high": float(high[i]), "low": float(low[i]),
         "close": float(close[i]), "volume": float(vol[i])}
        for i in range(n)
    ]


class _FakeRow:
    """A minimal ``Data``-like row exposing ``model_dump`` over a plain dict."""

    def __init__(self, mapping: dict):
        self._mapping = mapping

    def model_dump(self) -> dict:
        """Return the row's underlying mapping (mirrors pydantic ``Data``)."""
        return dict(self._mapping)


class _FakeResult:
    """A minimal OBBject-like wrapper exposing ``results`` as a list of rows."""

    def __init__(self, frame):
        self.results = [_FakeRow(rec) for rec in frame.to_dict("records")]


class _FakeTechnical:
    """Fake ``obb.technical`` reproducing the first-party command column contract.

    Each method builds the same pandas-ta-classic output the real ``technical``
    extension would: target-based commands operate on the ``close`` column with
    ``prefix="close"`` (renaming to ``close_*``), while the OHLC commands run on the
    full frame with the bare names. Results are wrapped as OBBject-like objects so
    the adapter's ``_tech_df`` reads them through ``.results`` + ``model_dump``.
    """

    @staticmethod
    def _frame(records: list[dict]):
        import pandas as pd

        return pd.DataFrame(records)

    def macd(self, *, data, fast, slow, signal):
        """Reproduce ``obb.technical.macd`` (target-based, ``close_`` prefix)."""
        df = self._frame(data)
        out = df["close"].to_frame()
        macd = out.ta.macd(fast=fast, slow=slow, signal=signal, close="close", prefix="close", talib=False)
        return _FakeResult(out.join(macd))

    def adx(self, *, data, length):
        """Reproduce ``obb.technical.adx`` (OHLC, bare ``ADX_`` prefix)."""
        df = self._frame(data)
        return _FakeResult(df.join(df.ta.adx(length=length, talib=False)))

    def ema(self, *, data, length):
        """Reproduce ``obb.technical.ema`` (target-based, ``close_`` prefix)."""
        df = self._frame(data)
        out = df["close"].to_frame()
        ema = out.ta.ema(length=length, close="close", prefix="close", talib=False)
        return _FakeResult(out.join(ema))

    def rsi(self, *, data, length):
        """Reproduce ``obb.technical.rsi`` (target-based, ``close_`` prefix)."""
        df = self._frame(data)
        out = df["close"].to_frame()
        rsi = out.ta.rsi(length=length, close="close", prefix="close", talib=False)
        return _FakeResult(out.join(rsi))

    def stoch(self, *, data, fast_k_period, slow_d_period, slow_k_period):
        """Reproduce ``obb.technical.stoch`` (OHLC, bare ``STOCH`` prefix)."""
        df = self._frame(data)
        stoch = df.ta.stoch(k=fast_k_period, d=slow_d_period, smooth_k=slow_k_period, talib=False)
        return _FakeResult(df.join(stoch))

    def bbands(self, *, data, length, std):
        """Reproduce ``obb.technical.bbands`` (target-based, ``close_`` prefix)."""
        df = self._frame(data)
        out = df["close"].to_frame()
        bb = out.ta.bbands(length=length, std=std, close="close", prefix="close", talib=False)
        return _FakeResult(out.join(bb))

    def atr(self, *, data, length):
        """Reproduce ``obb.technical.atr`` (OHLC, bare ``ATR`` prefix)."""
        df = self._frame(data)
        return _FakeResult(df.join(df.ta.atr(length=length, talib=False)))

    def kc(self, *, data, length, scalar):
        """Reproduce ``obb.technical.kc`` (OHLC, bare ``KC`` prefix)."""
        df = self._frame(data)
        return _FakeResult(df.join(df.ta.kc(length=length, scalar=scalar, talib=False)))


class _FakeObb:
    """A stand-in ``obb`` object exposing only the ``technical`` namespace."""

    technical = _FakeTechnical()


def _fake_loader() -> _FakeObb:
    """Return the fake ``obb`` for injection through the ``obb_loader`` seam."""
    return _FakeObb()


def test_technical_leg_populates_all_covered_keys():
    """Assert the injected technical leg fills every technical-covered key.

    This is the regression lock for the ``close_`` (``prefix=target``) column
    contract: a missing prefix would silently drop ``macd_hist`` / ``ema_*`` /
    ``rsi`` / ``bb_pctb`` and this assertion would fail.
    """
    panel = technical_panel("X", _AS_OF, _rows(), obb_loader=_fake_loader)
    assert isinstance(panel, IndicatorPanel)
    for family, expected in _COVERED.items():
        assert expected <= set(getattr(panel, family)), (
            f"{family}: missing {expected - set(getattr(panel, family))}"
        )


@pytest.mark.parametrize("family", ["trend", "momentum", "volatility"])
def test_technical_leg_matches_classic_within_tolerance(family):
    """Assert the injected technical leg agrees with the #72 classic builder."""
    classic = getattr(build_indicator_panel("X", _AS_OF, _rows()), family)
    tech = getattr(technical_panel("X", _AS_OF, _rows(), obb_loader=_fake_loader), family)
    assert set(tech) == set(classic), (
        f"{family}: technical keys {sorted(tech)} != classic keys {sorted(classic)}"
    )
    for key in classic:
        assert abs(classic[key] - tech[key]) <= _TOL, f"{family}.{key} diverged"


def test_technical_leg_fills_volume_and_candles_from_classic():
    """Assert volume/candles come from the classic helpers even on the technical path."""
    panel = technical_panel("X", _AS_OF, _rows(), obb_loader=_fake_loader)
    assert "obv_slope" in panel.volume and "cmf" in panel.volume


def test_broken_technical_leg_degrades_to_classic():
    """Assert a raising obb loader degrades to the byte-identical #72 panel."""
    def _boom() -> object:
        raise RuntimeError("technical exploded")

    degraded = technical_panel("X", _AS_OF, _rows(), obb_loader=_boom).model_dump()
    expected = build_indicator_panel("X", _AS_OF, _rows()).model_dump()
    assert degraded == expected
