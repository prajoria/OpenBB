"""Unit tests for the #82 backtest_bridge (PRD §15, design §5).

Fully offline + deterministic. Asserts:

- ``plan_to_config`` translates a TradePlan into a BacktestConfig with the right
  universe / window / strategy (§3, Q-B).
- ``_start_date`` handles the Feb-29 leap-day edge.
- ``_strategy_params`` threads the rule's ``entry_threshold``.
- ``TechtradeDependencyError`` is a subclass of ``OpenBBError`` with the
  ``pip install`` hint (Q-A).
- **Degradation:** when ``openbb_backtest`` is forced un-importable
  (monkeypatch sys.modules), ``validate_plan`` raises ``TechtradeDependencyError``
  AND every *other* techtrade module still imports and is callable -- the
  #85 core-unchanged-when-removed discipline (Q-F).
- **Attach via model_copy:** with a faked ``validate``, the bridge returns a plan
  whose ``.validation`` is the report (immutable; original plan unchanged).
- Method/thresholds/horizon/provider arguments are forwarded verbatim.
"""

from __future__ import annotations

import asyncio
import builtins
import importlib
import sys
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_techtrade.models import (
    EntryExitRule,
    IndicatorVote,
    MoverSignal,
    Recommendation,
    TradePlan,
)
from openbb_techtrade.validation.backtest_bridge import (
    DEFAULT_HORIZON_YEARS,
    STRATEGY_NAME,
    TechtradeDependencyError,
    _start_date,
    _strategy_params,
    plan_to_config,
    validate_plan,
)

# --- Constants ---------------------------------------------------------------------------------

_AS_OF = date(2024, 1, 12)
_ENTRY = Decimal("121.40")
_STOP = Decimal("117.60")
_TARGET = Decimal("129.00")
_QTY = Decimal("263")


def _votes() -> list[IndicatorVote]:
    return [
        IndicatorVote(family="trend", name="macd_hist", vote=1.0, weight=0.40),
        IndicatorVote(family="momentum", name="rsi", vote=0.8, weight=0.25),
        IndicatorVote(family="volume", name="obv_slope", vote=1.0, weight=0.15),
    ]


def _plan(
    symbol: str = "NVDA",
    as_of: date = _AS_OF,
    *,
    entry_threshold: float = 0.4,
) -> TradePlan:
    """Build a paper-filled TradePlan for bridge translation tests."""
    sig = MoverSignal(
        symbol=symbol, segment="IT", as_of=as_of,
        score=0.78, direction="long", votes=_votes(), rank_in_segment=1,
    )
    rec = Recommendation(
        symbol=symbol, segment="IT", as_of=as_of,
        action="BUY", conviction="High", score=0.78,
        entry_price=_ENTRY, stop_price=_STOP, target_price=_TARGET,
        stop_distance_pct=0.0313, target_distance_pct=0.0626, risk_reward=2.0, atr=1.9,
        position_size=_QTY, risk_per_share=Decimal("3.80"),
        risk_pct_of_notional=0.009994, time_stop_bars=20,
        reasoning="", top_factors=[], caveats="None.",
    )
    return TradePlan(
        symbol=symbol, segment="IT", as_of=as_of,
        signal=sig, rule=EntryExitRule(entry_threshold=entry_threshold),
        position_size=_QTY, orders=[], simulated_fills=[], recommendation=rec,
    )


