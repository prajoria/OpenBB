"""Integration test for #82 validate -- end-to-end against in-tree openbb-backtest.

Runs ``validate_plan`` against the **real** openbb-backtest validate router on a
single-symbol sample plan, asserting a real verdict is returned and the bridge's
attach contract holds (plan.validation populated). Skips cleanly when either
``openbb-backtest`` is absent or the data provider (``fmp_cached``) is unreachable
-- so the default offline unit sweep is unaffected.

The fixture window is intentionally small (≈1y) to keep the test cost-bounded; the
shipped default horizon is 5y for production runs.
"""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

_BACKTEST_AVAILABLE = importlib.util.find_spec("openbb_backtest") is not None


def _fmp_cached_available() -> bool:
    """Best-effort probe: provider importable + a user_settings.json carries the key."""
    if importlib.util.find_spec("openbb_fmp_cached") is None:
        return False
    settings = Path.home() / ".openbb_platform" / "user_settings.json"
    if not settings.exists():
        return False
    try:
        import json
        cred = json.loads(settings.read_text(encoding="utf-8")).get("credentials", {})
        return bool(cred.get("fmp_cached_api_key") or cred.get("fmp_api_key"))
    except Exception:  # noqa: BLE001 - any settings-read failure -> skip
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _BACKTEST_AVAILABLE,
        reason="openbb-backtest not installed; install with: pip install 'openbb-techtrade[validation]'",
    ),
    pytest.mark.skipif(
        not _fmp_cached_available(),
        reason="fmp_cached provider / API key not configured for live integration",
    ),
]


from openbb_techtrade.models import (  # noqa: E402 -- gated by skipif
    EntryExitRule,
    MoverSignal,
    Recommendation,
    TradePlan,
)
from openbb_techtrade.validation.backtest_bridge import validate_plan  # noqa: E402


def _build_sample_plan() -> TradePlan:
    """A single-symbol BUY plan with a recent as_of for the integration window."""
    as_of = date(2024, 12, 13)  # fixed Friday in late 2024 -- deterministic fold window
    sig = MoverSignal(
        symbol="SPY", segment="IT", as_of=as_of,
        score=0.55, direction="long", votes=[], rank_in_segment=1,
    )
    rec = Recommendation(
        symbol="SPY", segment="IT", as_of=as_of,
        action="BUY", conviction="Medium", score=0.55,
        entry_price=Decimal("600.00"), stop_price=Decimal("588.00"), target_price=Decimal("624.00"),
        stop_distance_pct=0.02, target_distance_pct=0.04, risk_reward=2.0, atr=6.0,
        position_size=Decimal("83"), risk_per_share=Decimal("12.00"),
        risk_pct_of_notional=0.00996, time_stop_bars=20,
        reasoning="", top_factors=[], caveats="None.",
    )
    return TradePlan(
        symbol="SPY", segment="IT", as_of=as_of,
        signal=sig, rule=EntryExitRule(entry_threshold=0.4),
        position_size=Decimal("83"), orders=[], simulated_fills=[], recommendation=rec,
    )


def test_validate_plan_returns_real_verdict_against_in_tree_backtest():
    """End-to-end: a sample plan validates against in-tree openbb-backtest and returns a verdict.

    Asserts:
    1. The bridge returns ``(updated_plan, report)`` where ``report.verdict`` is one
       of the locked three verdicts (L3).
    2. ``updated_plan.validation`` is the same report (Q-D attach).
    3. The report records the method we asked for + the windowed fold range.
    """
    plan = _build_sample_plan()
    # Use a SHORT horizon (1y) so the integration test stays cost-bounded; in production
    # the default 5y horizon gives more folds and a stabler verdict.
    updated, report = asyncio.run(
        validate_plan(plan, method="wfo", horizon_years=1)
    )
    assert report.verdict in {"robust", "fragile", "overfit"}
    assert report.method == "wfo"
    assert len(report.folds) >= 1
    assert updated.validation is report
