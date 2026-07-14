"""bd-cht: three parity assertions per strategy fixture triple.

Runs ``obb.pine.strategies.run_byo(source=<triple.pine>, records=<500
deterministic bars>)`` and asserts the produced (equity_curve, trades,
stats) match the recorded expected values in the triple's ``.csv``
files.

Tolerances per D5 §M2a:

* Floats: 0.1% relative (``rtol=1e-3``).
* Integer counts and trade IDs: exact match.

The trade-list assertion currently checks only trade count. The full
per-field trade comparison lands with bd-ph0's first fixture that
actually trades — the placeholder fixture in bd-cht is a never-trades
strategy, so there is nothing else to compare here yet.
"""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path

import numpy as np
import pytest

from openbb_pine.routers.strategies_router import run_byo


def _run(triple, records):
    """Invoke ``run_byo(source=..., records=..., symbol='TEST')`` synchronously."""
    source = triple.pine_path.read_text(encoding="utf-8")
    return asyncio.run(run_byo(source=source, records=records, symbol="TEST"))


def _read_equity_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return [
            {
                "bar_index": int(r["bar_index"]),
                "equity": float(r["equity"]),
                "drawdown": float(r["drawdown"]),
            }
            for r in csv.DictReader(f)
        ]


def _read_trades_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _coerce_stats_value(v: str):
    """Parse a stats CSV cell — try float, fall back to raw string."""
    if v == "" or v.lower() == "none":
        return None
    try:
        return float(v)
    except ValueError:
        return v


def _read_stats_csv(path: Path) -> dict:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1, (
        f"stats CSV must have exactly 1 data row, got {len(rows)}: {path}"
    )
    return {k: _coerce_stats_value(v) for k, v in rows[0].items()}


def test_strategy_equity_parity(strategy_conformance_triple, bars_for_triple):
    """Bar-by-bar equity match at 0.1% rtol per D5 §M2a."""
    triple = strategy_conformance_triple
    result = _run(triple, bars_for_triple)
    actual_curve = result.extra["equity_curve"]
    expected_curve = _read_equity_csv(triple.equity_path)
    assert len(actual_curve) == len(expected_curve), (
        f"{triple.name}: equity_curve length mismatch "
        f"(actual={len(actual_curve)}, expected={len(expected_curve)})"
    )
    actual_equity = np.array([r["equity"] for r in actual_curve])
    expected_equity = np.array([r["equity"] for r in expected_curve])
    np.testing.assert_allclose(
        actual_equity,
        expected_equity,
        rtol=1e-3,
        err_msg=f"{triple.name}: equity curve diverges",
    )
    actual_dd = np.array([r["drawdown"] for r in actual_curve])
    expected_dd = np.array([r["drawdown"] for r in expected_curve])
    # atol accommodates the equity=0 → drawdown=0 flat case where rtol
    # is undefined.
    np.testing.assert_allclose(
        actual_dd,
        expected_dd,
        rtol=1e-3,
        atol=1e-6,
        err_msg=f"{triple.name}: drawdown curve diverges",
    )


def test_strategy_trade_list_exact_match(
    strategy_conformance_triple, bars_for_triple
):
    """Trade count matches exactly.

    Per bd-cht scope: full per-trade field comparison (IDs, prices,
    directions) is deferred to bd-ph0's first trading fixture. The
    placeholder ships zero trades so count-parity is the only assertion
    that makes sense here — bd-ph0 tightens this to per-row field
    comparison when a real strategy with orders lands.
    """
    triple = strategy_conformance_triple
    result = _run(triple, bars_for_triple)
    actual_trades = result.extra.get("orders") or []
    expected_trades = _read_trades_csv(triple.trades_path)
    assert len(actual_trades) == len(expected_trades), (
        f"{triple.name}: trade count mismatch "
        f"(actual={len(actual_trades)}, expected={len(expected_trades)})"
    )


def test_strategy_stats_parity(strategy_conformance_triple, bars_for_triple):
    """Stats dict values match at 0.1% rtol on floats, exact on int-valued fields."""
    triple = strategy_conformance_triple
    result = _run(triple, bars_for_triple)
    actual_stats = result.extra["stats"] or {}
    expected_stats = _read_stats_csv(triple.stats_path)
    for key, expected_val in expected_stats.items():
        assert key in actual_stats, (
            f"{triple.name}: stats missing key {key!r} "
            f"(actual keys: {sorted(actual_stats)})"
        )
        actual_val = actual_stats[key]
        if expected_val is None:
            assert actual_val is None, (
                f"{triple.name}: stats.{key} expected None, got {actual_val!r}"
            )
            continue
        if isinstance(expected_val, str):
            assert actual_val == expected_val, (
                f"{triple.name}: stats.{key} = {actual_val!r} vs {expected_val!r}"
            )
            continue
        # Numeric: integer-valued expected → exact int compare; else rtol.
        try:
            ev = float(expected_val)
            av = float(actual_val) if actual_val is not None else float("nan")
        except (TypeError, ValueError):
            pytest.fail(
                f"{triple.name}: stats.{key} not numeric-coercible "
                f"(actual={actual_val!r}, expected={expected_val!r})"
            )
        if ev.is_integer() and abs(ev) < 1e15:
            assert int(round(av)) == int(round(ev)), (
                f"{triple.name}: stats.{key} = {av} vs {ev} (integer expected)"
            )
        else:
            np.testing.assert_allclose(
                av,
                ev,
                rtol=1e-3,
                atol=1e-6,
                err_msg=f"{triple.name}: stats.{key} diverges",
            )
