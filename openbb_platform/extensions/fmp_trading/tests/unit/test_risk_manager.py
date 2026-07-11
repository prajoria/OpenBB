"""RiskManager — one test per gate (PRD §8.2, AC-risk-1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import exchange_calendars as xcals
import pytest

from openbb_fmp_trading.core.risk_manager import RiskManager
from openbb_fmp_trading.models import RiskConfig, SessionStatus, TickData


def _tick(ts):
    return TickData(
        ts=ts,
        quotes={},
        bars_recent={},
        session_status=SessionStatus(
            exchange="NASDAQ",
            is_market_open=True,
            is_pre_market=False,
            is_after_market=False,
            is_early_close_day=False,
            next_open=ts,
            next_close=ts,
        ),
    )


def _rm(**overrides):
    cfg = RiskConfig(
        **{k: v for k, v in overrides.items() if k in RiskConfig.model_fields}
    )
    return RiskManager(config=cfg, starting_equity=Decimal("100000"))


def test_g1_flat_by_close_rejects_after_1550_et():
    rm = _rm()
    cal = xcals.get_calendar("NASDAQ")
    et = cal.tz
    tick = _tick(
        datetime(2026, 7, 6, 15, 51, tzinfo=et).astimezone(timezone.utc)
    )
    plan = {"symbol": "AAPL", "notional": Decimal("1000"), "sector": "Tech"}
    d = rm.propose_trade(plan, tick)
    assert d.verdict == "REJECTED" and d.reason_code == "G1"


def test_g2_max_open_positions():
    rm = _rm()
    rm.state.open_position_count = rm.config.max_open_positions
    d = rm.propose_trade(
        {"symbol": "AAPL", "notional": Decimal("1000"), "sector": "Tech"},
        _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
    )
    assert d.reason_code == "G2"


def test_g3_day_dd_pct_breach():
    rm = _rm()
    rm.state.day_dd_pct = -3.0  # config default is -2.0
    d = rm.propose_trade(
        {"symbol": "AAPL", "notional": Decimal("1000"), "sector": "Tech"},
        _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
    )
    assert d.reason_code == "G3"


def test_g4_per_symbol_cooldown():
    rm = _rm()
    now = datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)
    rm.state.cooldowns["AAPL"] = now + timedelta(minutes=15)
    d = rm.propose_trade(
        {"symbol": "AAPL", "notional": Decimal("1000"), "sector": "Tech"},
        _tick(now),
    )
    assert d.reason_code == "G4"


def test_g5_sector_cap():
    rm = _rm()
    rm.open_positions_by_sector["Tech"] = rm.config.max_positions_per_sector
    d = rm.propose_trade(
        {"symbol": "AAPL", "notional": Decimal("1000"), "sector": "Tech"},
        _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
    )
    assert d.reason_code == "G5"


def test_g6_max_position_size():
    rm = _rm()
    # 10% of 100k = 10k limit; propose 15k -> G6 fires.
    d = rm.propose_trade(
        {"symbol": "AAPL", "notional": Decimal("15000"), "sector": "Tech"},
        _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
    )
    assert d.reason_code == "G6"


def test_g7_total_notional_cap():
    rm = _rm()
    # 30% of 100k = 30k cap; already holding 25k, propose 10k -> G7 fires.
    rm.total_notional = Decimal("25000")
    d = rm.propose_trade(
        {"symbol": "MSFT", "notional": Decimal("10000"), "sector": "Tech"},
        _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
    )
    assert d.reason_code == "G7"


def test_g8_duplicate_position():
    rm = _rm()
    rm.open_positions_by_symbol["AAPL"] = Decimal("100")
    d = rm.propose_trade(
        {"symbol": "AAPL", "notional": Decimal("1000"), "sector": "Tech"},
        _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
    )
    assert d.reason_code == "G8"


def test_all_gates_pass_approves():
    """Sanity: minimal state with no gate tripped -> APPROVED."""
    rm = _rm()
    d = rm.propose_trade(
        {"symbol": "AAPL", "notional": Decimal("5000"), "sector": "Tech"},
        _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
    )
    assert d.verdict == "APPROVED"


def test_first_reject_wins_short_circuits():
    """Multiple gates could fire — only the first (G2) should be reported.

    G2 (max_open) will fire; if we also set day_dd, only G2 should return.
    """
    rm = _rm()
    rm.state.open_position_count = rm.config.max_open_positions
    rm.state.day_dd_pct = -3.0  # would also trip G3
    d = rm.propose_trade(
        {"symbol": "AAPL", "notional": Decimal("1000"), "sector": "Tech"},
        _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
    )
    assert d.reason_code == "G2", "G2 comes before G3; first REJECT must win"


def test_gates_tripped_today_accumulates_unique():
    """Repeated fires of the same gate register once in gates_tripped_today."""
    rm = _rm()
    rm.state.open_position_count = rm.config.max_open_positions
    tick = _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc))
    plan = {"symbol": "AAPL", "notional": Decimal("1000"), "sector": "Tech"}
    for _ in range(3):
        rm.propose_trade(plan, tick)
    assert rm.state.gates_tripped_today == ["G2"]
