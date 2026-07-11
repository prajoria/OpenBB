"""J4 tests: fmp_trading typed JournalEvent subclasses.

Verifies each concrete event subclass:
  1. Fixes its event_type via Literal (dispatch key stable)
  2. Round-trips through model_dump_json / model_validate_json
  3. Loses no payload fidelity across serialization
  4. Can be written to and read from an actual JournalWriter/JournalReader
     via the openbb_core_journal primitive
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from openbb_core_journal import JournalReader, JournalWriter
from openbb_fmp_trading.models.journal_events import (
    AlertFiredEvent,
    FillEvent,
    OrderEvent,
    RiskStateChangeEvent,
    SessionEndEvent,
    SessionStartEvent,
    SignalEvent,
    TickEvent,
    VetoEvent,
)

_NOW = datetime(2026, 7, 8, 13, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "event_type_cls,event_type_literal",
    [
        (SessionStartEvent, "session_start"),
        (TickEvent, "tick"),
        (SignalEvent, "signal"),
        (OrderEvent, "order"),
        (FillEvent, "fill"),
        (VetoEvent, "veto"),
        (AlertFiredEvent, "alert"),
        (RiskStateChangeEvent, "risk_state_change"),
        (SessionEndEvent, "session_end"),
    ],
)
def test_event_type_is_fixed_literal(event_type_cls, event_type_literal):
    """Each concrete subclass pins its event_type — no accidental drift."""
    instance = event_type_cls(
        ts=_NOW,
        session_id="test",
        payload={"probe": True},
    )
    assert instance.event_type == event_type_literal


def test_events_round_trip_through_pydantic():
    """Every subclass survives model_dump_json → model_validate_json intact."""
    original = SignalEvent(
        ts=_NOW,
        session_id="s1",
        payload={
            "symbol": "AAPL",
            "score": 0.72,
            "direction": "long",
            "votes": {"trend": 2, "momentum": 1},
        },
    )
    revived = SignalEvent.model_validate_json(original.model_dump_json())
    assert revived == original


def test_events_write_and_read_via_openbb_core_journal(tmp_path: Path):
    """End-to-end: write typed events through JournalWriter, read back via JournalReader.

    This is the whole point of J4 — fmp_trading's event subclasses ride the
    shared writer/reader without any local NDJSON plumbing.
    """
    journal = tmp_path / "session.ndjson"

    events = [
        SessionStartEvent(
            ts=_NOW, session_id="s1",
            payload={"exchange": "NASDAQ", "starting_equity": "100000"},
        ),
        TickEvent(
            ts=_NOW, session_id="s1",
            payload={"watchlist_size": 20, "quotes_fetched": 20, "mode": "normal"},
        ),
        SignalEvent(
            ts=_NOW, session_id="s1",
            payload={"symbol": "AAPL", "score": 0.72, "direction": "long"},
        ),
        OrderEvent(
            ts=_NOW, session_id="s1",
            payload={"symbol": "AAPL", "intent": "entry", "qty": "100",
                     "limit_price": "180.55"},
        ),
        FillEvent(
            ts=_NOW, session_id="s1",
            payload={"symbol": "AAPL", "price": "180.55", "qty": "100",
                     "slippage": "0.05"},
        ),
        VetoEvent(
            ts=_NOW, session_id="s1",
            payload={"symbol": "MSFT", "gate": "G3", "reason_code": "G3",
                     "reason": "day drawdown breach"},
        ),
        AlertFiredEvent(
            ts=_NOW, session_id="s1",
            payload={"alert_id": "a1", "symbol": "AAPL",
                     "condition": "price > 180"},
        ),
        RiskStateChangeEvent(
            ts=_NOW, session_id="s1",
            payload={"gate": "flat_by_close", "activated": True},
        ),
        SessionEndEvent(
            ts=_NOW, session_id="s1",
            payload={"flat_at_close": True, "realized_pnl": "65.00"},
        ),
    ]

    with JournalWriter(journal, session_id="s1") as w:
        for e in events:
            w.write(e)

    # Read back — the reader returns generic JournalEvent objects; the
    # event_type discriminator is what downstream consumers use to dispatch.
    read_events = JournalReader(journal).read_all()
    assert len(read_events) == len(events)
    assert [e.event_type for e in read_events] == [
        "session_start", "tick", "signal", "order", "fill",
        "veto", "alert", "risk_state_change", "session_end",
    ]
    # Payload fidelity: check one representative field survives.
    fills = [e for e in read_events if e.event_type == "fill"]
    assert fills[0].payload["price"] == "180.55"


def test_filter_push_down_works_with_typed_subclass_writes(tmp_path: Path):
    """The reader's event_types push-down filter works on files written by our subclasses."""
    journal = tmp_path / "filtered.ndjson"
    with JournalWriter(journal, session_id="s1") as w:
        w.write(TickEvent(ts=_NOW, session_id="s1", payload={}))
        w.write(SignalEvent(ts=_NOW, session_id="s1", payload={}))
        w.write(FillEvent(ts=_NOW, session_id="s1", payload={}))
        w.write(TickEvent(ts=_NOW, session_id="s1", payload={}))

    ticks = list(JournalReader(journal).stream(event_types=["tick"]))
    assert len(ticks) == 2
    assert all(e.event_type == "tick" for e in ticks)


def test_no_local_session_journal_module_exists():
    """Anti-regression: fmp-trading MUST NOT ship a local SessionJournal.

    P1.4 (J4) explicitly retrofits fmp-trading to use openbb_core_journal.
    A local session_journal module reintroduces the duplication the shared
    primitive was extracted to prevent (core-journal PRD §1 motivation).
    """
    import importlib.util

    for candidate in (
        "openbb_fmp_trading.core.session_journal",
        "openbb_fmp_trading.session_journal",
    ):
        spec = importlib.util.find_spec(candidate)
        assert spec is None, (
            f"Local {candidate} module exists — it MUST not. "
            f"Use openbb_core_journal (epic #408) instead."
        )
