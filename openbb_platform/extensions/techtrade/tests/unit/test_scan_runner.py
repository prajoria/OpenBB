"""Tests for the run_scan snapshot adapter (issue #1934).

Fully offline. ``run_scan`` is exercised with an injected ``scan_fn`` returning
recorded-realistic ``TradePlan`` shapes (built through the real ``build_plans`` chain)
and, in one integration test, the real ``scan_segments`` driven by offline fetchers.
The adapter's persistence contract is asserted: one snapshot per requested segment,
empty-but-fresh writes, last-good preservation for skipped segments, warning
propagation, and cooperative cancellation between segments.
"""

from __future__ import annotations

import json
import warnings
from datetime import date
from decimal import Decimal

from openbb_techtrade.engine.plan import build_plans
from openbb_techtrade.engine.scan import ScanSegmentWarning
from openbb_techtrade.engine.scan_runner import DEFAULT_SEGMENTS, run_scan
from openbb_techtrade.models import MoverSignal, TradePlan
from openbb_techtrade.snapshots import ScanSnapshot, SqliteScanSnapshotStore

_AS_OF = date(2024, 1, 12)
_ENTRY = Decimal("121.40")
_ATR = 1.90


def _signal(symbol: str, segment: str, score: float) -> MoverSignal:
    """Build a ranked MoverSignal with direction derived from the score sign."""
    direction = "long" if score >= 0.4 else "short" if score <= -0.4 else "flat"
    return MoverSignal(
        symbol=symbol, segment=segment, as_of=_AS_OF, score=score,
        direction=direction, votes=[], rank_in_segment=1,
    )


def _signal_fetcher_for(signals: dict[tuple[str, str], MoverSignal]):
    """Offline signal_fetcher keyed by (symbol, segment)."""

    def _fetch(symbols=None, segment=None, *, preset="trend_follow", as_of=None):
        return [signals[(s, segment)] for s in (symbols or []) if (s, segment) in signals]

    return _fetch


def _level_fetcher(entry: Decimal = _ENTRY, atr: float = _ATR):
    def _fetch(symbol: str, *, as_of: date):
        return entry, atr

    return _fetch


def _plan(symbol: str, segment: str, score: float) -> TradePlan:
    """Build one real, actionable TradePlan for a score (recorded-realistic shape)."""
    sig = _signal(symbol, segment, score)
    plans = build_plans(
        symbols=[symbol], segment=segment, as_of=_AS_OF,
        signal_fetcher=_signal_fetcher_for({(symbol, segment): sig}),
        level_fetcher=_level_fetcher(),
    )
    return plans[0]


class _FakeStore:
    """In-memory ScanSnapshotStore used to assert the adapter's write behaviour."""

    def __init__(self) -> None:
        self.snapshots: list[ScanSnapshot] = []
        self.closed = False

    def initialize(self) -> None:  # pragma: no cover - trivial
        return None

    def close(self) -> None:
        self.closed = True

    def write_snapshot(self, snapshot: ScanSnapshot) -> ScanSnapshot:
        self.snapshots.append(snapshot)
        return snapshot

    def read_latest(self, *, kind: str, segment: str):
        matches = [s for s in self.snapshots if s.kind == kind and s.segment == segment]
        return matches[-1] if matches else None

    def read_by_id(self, snapshot_id: str):
        return next((s for s in self.snapshots if s.snapshot_id == snapshot_id), None)

    def list_snapshots(self, *, kind=None, segment=None, limit=None):
        rows = [
            s for s in self.snapshots
            if (kind is None or s.kind == kind) and (segment is None or s.segment == segment)
        ]
        return list(reversed(rows))[:limit] if limit is not None else list(reversed(rows))

    def prune_snapshots(self, *, keep=10) -> int:  # pragma: no cover - unused here
        return 0


def _scan_fn_returning(
    plans: list[TradePlan],
    *,
    warn: list[str | Warning] | None = None,
):
    """Build an injected scan_fn that returns fixed plans and emits given warnings."""

    def _scan(*, top_n=3, preset="trend_follow", as_of=None, **kwargs):
        for message in warn or []:
            warnings.warn(message, stacklevel=2)
        return list(plans)

    return _scan


