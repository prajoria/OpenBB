"""Drift-guard smoke test for the examples/ scripts (#86 Q-A A3 / §5).

For each ``examples/*.py`` script, this test imports its ``main()`` and runs it
against a synthetic ``obb`` (no live ``fmp_cached`` calls, no ``openbb.build()``,
no network) and asserts the SHAPE of the return value. The contract is "the
example signatures stay in sync with the code"; CONTENT lock-in lives in
``tests/golden/``, not here (per design §5.1).

If this test ever fails, the README/examples and the engine have drifted -- fix
one or the other, never silence the test.

Why monkeypatch the ``openbb`` module instead of the engine's ``_fetcher`` seams:
the brief's Step 3 anticipated this gap. The live ``obb.techtrade.{scan, plan,
export, simulate, validate}`` router signatures do NOT accept ``candidate_fetcher
/ signal_fetcher / level_fetcher`` kwargs -- those seams live one layer deeper
in ``engine/scan.py`` / ``engine/plan.py`` and are not plumbed through to the
user-facing OBBject routes. Each example does ``from openbb import obb`` LAZILY
inside ``main()``, so we monkeypatch ``sys.modules["openbb"]`` with a tiny shim
whose ``obb.techtrade.*`` callables return fully-formed ``OBBject``-shaped
``SimpleNamespace`` objects carrying real ``TradePlan`` / ``Order`` / ``Fill``
instances. This mirrors the ``tests/unit/test_tune_router.py`` monkeypatch
pattern (``_setup_tuned_dir`` swaps in fakes for ``pool_sector_ohlcv`` /
``fit_segment`` / ``validate_plan``) and bypasses ``obb.build()`` entirely.

The third test additionally uses the ``builtins.__import__`` blocker pattern
from ``tests/unit/test_backtest_bridge.py`` to force ``openbb_backtest`` absent,
which exercises the example's ``except TechtradeDependencyError`` degradation
path (returns None instead of raising) -- the soft-dep contract from #82.
"""

from __future__ import annotations

import builtins
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from openbb_techtrade.models import (
    EntryExitRule,
    Fill,
    IndicatorVote,
    MoverSignal,
    Order,
    Recommendation,
    TradePlan,
)

# --- Constants pinned to the #76 worked golden (same fixtures the engine tests use) ---

_AS_OF = date(2024, 1, 12)
_ENTRY = Decimal("121.40")
_STOP = Decimal("117.60")
_TARGET = Decimal("129.00")
_QTY = Decimal("263")
_RISK_PER_SHARE = Decimal("3.80")


def _votes() -> list[IndicatorVote]:
    """A minimal vote slate; just enough to make Recommendation reasoning non-empty."""
    return [
        IndicatorVote(family="trend", name="ema_cross", vote=1.0, weight=0.40),
        IndicatorVote(family="momentum", name="rsi", vote=0.5, weight=0.25),
    ]


def _signal(symbol: str = "MSFT", segment: str = "Information Technology") -> MoverSignal:
    """Build a confluence signal above ``entry_threshold`` (score 0.62 > default 0.4)."""
    return MoverSignal(
        symbol=symbol,
        segment=segment,
        as_of=_AS_OF,
        score=0.62,
        direction="long",
        votes=_votes(),
        rank_in_segment=1,
    )


def _recommendation(symbol: str = "MSFT", segment: str = "Information Technology") -> Recommendation:
    """Build a BUY recommendation pinned to the #76 worked-golden levels."""
    return Recommendation(
        symbol=symbol,
        segment=segment,
        as_of=_AS_OF,
        action="BUY",
        conviction="Medium",
        score=0.62,
        entry_price=_ENTRY,
        stop_price=_STOP,
        target_price=_TARGET,
        stop_distance_pct=0.0313,
        target_distance_pct=0.0626,
        risk_reward=2.0,
        atr=1.9,
        position_size=_QTY,
        risk_per_share=_RISK_PER_SHARE,
        risk_pct_of_notional=0.009994,
        time_stop_bars=20,
        reasoning="Synthetic plan for smoke test.",
        top_factors=["ema_cross"],
        caveats="None.",
    )