class _FakeBacktestConfig:
    """A duck-typed stand-in for openbb_backtest.models.BacktestConfig.

    Used so the translation unit tests don't require openbb-backtest to be installed.
    Captures every kwarg the bridge passes in so the test can assert on them.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


# --- TechtradeDependencyError --------------------------------------------------------------------


def test_dependency_error_is_openbb_error_subclass():
    """Q-A: TechtradeDependencyError subclasses OpenBBError so existing handlers catch it."""
    assert issubclass(TechtradeDependencyError, OpenBBError)


def test_dependency_error_message_carries_pip_hint(monkeypatch: pytest.MonkeyPatch):
    """Q-A: the error message contains a ready-to-run 'pip install' command.

    Forces openbb_backtest's import to fail (the real condition the user hits) and
    asserts the bridge wraps the ImportError into a TechtradeDependencyError with
    the actionable hint.
    """
    # Drop every backtest module so the next import retries from scratch.
    for module_name in list(sys.modules):
        if module_name.startswith("openbb_backtest"):
            monkeypatch.delitem(sys.modules, module_name, raising=False)
    real_import = builtins.__import__

    def _blocking_import(name: str, *args: Any, **kwargs: Any):
        if name.startswith("openbb_backtest"):
            raise ImportError(f"forced absent: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocking_import)

    plan = _plan()
    with pytest.raises(TechtradeDependencyError) as excinfo:
        asyncio.run(validate_plan(plan))
    msg = str(excinfo.value)
    assert "openbb-backtest" in msg
    assert "pip install" in msg


# --- Degradation discipline (#85 core-unchanged-when-removed) ------------------------------------


def test_degradation_other_modules_still_import(monkeypatch: pytest.MonkeyPatch):
    """Q-F: forcing openbb_backtest absent does NOT break techtrade's non-validation surface.

    The bridge raises TechtradeDependencyError on validate_plan, but every other
    techtrade module still imports cleanly. This is the discipline enforced by #85.
    """
    # Force any future ``import openbb_backtest`` to fail.
    real_import = builtins.__import__

    def _blocking_import(name: str, *args: Any, **kwargs: Any):
        if name.startswith("openbb_backtest"):
            raise ImportError(f"forced absent: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocking_import)
    # Drop any cached backtest modules so the next import goes through our blocker.
    for module_name in list(sys.modules):
        if module_name.startswith("openbb_backtest"):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    # 1. Every other techtrade module still imports cleanly.
    for module_name in (
        "openbb_techtrade",
        "openbb_techtrade.engine.plan",
        "openbb_techtrade.engine.scan",
        "openbb_techtrade.engine.signals",
        "openbb_techtrade.engine.execution",
        "openbb_techtrade.reporting.excel_export",
    ):
        importlib.import_module(module_name)

    # 2. validate_plan raises TechtradeDependencyError with the actionable hint.
    plan = _plan()
    with pytest.raises(TechtradeDependencyError) as excinfo:
        asyncio.run(validate_plan(plan))
    assert "pip install" in str(excinfo.value)


# --- plan_to_config translation -----------------------------------------------------------------


def test_plan_to_config_universe_is_single_symbol():
    """§3: universe = [plan.symbol]."""
    cfg = plan_to_config(_plan(symbol="NVDA"), BacktestConfig=_FakeBacktestConfig)
    assert cfg.universe == ["NVDA"]


def test_plan_to_config_end_is_as_of_and_start_is_as_of_minus_horizon():
    """§3 / Q-B: end = as_of; start = as_of - horizon_years."""
    cfg = plan_to_config(_plan(), horizon_years=5, BacktestConfig=_FakeBacktestConfig)
    assert cfg.end == _AS_OF
    assert cfg.start == date(2019, 1, 12)


def test_plan_to_config_strategy_name_is_techtrade_confluence():
    """Q-B B2: the registered strategy name is the techtrade_confluence singleton."""
    cfg = plan_to_config(_plan(), BacktestConfig=_FakeBacktestConfig)
    assert cfg.strategy == STRATEGY_NAME == "techtrade_confluence"


def test_plan_to_config_default_horizon_is_five_years():
    """Q-B answer 3: shipped default horizon is 5y."""
    assert DEFAULT_HORIZON_YEARS == 5


def test_plan_to_config_horizon_argument_overrides_default():
    """Q-B: caller can override horizon_years per-call."""
    cfg = plan_to_config(_plan(), horizon_years=3, BacktestConfig=_FakeBacktestConfig)
    assert cfg.start == date(2021, 1, 12)


def test_start_date_handles_leap_day():
    """_start_date must not raise on Feb-29 landing in a non-leap year."""
    # 2024-02-29 - 1y -> 2023-02-29 doesn't exist; the helper falls back to Mar 1.
    leap_as_of = date(2024, 2, 29)
    result = _start_date(leap_as_of, horizon_years=1)
    assert result == date(2023, 3, 1)


def test_start_date_normal_case():
    """_start_date returns as_of.replace(year=year-h) for non-leap edges."""
    assert _start_date(_AS_OF, horizon_years=5) == date(2019, 1, 12)
    assert _start_date(_AS_OF, horizon_years=1) == date(2023, 1, 12)


def test_strategy_params_threads_entry_threshold():
    """The strategy_params dict includes the rule's entry_threshold (not the default)."""
    params = _strategy_params(_plan(entry_threshold=0.55))
    assert params["entry_threshold"] == 0.55
    assert params["symbols"] == ["NVDA"]


# --- validate_plan attach + return (Q-D) ---------------------------------------------------------


def _fake_validate_factory(report: Any):
    """Build an awaitable validate fake that returns an OBBject-shaped object."""

    async def _validate(*, config: Any, method: str, thresholds: Any, strategy_params: Any, provider: Any):
        return SimpleNamespace(
            results=report,
            captured=SimpleNamespace(
                config=config, method=method, thresholds=thresholds,
                strategy_params=strategy_params, provider=provider,
            ),
        )

    return _validate