def test_run_scan_writes_one_snapshot_per_requested_segment():
    """Each requested segment gets exactly one snapshot with its grouped rows."""
    plans = [
        _plan("AAA", "Energy", 0.90),
        _plan("BBB", "Energy", 0.50),
        _plan("CCC", "Financials", 0.70),
    ]
    store = _FakeStore()
    result = run_scan(
        segments=["Energy", "Financials"],
        as_of=_AS_OF,
        store=store,
        scan_fn=_scan_fn_returning(plans),
    )

    assert set(result.processed_segments) == {"Energy", "Financials"}
    assert result.segment_counts == {"Energy": 2, "Financials": 1}
    assert result.total_rows == 3
    assert len(store.snapshots) == 2
    energy = store.read_latest(kind="daily_scan", segment="Energy")
    assert [r["symbol"] for r in energy.rows] == ["AAA", "BBB"]
    assert energy.as_of_session == _AS_OF


def test_run_scan_rows_are_json_safe_and_flattened():
    """Rows are plain JSON-safe scalars carrying the recommendation headline."""
    store = _FakeStore()
    run_scan(
        segments=["Energy"],
        store=store,
        scan_fn=_scan_fn_returning([_plan("AAA", "Energy", 0.90)]),
    )
    row = store.snapshots[0].rows[0]
    # Round-trips through json with no custom encoder.
    assert json.loads(json.dumps(row)) == row
    assert row["symbol"] == "AAA"
    assert row["action"] == "BUY"
    assert isinstance(row["entry_price"], float)
    assert isinstance(row["position_size"], float)


def test_run_scan_writes_empty_but_fresh_for_processed_segment_with_no_plans():
    """A requested, successfully-processed segment with no plans gets an empty snapshot."""
    store = _FakeStore()
    result = run_scan(
        segments=["Energy", "Financials"],
        store=store,
        scan_fn=_scan_fn_returning([_plan("AAA", "Energy", 0.90)]),
    )
    assert "Financials" in result.processed_segments
    fin = store.read_latest(kind="daily_scan", segment="Financials")
    assert fin is not None
    assert fin.rows == []
    assert fin.is_empty
    assert result.segment_counts["Financials"] == 0


def test_run_scan_skips_failed_segment_and_preserves_last_good():
    """A segment scan_fn skipped (warned) is not written; its last good snapshot stands."""
    store = _FakeStore()
    # Seed a prior good Energy snapshot.
    store.write_snapshot(
        ScanSnapshot(
            kind="daily_scan", segment="Energy", as_of_session=date(2024, 1, 11),
            rows=[{"symbol": "OLD", "segment": "Energy"}],
        )
    )
    result = run_scan(
        segments=["Energy", "Financials"],
        store=store,
        scan_fn=_scan_fn_returning(
            [_plan("CCC", "Financials", 0.70)],
            warn=[ScanSegmentWarning("Energy", RuntimeError("synthetic failure"))],
        ),
    )

    assert result.failed_segments == ["Energy"]
    assert "Energy" not in result.processed_segments
    assert "Financials" in result.processed_segments
    # Energy still shows the old good snapshot, not a new empty one.
    energy = store.read_latest(kind="daily_scan", segment="Energy")
    assert [r["symbol"] for r in energy.rows] == ["OLD"]


def test_run_scan_uses_structured_warning_from_real_scan_segments():
    """A real scan segment failure preserves last-good without parsing warning text."""
    store = _FakeStore()
    store.write_snapshot(
        ScanSnapshot(
            kind="daily_scan",
            segment="Energy",
            as_of_session=date(2024, 1, 11),
            rows=[{"symbol": "OLD", "segment": "Energy"}],
        )
    )

    def _fail_energy(symbols=None, segment=None, *, preset="trend_follow", as_of=None):
        if segment == "Energy":
            raise RuntimeError("synthetic producer failure")
        return []

    result = run_scan(
        segments=["Energy", "Financials"],
        store=store,
        as_of=_AS_OF,
        simulate=False,
        candidate_fetcher=_candidate_fetcher(
            {"symbol": "AAA", "pct_change": 0.05, "volume": 100}
        ),
        signal_fetcher=_fail_energy,
        level_fetcher=_level_fetcher(),
    )

    assert result.failed_segments == ["Energy"]
    assert result.processed_segments == ["Financials"]
    assert store.read_latest(kind="daily_scan", segment="Energy").rows == [
        {"symbol": "OLD", "segment": "Energy"}
    ]
    assert store.read_latest(kind="daily_scan", segment="Financials").rows == []


