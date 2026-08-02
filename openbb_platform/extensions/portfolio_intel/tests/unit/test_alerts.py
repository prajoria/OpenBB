"""Unit tests for alert-rule engine (#571).

Covers:
- Each of the 6 triggers in isolation (positive + negative cases).
- Threshold semantics (insider buy min USD, upcoming horizon, top-N).
- Filter semantics (only "P" transaction type, only "8-K" form type,
  only "downgrade" action, only held symbols).
- Deterministic ordering + idempotent keys (same input → same alerts,
  same order, same keys across calls).
- Loud-empty on empty ctx (no crash, empty result).
- Enable / disable per trigger.
- R7.11 reverse-verify: mutate a trigger's data, confirm output
  changes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from openbb_portfolio_intel.analytics.alerts import (
    DEFAULT_INSIDER_BUY_USD,
    Alert,
    AlertConfig,
    AlertContext,
    AnalystAction,
    DividendEvent,
    EarningsEvent,
    FormFiling,
    HoldingRef,
    InsiderTrade,
    PaperTradingEvent,
    Severity,
    TriggerType,
    evaluate_all,
    evaluate_analyst_downgrade_top10,
    evaluate_earnings_upcoming,
    evaluate_ex_div_upcoming,
    evaluate_form_8k_for_held,
    evaluate_insider_open_market_buy,
    evaluate_paper_trading_events,
)

D = Decimal
TODAY = date(2026, 7, 20)
NOW = datetime(2026, 7, 20, 15, 0, 0)


def _holdings(*weights: tuple[str, str]) -> tuple[HoldingRef, ...]:
    return tuple(HoldingRef(symbol=s, weight=D(w)) for s, w in weights)


# ---------------------------------------------------------------------------
# Trigger 1: earnings_upcoming
# ---------------------------------------------------------------------------


def test_earnings_alert_fires_within_horizon() -> None:
    alerts = evaluate_earnings_upcoming(
        _holdings(("AAPL", "0.5")),
        [EarningsEvent(symbol="AAPL", date=TODAY + timedelta(days=3))],
        today=TODAY,
    )
    assert len(alerts) == 1
    assert alerts[0].trigger is TriggerType.EARNINGS_UPCOMING
    assert alerts[0].symbol == "AAPL"


def test_earnings_alert_skipped_outside_horizon() -> None:
    alerts = evaluate_earnings_upcoming(
        _holdings(("AAPL", "0.5")),
        [EarningsEvent(symbol="AAPL", date=TODAY + timedelta(days=10))],
        today=TODAY,
        horizon_days=5,
    )
    assert alerts == []


def test_earnings_alert_skipped_for_unheld_symbol() -> None:
    alerts = evaluate_earnings_upcoming(
        _holdings(("AAPL", "0.5")),
        [EarningsEvent(symbol="MSFT", date=TODAY + timedelta(days=2))],
        today=TODAY,
    )
    assert alerts == []


def test_earnings_alert_severity_warning_when_soon() -> None:
    alerts = evaluate_earnings_upcoming(
        _holdings(("AAPL", "0.5")),
        [EarningsEvent(symbol="AAPL", date=TODAY + timedelta(days=1))],
        today=TODAY,
    )
    assert alerts[0].severity is Severity.WARNING


# ---------------------------------------------------------------------------
# Trigger 2: ex_div_upcoming
# ---------------------------------------------------------------------------


def test_ex_div_alert_fires_within_horizon() -> None:
    alerts = evaluate_ex_div_upcoming(
        _holdings(("SPY", "1.0")),
        [DividendEvent(symbol="SPY", ex_date=TODAY + timedelta(days=3))],
        today=TODAY,
    )
    assert len(alerts) == 1
    assert alerts[0].severity is Severity.INFO


def test_ex_div_alert_skipped_past_date() -> None:
    alerts = evaluate_ex_div_upcoming(
        _holdings(("SPY", "1.0")),
        [DividendEvent(symbol="SPY", ex_date=TODAY - timedelta(days=1))],
        today=TODAY,
    )
    assert alerts == []


# ---------------------------------------------------------------------------
# Trigger 3: insider_open_market_buy
# ---------------------------------------------------------------------------


def test_insider_buy_fires_above_threshold_for_open_market_buy() -> None:
    alerts = evaluate_insider_open_market_buy(
        _holdings(("AAPL", "0.5")),
        [
            InsiderTrade(
                symbol="AAPL",
                transaction_date=TODAY - timedelta(days=1),
                transaction_type="P",
                value_usd=D("250000"),
            )
        ],
        since=TODAY - timedelta(days=7),
    )
    assert len(alerts) == 1
    assert alerts[0].severity is Severity.WARNING


def test_insider_buy_skips_below_threshold() -> None:
    alerts = evaluate_insider_open_market_buy(
        _holdings(("AAPL", "0.5")),
        [
            InsiderTrade(
                symbol="AAPL",
                transaction_date=TODAY - timedelta(days=1),
                transaction_type="P",
                value_usd=D("50000"),  # below default $100K
            )
        ],
        since=TODAY - timedelta(days=7),
    )
    assert alerts == []


def test_insider_buy_skips_sells_and_other_codes() -> None:
    """Only 'P' (open-market purchase) fires. Sells 'S' and everything else ignored."""
    for tx_type in ("S", "M", "F", "A"):
        alerts = evaluate_insider_open_market_buy(
            _holdings(("AAPL", "0.5")),
            [
                InsiderTrade(
                    symbol="AAPL",
                    transaction_date=TODAY - timedelta(days=1),
                    transaction_type=tx_type,
                    value_usd=D("500000"),
                )
            ],
            since=TODAY - timedelta(days=7),
        )
        assert alerts == [], f"tx_type={tx_type} should not fire"


def test_insider_buy_respects_custom_threshold() -> None:
    alerts = evaluate_insider_open_market_buy(
        _holdings(("AAPL", "0.5")),
        [
            InsiderTrade(
                symbol="AAPL",
                transaction_date=TODAY - timedelta(days=1),
                transaction_type="P",
                value_usd=D("75000"),
            )
        ],
        since=TODAY - timedelta(days=7),
        min_value_usd=D("50000"),
    )
    assert len(alerts) == 1


# ---------------------------------------------------------------------------
# Trigger 4: form_8k_for_held
# ---------------------------------------------------------------------------


def test_form_8k_fires_for_held_symbol() -> None:
    alerts = evaluate_form_8k_for_held(
        _holdings(("AAPL", "0.5")),
        [
            FormFiling(
                symbol="AAPL",
                form_type="8-K",
                filed_at=NOW - timedelta(hours=2),
            )
        ],
        since=NOW - timedelta(days=7),
    )
    assert len(alerts) == 1
    assert alerts[0].severity is Severity.WARNING


def test_form_8k_skips_non_8k_forms() -> None:
    alerts = evaluate_form_8k_for_held(
        _holdings(("AAPL", "0.5")),
        [
            FormFiling(
                symbol="AAPL", form_type="10-Q", filed_at=NOW - timedelta(hours=2)
            ),
            FormFiling(
                symbol="AAPL",
                form_type="10-K",
                filed_at=NOW - timedelta(days=1),
            ),
        ],
        since=NOW - timedelta(days=7),
    )
    assert alerts == []


# ---------------------------------------------------------------------------
# Trigger 5: analyst_downgrade_top10
# ---------------------------------------------------------------------------


def test_downgrade_alert_fires_for_top10_holding() -> None:
    holdings = _holdings(*[(f"S{i}", str(0.1 - i * 0.005)) for i in range(15)])
    # S0..S14; top 10 by weight = S0..S9
    alerts = evaluate_analyst_downgrade_top10(
        holdings,
        [
            AnalystAction(
                symbol="S3",
                action_date=TODAY - timedelta(days=1),
                action="downgrade",
                from_rating="Buy",
                to_rating="Hold",
            )
        ],
        since=TODAY - timedelta(days=7),
    )
    assert len(alerts) == 1
    assert alerts[0].severity is Severity.CRITICAL


def test_downgrade_alert_skipped_for_outside_top10() -> None:
    holdings = _holdings(*[(f"S{i}", str(0.1 - i * 0.005)) for i in range(15)])
    alerts = evaluate_analyst_downgrade_top10(
        holdings,
        [
            AnalystAction(
                symbol="S12",  # rank 13 — outside top 10
                action_date=TODAY - timedelta(days=1),
                action="downgrade",
            )
        ],
        since=TODAY - timedelta(days=7),
    )
    assert alerts == []


def test_upgrade_not_flagged_only_downgrades_fire() -> None:
    holdings = _holdings(("AAPL", "0.5"))
    alerts = evaluate_analyst_downgrade_top10(
        holdings,
        [
            AnalystAction(
                symbol="AAPL",
                action_date=TODAY - timedelta(days=1),
                action="upgrade",
            ),
            AnalystAction(
                symbol="AAPL",
                action_date=TODAY - timedelta(days=1),
                action="initiate",
            ),
        ],
        since=TODAY - timedelta(days=7),
    )
    assert alerts == []


# ---------------------------------------------------------------------------
# Trigger 6: paper_trading_events
# ---------------------------------------------------------------------------


def test_paper_fill_produces_info_alert() -> None:
    alerts = evaluate_paper_trading_events(
        [
            PaperTradingEvent(
                symbol="AAPL",
                when=NOW - timedelta(minutes=5),
                status="FILLED",
                quantity=D("10"),
                fill_price=D("100.05"),
            )
        ],
        since=NOW - timedelta(days=1),
    )
    assert len(alerts) == 1
    assert alerts[0].severity is Severity.INFO
    assert "10" in alerts[0].message


def test_paper_rejection_produces_warning_alert() -> None:
    alerts = evaluate_paper_trading_events(
        [
            PaperTradingEvent(
                symbol="AAPL",
                when=NOW - timedelta(minutes=1),
                status="REJECTED",
                reason="insufficient cash",
            )
        ],
        since=NOW - timedelta(days=1),
    )
    assert alerts[0].severity is Severity.WARNING
    assert "insufficient cash" in alerts[0].message


# ---------------------------------------------------------------------------
# evaluate_all — orchestration, sorting, keys, empty
# ---------------------------------------------------------------------------


def test_evaluate_all_empty_context_returns_empty_list() -> None:
    """R7.3: no crash on empty substrate."""
    assert evaluate_all(AlertContext(), now=NOW) == []


def test_evaluate_all_sort_is_severity_desc_then_time_asc() -> None:
    ctx = AlertContext(
        holdings=_holdings(("AAPL", "0.5"), ("MSFT", "0.5")),
        earnings=(EarningsEvent(symbol="AAPL", date=TODAY + timedelta(days=1)),),
        analyst_actions=(
            AnalystAction(
                symbol="AAPL",
                action_date=TODAY - timedelta(days=1),
                action="downgrade",
            ),
        ),
        dividends=(DividendEvent(symbol="MSFT", ex_date=TODAY + timedelta(days=1)),),
    )
    out = evaluate_all(ctx, now=NOW)
    # Expect: CRITICAL downgrade first, then WARNING earnings, then INFO ex-div
    severities = [a.severity for a in out]
    assert severities == [Severity.CRITICAL, Severity.WARNING, Severity.INFO]


def test_alert_keys_are_idempotent_across_calls() -> None:
    """Same input → same keys. Callers can dedupe on key."""
    ctx = AlertContext(
        holdings=_holdings(("AAPL", "1.0")),
        earnings=(EarningsEvent(symbol="AAPL", date=TODAY + timedelta(days=2)),),
    )
    out1 = evaluate_all(ctx, now=NOW)
    out2 = evaluate_all(ctx, now=NOW)
    assert [a.key for a in out1] == [a.key for a in out2]


def test_disable_specific_trigger_via_config() -> None:
    ctx = AlertContext(
        holdings=_holdings(("AAPL", "1.0")),
        earnings=(EarningsEvent(symbol="AAPL", date=TODAY + timedelta(days=2)),),
    )
    # earnings enabled — get one alert
    assert len(evaluate_all(ctx, now=NOW)) == 1
    # earnings disabled — get zero
    cfg = AlertConfig(
        enabled=frozenset(
            t for t in TriggerType if t is not TriggerType.EARNINGS_UPCOMING
        )
    )
    assert evaluate_all(ctx, now=NOW, config=cfg) == []


def test_default_insider_buy_threshold_matches_prd() -> None:
    """PRD 17 Phase 1: default insider open-market buy threshold = $100K."""
    assert DEFAULT_INSIDER_BUY_USD == D("100000")


# ---------------------------------------------------------------------------
# R7.11 reverse-verify: mutate data, confirm output changes
# ---------------------------------------------------------------------------


def test_reverse_verify_earnings_date_shift_changes_alert_count() -> None:
    """Move the earnings event outside the horizon → alert count changes."""
    holdings = _holdings(("AAPL", "1.0"))
    inside = [EarningsEvent(symbol="AAPL", date=TODAY + timedelta(days=3))]
    outside = [EarningsEvent(symbol="AAPL", date=TODAY + timedelta(days=30))]
    n_in = len(evaluate_earnings_upcoming(holdings, inside, today=TODAY))
    n_out = len(evaluate_earnings_upcoming(holdings, outside, today=TODAY))
    assert n_in == 1
    assert n_out == 0
    assert n_in != n_out


def test_reverse_verify_downgrade_severity_load_bearing() -> None:
    """CRITICAL severity for top-10 downgrade is load-bearing for sort order.

    If a future refactor accidentally downgrades this to WARNING, the
    ordering test above still passes for that scenario (WARNING earnings
    would sort ahead of a WARNING downgrade differently). Lock in the
    exact severity here so mutation is detected.
    """
    holdings = _holdings(("AAPL", "1.0"))
    alerts = evaluate_analyst_downgrade_top10(
        holdings,
        [
            AnalystAction(
                symbol="AAPL",
                action_date=TODAY,
                action="downgrade",
            )
        ],
        since=TODAY - timedelta(days=7),
    )
    assert len(alerts) == 1
    assert alerts[0].severity is Severity.CRITICAL


def test_alert_dataclass_is_frozen() -> None:
    """Alerts must be immutable so key-based dedup is safe."""
    a = Alert(
        trigger=TriggerType.EARNINGS_UPCOMING,
        severity=Severity.INFO,
        symbol="AAPL",
        when=NOW,
        message="test",
        key="test:AAPL",
    )
    import dataclasses

    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        a.symbol = "MSFT"  # type: ignore[misc]