def test_validate_plan_attaches_report_via_model_copy(monkeypatch: pytest.MonkeyPatch):
    """Q-D: the bridge returns a plan whose .validation is the report (immutable copy)."""
    fake_report = SimpleNamespace(verdict="robust")

    monkeypatch.setattr(
        "openbb_techtrade.validation.backtest_bridge._require_backtest",
        lambda: (_FakeBacktestConfig, _fake_validate_factory(fake_report)),
    )

    plan = _plan()
    original_snapshot = plan.model_dump()
    updated, returned_report = asyncio.run(validate_plan(plan, method="wfo"))
    # Original plan unmutated.
    assert plan.model_dump() == original_snapshot
    # Updated plan carries the report.
    assert updated.validation is fake_report
    assert returned_report is fake_report


def test_validate_plan_forwards_method_thresholds_horizon_provider(monkeypatch: pytest.MonkeyPatch):
    """Q-C / Q-D: method / thresholds / horizon_years / provider flow through verbatim."""
    captured: dict[str, Any] = {}

    async def _capture(*, config: Any, method: str, thresholds: Any, strategy_params: Any, provider: Any):
        captured.update(
            config=config, method=method, thresholds=thresholds,
            strategy_params=strategy_params, provider=provider,
        )
        return SimpleNamespace(results=SimpleNamespace(verdict="robust"))

    monkeypatch.setattr(
        "openbb_techtrade.validation.backtest_bridge._require_backtest",
        lambda: (_FakeBacktestConfig, _capture),
    )

    plan = _plan(entry_threshold=0.42)
    custom_thresh = {"pbo_robust": 0.1, "dsr_robust": 0.99}
    asyncio.run(validate_plan(
        plan, method="cpcv", thresholds=custom_thresh,
        horizon_years=3, provider="fmp_cached",
    ))
    assert captured["method"] == "cpcv"
    assert captured["thresholds"] == custom_thresh
    assert captured["provider"] == "fmp_cached"
    assert captured["strategy_params"]["entry_threshold"] == 0.42
    assert captured["strategy_params"]["symbols"] == ["NVDA"]
    # horizon flows via config.start
    assert captured["config"].start == date(2021, 1, 12)


def test_validate_plan_default_method_is_wfo(monkeypatch: pytest.MonkeyPatch):
    """Q-C: default method is 'wfo'."""
    captured: dict[str, Any] = {}

    async def _capture(*, config, method, thresholds, strategy_params, provider):
        captured["method"] = method
        return SimpleNamespace(results=SimpleNamespace(verdict="robust"))

    monkeypatch.setattr(
        "openbb_techtrade.validation.backtest_bridge._require_backtest",
        lambda: (_FakeBacktestConfig, _capture),
    )
    asyncio.run(validate_plan(_plan()))
    assert captured["method"] == "wfo"


# --- #83 extension: both extras absent at once (joint truth-table row) ---------------------------


def test_degradation_with_tuneta_also_absent(monkeypatch: pytest.MonkeyPatch):
    """#83 Q-G: extend the #82 truth table -- with BOTH openbb_backtest AND tuneta absent,
    every other techtrade module still imports cleanly (the #85 core-unchanged-when-removed
    discipline applied to both optional extras at once).
    """
    real_import = builtins.__import__

    def _blocker(name: str, *args: Any, **kwargs: Any):
        if name.startswith("openbb_backtest") or name.startswith("tuneta"):
            raise ImportError(f"forced absent: {name}")
        return real_import(name, *args, **kwargs)

    for module_name in list(sys.modules):
        if module_name.startswith("openbb_backtest") or module_name.startswith("tuneta"):
            monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.setattr(builtins, "__import__", _blocker)

    # Every techtrade module -- including the NEW tuning ones -- must still import.
    for module_name in (
        "openbb_techtrade",
        "openbb_techtrade.engine.plan",
        "openbb_techtrade.engine.scan",
        "openbb_techtrade.engine.signals",
        "openbb_techtrade.engine.execution",
        "openbb_techtrade.reporting.excel_export",
        # NEW for #83:
        "openbb_techtrade.tuning",
        "openbb_techtrade.tuning.tuned_defaults",
        "openbb_techtrade.tuning.sector_ohlcv",
        "openbb_techtrade.tuning.tuneta_adapter",  # the only tuneta-touching module -- must still import
    ):
        importlib.import_module(module_name)