def test_run_scan_surfaces_scan_warnings_in_result():
    """Warnings emitted by scan_fn are captured into the result warnings."""
    store = _FakeStore()
    result = run_scan(
        segments=["Financials"],
        store=store,
        scan_fn=_scan_fn_returning(
            [_plan("CCC", "Financials", 0.70)],
            warn=["scan: skipped fills for 'CCC': boom"],
        ),
    )
    assert any("skipped fills for 'CCC'" in w for w in result.warnings)


def test_run_scan_cancels_between_segments():
    """A cancellation request between segments stops further writes and is reported."""
    plans = [_plan("AAA", "Energy", 0.90), _plan("CCC", "Financials", 0.70)]
    store = _FakeStore()
    calls = {"n": 0}

    def _cancel() -> bool:
        # Allow the first segment, cancel before the second.
        should = calls["n"] >= 1
        calls["n"] += 1
        return should

    result = run_scan(
        segments=["Energy", "Financials"],
        store=store,
        scan_fn=_scan_fn_returning(plans),
        should_cancel=_cancel,
    )

    assert result.cancelled is True
    assert result.processed_segments == ["Energy"]
    assert "Financials" not in result.snapshot_ids
    assert any("cancelled" in w for w in result.warnings)


def test_run_scan_defaults_to_all_gics_segments():
    """With no segments given, every GICS sector is requested."""
    store = _FakeStore()
    result = run_scan(store=store, scan_fn=_scan_fn_returning([]))
    assert result.requested_segments == list(DEFAULT_SEGMENTS)
    assert len(result.processed_segments) == len(DEFAULT_SEGMENTS)
    # All empty-but-fresh.
    assert result.total_rows == 0
    assert len(store.snapshots) == len(DEFAULT_SEGMENTS)


def test_run_scan_summary_is_json_safe():
    """The result summary serializes cleanly for a JobResult."""
    store = _FakeStore()
    result = run_scan(
        segments=["Energy"],
        store=store,
        scan_fn=_scan_fn_returning([_plan("AAA", "Energy", 0.90)]),
    )
    summary = result.to_summary()
    assert json.loads(json.dumps(summary)) == summary
    assert summary["total_rows"] == 1
    assert summary["processed_segment_count"] == 1


def _candidate_fetcher(*rows: dict):
    """Segment-blind offline candidate_fetcher (same movers for every sector)."""

    def _fetch(as_of=None, calendar="XNYS", needs_ohlcv=False, **kwargs):
        return [dict(r) for r in rows]

    return _fetch


def test_run_scan_wraps_real_scan_segments_into_sqlite(tmp_path):
    """Integration: run_scan drives the real scan_segments and persists to SQLite."""
    from openbb_techtrade.engine.movers import list_movers

    segments = [
        ml.segment
        for ml in list_movers(
            segment=None,
            candidate_fetcher=_candidate_fetcher({"symbol": "AAA", "pct_change": 0.05, "volume": 100}),
            as_of=_AS_OF,
        )
    ]
    signals = {seg: _signal("AAA", seg, 0.90) for seg in segments}
    signal_fetcher = _signal_fetcher_for({("AAA", seg): sig for seg, sig in signals.items()})

    store = SqliteScanSnapshotStore(tmp_path / "scan.db")
    try:
        result = run_scan(
            segments=segments,
            store=store,
            as_of=_AS_OF,
            simulate=False,
            candidate_fetcher=_candidate_fetcher({"symbol": "AAA", "pct_change": 0.05, "volume": 100}),
            signal_fetcher=signal_fetcher,
            level_fetcher=_level_fetcher(),
        )
        assert len(result.processed_segments) == len(segments)
        assert result.total_rows == len(segments)  # one AAA plan per sector
        one = store.read_latest(kind="daily_scan", segment=segments[0])
        assert one is not None and one.rows[0]["symbol"] == "AAA"
    finally:
        store.close()
