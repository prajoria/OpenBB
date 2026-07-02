"""End-to-end test for :func:`openbb_pine.routers.run_router.run_byo`
(beads 0e9.5.61 + 0e9.11).

Proves the full compile-then-execute pipeline is wired end-to-end via
``run_byo(source, records=..., symbol=...)``: the ``_smoke.pine`` fixture
(a real Pine v6 indicator) reaches the endpoint, compiles via
``compile_pine()``, runs through ``run_compiled()`` against a BYO
``pandas.DataFrame`` (so no FMP key required), and returns an OBBject
with the D2 §6.1 shape.

Facade-split note (bead 0e9.11): the canonical single ``/pine/run``
endpoint was split into ``/pine/run`` (provider-only) + ``/pine/run_byo``
(BYO-records-only) to sidestep openbb-core's ``@validate`` union-coercion
of the ``data`` param. These tests exercise the BYO endpoint end-to-end.

FMP-provider mode is unit-tested via mock in test_routers_run.py; here we
prefer BYO to keep the integration test hermetic.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd
import pytest
from openbb_core.app.model.obbject import OBBject

from openbb_pine.routers.run_router import run_byo


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SMOKE_PINE = _REPO_ROOT / "tests" / "conformance" / "_smoke.pine"


def _run_async(coro):
    return asyncio.run(coro)


def _byo_records_5_bars() -> list[dict]:
    """Synthetic 5-bar OHLCV — enough for the smoke script's ta.sma(close, 1)."""
    return [
        {"date": "2024-01-02T00:00:00Z", "open": 100.0, "high": 102.0,
         "low":  99.5, "close": 101.5, "volume": 1_000_000},
        {"date": "2024-01-03T00:00:00Z", "open": 101.5, "high": 103.0,
         "low": 100.8, "close": 102.4, "volume": 1_100_000},
        {"date": "2024-01-04T00:00:00Z", "open": 102.4, "high": 104.5,
         "low": 101.9, "close": 104.1, "volume":   950_000},
        {"date": "2024-01-05T00:00:00Z", "open": 104.1, "high": 105.2,
         "low": 103.0, "close": 103.8, "volume": 1_200_000},
        {"date": "2024-01-08T00:00:00Z", "open": 103.8, "high": 106.0,
         "low": 103.5, "close": 105.9, "volume": 1_050_000},
    ]


@pytest.mark.integration
def test_pine_run_e2e_smoke_fixture_via_byo():
    """End-to-end: /pine/run compiles the _smoke.pine fixture and runs it
    over BYO OHLCV, returns an OBBject with .results DataFrame + .extra keys.

    This is the M1 gate (a) live proof — the compile→execute chain works
    against a real Pine v6 indicator (``plot(ta.sma(close, 1), title="sma_close")``)
    without any FMP dependency."""
    assert _SMOKE_PINE.is_file(), f"Missing conformance fixture: {_SMOKE_PINE}"
    src = _SMOKE_PINE.read_text()

    result = _run_async(run_byo(
        source=src,
        records=_byo_records_5_bars(),
        symbol="SMOKE",
    ))

    # ---- OBBject shape ----
    assert isinstance(result, OBBject), f"expected OBBject, got {type(result)}"

    # ---- .results — DataFrame with plot columns ----
    df = pd.DataFrame(result.results) if not isinstance(result.results, pd.DataFrame) else result.results
    assert len(df) > 0, "results should carry per-bar rows"
    # smoke fixture plots ta.sma(close, 1) which equals close for length=1
    plot_columns = [c for c in df.columns if c not in ("date", "timestamp", "time")]
    assert plot_columns, f"expected at least one plot column, got {list(df.columns)}"

    # ---- .extra — D2 §6.1 keys ----
    for key in ("alerts", "orders", "attribution", "compile_cache_hit",
                "exec_ms", "provider_used", "bars_consumed"):
        assert key in result.extra, f"missing .extra[{key!r}]"

    # ---- Attribution surface #1 — PRD §2.6 ----
    assert "PyneSys" in result.extra["attribution"]
    assert "https://pynesys.io" in result.extra["attribution"]

    # ---- Provider is BYO ----
    assert result.extra["provider_used"] == "byo"

    # ---- Bars consumed matches BYO row count ----
    assert result.extra["bars_consumed"] == 5

    # ---- exec_ms is present and sane ----
    # (Can be 0 on very fast cache-hit runs; can't assert > 0 without flakiness.)
    assert isinstance(result.extra["exec_ms"], int)
    assert result.extra["exec_ms"] >= 0
    assert result.extra["exec_ms"] < 30_000  # sanity: <30s wall-clock

    # ---- Indicator-mode orders is empty list per D2 §6.1 ----
    assert result.extra["orders"] == []


@pytest.mark.integration
def test_pine_run_e2e_cache_hit_on_second_call():
    """Second identical call is a cache hit — compile_pine returns from
    ~/.openbb/pine_cache/ without re-lexing/parsing/emitting."""
    src = _SMOKE_PINE.read_text()

    # First call — cache miss (or hit if a prior test warmed the cache).
    _run_async(run_byo(source=src, records=_byo_records_5_bars(), symbol="SMOKE"))
    # Second call — should be a cache hit regardless of first-call state.
    result2 = _run_async(run_byo(source=src, records=_byo_records_5_bars(), symbol="SMOKE"))

    assert result2.extra["compile_cache_hit"] is True