def _orders(symbol: str = "MSFT") -> list[Order]:
    """The 5 canonical legs (entry / exit_stop / exit_target / exit_time / exit_signal)."""
    return [
        Order(symbol=symbol, side="buy", quantity=_QTY, order_type="market", intent="entry"),
        Order(symbol=symbol, side="sell", quantity=_QTY, order_type="stop",
              stop_price=_STOP, intent="exit_stop"),
        Order(symbol=symbol, side="sell", quantity=_QTY, order_type="limit",
              limit_price=_TARGET, intent="exit_target"),
        Order(symbol=symbol, side="sell", quantity=_QTY, order_type="market", intent="exit_time"),
        Order(symbol=symbol, side="sell", quantity=_QTY, order_type="market", intent="exit_signal"),
    ]


def _plan(symbol: str = "MSFT", segment: str = "Information Technology") -> TradePlan:
    """Build a complete TradePlan (signal + rule + orders + recommendation) for tests."""
    return TradePlan(
        symbol=symbol,
        segment=segment,
        as_of=_AS_OF,
        signal=_signal(symbol, segment),
        rule=EntryExitRule(),
        position_size=_QTY,
        orders=_orders(symbol),
        simulated_fills=[],
        recommendation=_recommendation(symbol, segment),
    )


def _install_fake_obb(monkeypatch: pytest.MonkeyPatch, fake_obb: SimpleNamespace) -> None:
    """Install a fake ``openbb`` module so ``from openbb import obb`` returns ``fake_obb``.

    Because each example does its ``from openbb import obb`` LAZILY inside ``main()``,
    swapping ``sys.modules["openbb"]`` before calling ``main()`` is sufficient -- the
    lazy import sees our fake module and never touches the real ``obb.build()``.
    """
    fake_openbb_module = SimpleNamespace(obb=fake_obb)
    monkeypatch.setitem(sys.modules, "openbb", fake_openbb_module)


# --- examples.scan_to_excel ----------------------------------------------------


def test_scan_to_excel_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """examples/scan_to_excel.py::main runs offline and returns the workbook path.

    Drift-guard contract (design §5.2): the example chains ``scan -> export``
    without TypeError, and ``main`` returns a string ending in ``.xlsx``.
    """
    out_path = tmp_path / "wb.xlsx"
    fake_plans = [_plan("MSFT"), _plan("AAPL")]

    # The real ``export`` writes the workbook to disk before returning the path;
    # the fake replicates that contract so ``os.path.exists`` holds.
    def _fake_export(**kw: Any) -> SimpleNamespace:
        path = kw.get("path") or str(out_path)
        Path(path).write_bytes(b"PK\x03\x04 synthetic xlsx placeholder")
        return SimpleNamespace(results=str(path))

    fake_obb = SimpleNamespace(
        techtrade=SimpleNamespace(
            scan=lambda **kw: SimpleNamespace(results=fake_plans),
            export=_fake_export,
        )
    )
    _install_fake_obb(monkeypatch, fake_obb)

    from openbb_techtrade.examples import scan_to_excel

    path = scan_to_excel.main(out=out_path)

    assert isinstance(path, str)
    assert path.endswith(".xlsx")
    assert os.path.exists(path)


# --- examples.plan_one_symbol --------------------------------------------------


