"""Persist a TechTrade scan into widget-ready snapshots (issue #1934).

``run_scan`` is a thin *adapter* over the existing
:func:`openbb_techtrade.engine.scan.scan_segments` orchestrator. It never re-implements
the fan-out or rank -- it calls ``scan_segments`` once, groups the returned actionable
plans by segment, narrows each plan to a JSON-safe row (:func:`plan_to_row`), and writes
one append-only snapshot per *successfully processed* requested segment.

Two behaviours matter for the widgets that read these snapshots:

* **empty-but-fresh** -- a segment that was scanned but produced no actionable plan gets
  a real, empty snapshot with a current ``computed_at``. That is genuinely different from
  "never scanned" (no row at all) and lets a widget say "scanned, nothing today" rather
  than "stale/unknown".
* **last-good** -- a segment whose scan *failed* (``scan_segments`` emits a skip warning
  and drops it) is never written, so its previous committed snapshot survives untouched.

The module keeps its ``python -m openbb_techtrade.engine.scan_runner`` CLI so the legacy
direct entry point remains a compatibility wrapper around the same adapter.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from openbb_techtrade.engine.movers import resolve_session
from openbb_techtrade.engine.scan import ScanSegmentWarning, scan_segments
from openbb_techtrade.engine.universe import GICS_SECTOR_ETFS
from openbb_techtrade.models import TradePlan
from openbb_techtrade.snapshots.models import (
    DEFAULT_SCAN_KIND,
    ScanSnapshot,
    plan_to_row,
)
from openbb_techtrade.snapshots.sqlite import SqliteScanSnapshotStore
from openbb_techtrade.snapshots.store import ScanSnapshotStore

UTC = timezone.utc

#: Canonical requested-segment default: every GICS sector, in canonical order.
DEFAULT_SEGMENTS: tuple[str, ...] = tuple(GICS_SECTOR_ETFS.keys())

#: A no-op cancellation check used when the caller supplies none.
def _never_cancel() -> bool:
    """Return ``False`` -- the default cancellation seam is never triggered."""
    return False


class ScanRunResult(BaseModel):
    """Structured outcome of one :func:`run_scan` invocation."""

    model_config = ConfigDict(frozen=True)

    kind: str = DEFAULT_SCAN_KIND
    as_of_session: date
    computed_at: datetime
    requested_segments: list[str] = Field(default_factory=list)
    processed_segments: list[str] = Field(default_factory=list)
    failed_segments: list[str] = Field(default_factory=list)
    snapshot_ids: dict[str, str] = Field(default_factory=dict)
    segment_counts: dict[str, int] = Field(default_factory=dict)
    total_rows: int = 0
    cancelled: bool = False
    warnings: list[str] = Field(default_factory=list)

    def to_summary(self) -> dict[str, Any]:
        """Return a bounded, JSON-safe summary suitable for a ``JobResult``."""
        return {
            "kind": self.kind,
            "as_of_session": self.as_of_session.isoformat(),
            "computed_at": self.computed_at.isoformat(),
            "requested_segment_count": len(self.requested_segments),
            "processed_segment_count": len(self.processed_segments),
            "failed_segment_count": len(self.failed_segments),
            "empty_segment_count": sum(
                1 for seg in self.processed_segments if self.segment_counts.get(seg, 0) == 0
            ),
            "total_rows": self.total_rows,
            "cancelled": self.cancelled,
            "snapshot_ids": dict(self.snapshot_ids),
            "segment_counts": dict(self.segment_counts),
            "failed_segments": list(self.failed_segments),
        }


def _resolve_as_of(as_of: date | str | None) -> date:
    """Snap ``as_of`` to the last XNYS session (the session the scan represents)."""
    return resolve_session(as_of, "XNYS")


def _failed_segments_from_warnings(
    caught: list[warnings.WarningMessage],
) -> set[str]:
    """Return segments identified by the structured scan warning contract."""
    return {
        item.message.segment
        for item in caught
        if isinstance(item.message, ScanSegmentWarning)
    }


def run_scan(
    *,
    segments: list[str] | None = None,
    top_n: int = 3,
    preset: str = "trend_follow",
    as_of: date | str | None = None,
    store: ScanSnapshotStore | None = None,
    scan_fn: Callable[..., list[TradePlan]] = scan_segments,
    kind: str = DEFAULT_SCAN_KIND,
    should_cancel: Callable[[], bool] | None = None,
    **scan_kwargs: Any,
) -> ScanRunResult:
    """Run the cross-segment scan and persist one snapshot per requested segment.

    The heavy lifting stays in ``scan_fn`` (``scan_segments`` by default): this adapter
    only owns persistence. It calls ``scan_fn`` once, captures its skip warnings, groups
    the ranked actionable plans by segment, and writes an append-only snapshot for each
    requested segment that was *successfully processed* -- including an empty-but-fresh
    snapshot for a processed segment with no actionable plan. Segments that ``scan_fn``
    skipped (surfaced as warnings) are never written, so their last good snapshot stands.

    Parameters
    ----------
    segments : list[str] | None, optional
        Requested segments to persist. Defaults to every GICS sector.
    top_n : int, optional
        Per-segment mover cap forwarded to ``scan_fn``. Defaults to ``3``.
    preset : str, optional
        Confluence/rule preset forwarded to ``scan_fn`` and recorded on each snapshot.
    as_of : date | str | None, optional
        Requested date; snapped once to the last XNYS session and threaded down.
    store : ScanSnapshotStore | None, optional
        Snapshot store. Defaults to a ``SqliteScanSnapshotStore`` at the configured path.
    scan_fn : Callable[..., list[TradePlan]], optional
        The scan orchestrator. Injected by tests; defaults to ``scan_segments``.
    kind : str, optional
        Snapshot ``kind`` label. Defaults to ``"daily_scan"``.
    should_cancel : Callable[[], bool] | None, optional
        Cooperative cancellation check consulted *between segments*. When it returns
        ``True`` the run stops writing further segments and reports ``cancelled=True``.
    **scan_kwargs : Any
        Extra keyword arguments forwarded verbatim to ``scan_fn`` (e.g. test fetchers).

    Returns
    -------
    ScanRunResult
        Snapshot ids, per-segment counts, failed/processed segments, and warnings.
    """
    requested = list(segments) if segments is not None else list(DEFAULT_SEGMENTS)
    cancel_check = should_cancel or _never_cancel
    owns_store = store is None
    active_store = store or SqliteScanSnapshotStore()

    session = _resolve_as_of(as_of)
    computed_at = datetime.now(UTC)

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            plans = scan_fn(top_n=top_n, preset=preset, as_of=as_of, **scan_kwargs)

        warning_messages = [str(item.message) for item in caught]
        failed = _failed_segments_from_warnings(caught) & set(requested)

        plans_by_segment: dict[str, list[TradePlan]] = {}
        for plan in plans:
            plans_by_segment.setdefault(plan.segment, []).append(plan)

        snapshot_ids: dict[str, str] = {}
        segment_counts: dict[str, int] = {}
        processed: list[str] = []
        cancelled = False
        result_warnings = list(warning_messages)

        for segment in requested:
            if segment in failed:
                # scan_fn skipped this segment; preserve its last good snapshot.
                continue
            if cancel_check():
                cancelled = True
                result_warnings.append(
                    f"scan: cancelled before segment {segment!r}; last good snapshot preserved"
                )
                break

            segment_plans = plans_by_segment.get(segment, [])
            rows = [plan_to_row(plan) for plan in segment_plans]
            snapshot = ScanSnapshot(
                kind=kind,
                segment=segment,
                as_of_session=session,
                computed_at=computed_at,
                preset=preset,
                params={"top_n": top_n, "preset": preset},
                rows=rows,
            )
            active_store.write_snapshot(snapshot)
            snapshot_ids[segment] = snapshot.snapshot_id
            segment_counts[segment] = len(rows)
            processed.append(segment)

        return ScanRunResult(
            kind=kind,
            as_of_session=session,
            computed_at=computed_at,
            requested_segments=requested,
            processed_segments=processed,
            failed_segments=sorted(failed),
            snapshot_ids=snapshot_ids,
            segment_counts=segment_counts,
            total_rows=sum(segment_counts.values()),
            cancelled=cancelled,
            warnings=result_warnings,
        )
    finally:
        if owns_store:
            active_store.close()


def _build_parser() -> argparse.ArgumentParser:
    """Build the ``python -m openbb_techtrade.engine.scan_runner`` CLI parser."""
    parser = argparse.ArgumentParser(
        prog="python -m openbb_techtrade.engine.scan_runner",
        description="Run a TechTrade scan and persist widget-ready snapshots.",
    )
    parser.add_argument(
        "--segments",
        default=None,
        help="Comma-separated segments to persist (default: all GICS sectors).",
    )
    parser.add_argument("--top-n", type=int, default=3, help="Per-segment mover cap.")
    parser.add_argument(
        "--preset", default="trend_follow", help="Confluence/rule preset."
    )
    parser.add_argument(
        "--as-of", default=None, help="Session date (YYYY-MM-DD); defaults to today."
    )
    parser.add_argument(
        "--db", default=None, help="Override the snapshot database path."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m openbb_techtrade.engine.scan_runner``."""
    args = _build_parser().parse_args(argv)
    segments = (
        [seg.strip() for seg in args.segments.split(",") if seg.strip()]
        if args.segments
        else None
    )
    store = SqliteScanSnapshotStore(args.db) if args.db else None
    try:
        result = run_scan(
            segments=segments,
            top_n=args.top_n,
            preset=args.preset,
            as_of=args.as_of,
            store=store,
        )
    finally:
        if store is not None:
            store.close()

    print(json.dumps(result.to_summary(), indent=2, sort_keys=True))  # noqa: T201 - CLI stdout is this entry point's interface
    for message in result.warnings:
        print(f"warning: {message}", file=sys.stderr)  # noqa: T201 - CLI stderr diagnostics
    return 0


if __name__ == "__main__":
    sys.exit(main())
