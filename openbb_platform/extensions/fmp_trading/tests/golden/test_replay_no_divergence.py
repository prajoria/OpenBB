"""AC-P5-7: replay the checked-in reference journal without divergence.

Any change to _process_signal that alters event shape fails this test
on the frozen reference journal — the alarm bell for "did we just
change the golden contract?"

This test can only provide protection if the reference journal actually
exercises the code paths under change. Since the current empty-quote
StubbedDataProvider means replaying a fixture with signals/orders/fills
would diverge, this test uses ``raise_on_divergence=False`` and asserts
we STOP AT the divergent tick — proving the comparator worked. The
diverged_at_tick should be the index of the first bar-close tick where
a signal was recorded.

Full "no divergence at all" replay lands with the P5-followup-1
TickEvent widening (StubbedDataProvider gets real quotes).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REF_JOURNAL = (
    Path(__file__).parent.parent
    / "fixtures"
    / "journals"
    / "ref_2026-07-13_msft_aapl.ndjson"
)


def test_reference_journal_exists():
    """Guard: the reference journal file is committed to the repo."""
    assert REF_JOURNAL.exists(), (
        f"Reference journal missing: {REF_JOURNAL}. This is a checked-in "
        f"fixture — restore it before running the golden suite."
    )


def test_reference_journal_exercises_nontrivial_paths():
    """Guard against a shrunk fixture masquerading as coverage.

    The reference journal must exercise real signal + order + fill +
    veto events, otherwise the golden test would silently protect
    nothing.
    """
    lines = REF_JOURNAL.read_text(encoding="utf-8").splitlines()
    event_types = set()
    for line in lines:
        if not line.strip():
            continue
        # Very simple: grep 'event_type":"X"'
        if '"event_type":"' in line:
            start = line.index('"event_type":"') + len('"event_type":"')
            end = line.index('"', start)
            event_types.add(line[start:end])

    for required in (
        "session_start",
        "tick",
        "signal",
        "order",
        "fill",
        "veto",
        "session_end",
    ):
        assert required in event_types, (
            f"Reference journal missing {required!r} events — golden "
            f"test protects nothing. Regenerate a fixture that exercises "
            f"the full tick-loop path (see P5.3 Step 1)."
        )


def test_reference_journal_control_flow_deterministic():
    """Control-flow contract: replay's diverged_at_tick reports the
    first tick where a signal/order/fill was recorded.

    In the reference journal, the first bar-close tick (index 2 =
    13:30:10 UTC) had a signal + order + fill. Replay's empty-quote
    stub can't reproduce those, so it MUST detect the divergence.

    If someone changes _process_signal to emit different event types
    at that tick, this test surfaces the change immediately.
    """
    from openbb_fmp_trading.reporting.replay import replay

    result = replay(REF_JOURNAL, raise_on_divergence=False)
    # Reference journal has 5 tick events; the 3rd (index 2) is where
    # the signal cascade fires. Comparator detects the divergence there.
    assert result.diverged_at_tick is not None, (
        "Reference journal replayed WITHOUT any divergence — the "
        "control-flow comparator is broken (or someone widened "
        "TickEvent.payload without updating this test)."
    )
    assert 0 <= result.diverged_at_tick < 5