def test_plan_one_symbol_smoke(monkeypatch: pytest.MonkeyPatch):
    """examples/plan_one_symbol.py::main runs offline and returns a list of fills.

    Drift-guard contract: ``plan -> orders -> simulate`` chains without TypeError;
    the return is a list (the SHAPE locked here -- COUNT is asserted by the engine
    tests in test_orders.py / test_broker.py).
    """
    plan = _plan("MSFT")

    fake_fill = Fill(
        order_ref="MSFT:entry",
        timestamp="2024-01-13T14:30:00+00:00",
        symbol="MSFT",
        side="buy",
        quantity=_QTY,
        price=Decimal("121.45"),
        commission=Decimal("1.00"),
        slippage=Decimal("0.05"),
    )

    fake_obb = SimpleNamespace(
        techtrade=SimpleNamespace(
            plan=lambda **kw: SimpleNamespace(results=[plan]),
            orders=lambda **kw: SimpleNamespace(results=plan.orders),
            simulate=lambda **kw: SimpleNamespace(results=[fake_fill]),
        )
    )
    _install_fake_obb(monkeypatch, fake_obb)

    from openbb_techtrade.examples import plan_one_symbol

    fills = plan_one_symbol.main(symbol="MSFT")

    assert isinstance(fills, list)
    # SHAPE-only: every entry is a Fill; count is not asserted because a real
    # synthetic-bar window might or might not trip an entry threshold (per the
    # brief: "may be empty for a synthetic-bar window that doesn't trip an
    # entry"). The drift-guard contract is that main() returns a list[Fill],
    # not a specific count — locking the count would couple the smoke to fake
    # internals rather than the example contract.
    assert all(isinstance(f, Fill) for f in fills)


# --- examples.validate_a_plan --------------------------------------------------


def test_validate_a_plan_smoke_when_backtest_absent(monkeypatch: pytest.MonkeyPatch):
    """examples/validate_a_plan.py::main returns None cleanly when [validation] absent.

    Drift-guard contract: the example catches ``TechtradeDependencyError`` and
    degrades to a skip notice + None return (never raises). Mirrors the #82
    integration-test skipif pattern; uses the same ``builtins.__import__``
    blocker pattern as ``tests/unit/test_backtest_bridge.py`` to force the
    soft-dep absent regardless of whether it's installed locally.
    """
    plan = _plan("MSFT")

    # The example reaches ``obb.techtrade.validate`` only after ``obb.techtrade.plan``
    # produces at least one plan, so the fake_obb still needs a working ``plan``.
    # ``validate`` is on the fake too, but the import blocker below ensures the
    # real ``validate_plan`` (which the router would have called) would raise
    # TechtradeDependencyError first; here we let the fake raise it directly so
    # the test does NOT depend on the real router being wired through.
    from openbb_techtrade.validation.backtest_bridge import TechtradeDependencyError

    def _fake_validate(**kw: Any) -> SimpleNamespace:  # pragma: no cover - raises before return
        raise TechtradeDependencyError(
            "obb.techtrade.validate requires the 'openbb-backtest' extension, "
            "which is not installed. Install it with: pip install 'openbb-techtrade[validation]'"
        )

    fake_obb = SimpleNamespace(
        techtrade=SimpleNamespace(
            plan=lambda **kw: SimpleNamespace(results=[plan]),
            validate=_fake_validate,
        )
    )
    _install_fake_obb(monkeypatch, fake_obb)

    # Force openbb_backtest absent: drop any cached modules + block future imports.
    # The example's ``from openbb_techtrade.validation.backtest_bridge import
    # TechtradeDependencyError`` still works (validation module is shipped in
    # techtrade), but any deeper backtest import would fail -- this mirrors the
    # production absent-soft-dep posture even if the test environment happens
    # to have openbb-backtest installed.
    for module_name in list(sys.modules):
        if module_name.startswith("openbb_backtest"):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    real_import = builtins.__import__

    def _blocker(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("openbb_backtest"):
            raise ImportError(f"forced absent: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocker)

    from openbb_techtrade.examples import validate_a_plan

    result = validate_a_plan.main(symbol="MSFT")

    # The example caught TechtradeDependencyError and degraded to None -- the
    # drift-guard contract for absent soft-deps (the brief's "what done means").
    assert result is None
