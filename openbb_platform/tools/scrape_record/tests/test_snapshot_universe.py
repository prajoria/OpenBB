"""Round-trip tests: for every committed snapshot, extractor produces
a shape-conformant `extracted` dict. Parametrized across the whole
committed universe.

This is the load-bearing regression test for sub-epic #1384 PR-B —
if an extractor breaks or a snapshot gets corrupted mid-refresh,
this catches it before it reaches a fetcher.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scrape_record.config import load_config, snapshot_path
from scrape_record.extract import apply_extractor

SNAPSHOTS_ROOT = (
    Path(__file__).resolve().parents[3] / "tools" / "scrape_record" / "snapshots"
)


def _iter_snapshots():
    """Yield (recording_name, symbol, path) for every committed snapshot."""
    for recording_dir in sorted(SNAPSHOTS_ROOT.iterdir()):
        if not recording_dir.is_dir():
            continue
        recording_name = recording_dir.name
        for path in sorted(recording_dir.glob("*.json")):
            yield recording_name, path.stem, path


SNAPSHOT_CASES = list(_iter_snapshots())


@pytest.mark.parametrize(
    ("recording_name", "symbol", "path"),
    SNAPSHOT_CASES,
    ids=[f"{name}/{sym}" for name, sym, _ in SNAPSHOT_CASES],
)
def test_snapshot_round_trip(recording_name: str, symbol: str, path: Path) -> None:
    """`raw` -> extractor -> shape-conformant dict; matches `extracted` on disk."""
    data = json.loads(path.read_text(encoding="utf-8"))
    assert (
        data["symbol"].upper() == symbol.upper()
    ), f"snapshot filename {symbol!r} != envelope symbol {data['symbol']!r}"
    assert isinstance(data.get("raw"), dict), "snapshot missing 'raw' block"

    fresh = apply_extractor(recording_name, data["raw"])
    assert isinstance(fresh, dict) and fresh, "extractor returned empty dict"

    committed = data.get("extracted")
    if committed:
        assert set(fresh.keys()) == set(committed.keys()), (
            f"extractor keys drifted for {recording_name}/{symbol}: "
            f"fresh={sorted(fresh.keys())}, committed={sorted(committed.keys())}"
        )


def test_snapshot_universe_not_empty():
    """Guard against an empty snapshots dir slipping past CI."""
    assert len(SNAPSHOT_CASES) > 0, "no committed snapshots — did ingest happen?"


@pytest.mark.parametrize(
    ("recording_name", "symbol", "path"),
    SNAPSHOT_CASES,
    ids=[f"{name}/{sym}" for name, sym, _ in SNAPSHOT_CASES],
)
def test_snapshot_path_resolves_via_config(
    recording_name: str, symbol: str, path: Path
) -> None:
    """`snapshot_path()` must resolve to the same file the sweep wrote."""
    cfg = load_config()
    resolved = snapshot_path(cfg, recording_name, symbol)
    assert resolved.resolve() == path.resolve()


def test_snapshot_no_pii_leak():
    """No snapshot may contain operator-identifying strings.

    Public market data only. If a snapshot got written with a local
    absolute path (would happen if a recording script embedded it) or
    an operator username, this catches it before commit reaches CI.
    """
    bad_patterns = ("daaji", "C:\\Users\\", "/home/")
    hits = []
    for _, _, path in SNAPSHOT_CASES:
        text = path.read_text(encoding="utf-8")
        for pat in bad_patterns:
            if pat in text:
                hits.append(f"{path.name}: {pat!r}")
    assert not hits, "PII detected in snapshots: " + ", ".join(hits[:5])
