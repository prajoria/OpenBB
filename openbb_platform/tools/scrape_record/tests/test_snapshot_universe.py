"""Round-trip tests: for every synthetic fixture snapshot, the extractor
produces a shape-conformant `extracted` dict.

Post-#1425 there are no committed real snapshots; the parametrization
walks the small ``synthetic_fixtures/`` set retained for tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scrape_record.extract import apply_extractor

from ._fixtures import FIXTURES_ROOT


def _iter_fixtures():
    for recording_dir in sorted(FIXTURES_ROOT.iterdir()):
        if not recording_dir.is_dir():
            continue
        for path in sorted(recording_dir.glob("*.json")):
            yield recording_dir.name, path.stem, path


FIXTURE_CASES = list(_iter_fixtures())


@pytest.mark.parametrize(
    ("recording_name", "symbol", "path"),
    FIXTURE_CASES,
    ids=[f"{name}/{sym}" for name, sym, _ in FIXTURE_CASES],
)
def test_synthetic_fixture_round_trip(
    recording_name: str, symbol: str, path: Path
) -> None:
    """`raw` -> extractor -> non-empty dict; keys match committed `extracted`."""
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["symbol"].upper() == symbol.upper()
    assert isinstance(data.get("raw"), dict)
    fresh = apply_extractor(recording_name, data["raw"])
    assert isinstance(fresh, dict) and fresh
    committed = data.get("extracted")
    if committed:
        assert set(fresh.keys()) == set(committed.keys())


def test_fixture_universe_not_empty():
    """Guard against an empty synthetic_fixtures dir slipping past CI."""
    assert len(FIXTURE_CASES) > 0, "no synthetic fixtures under synthetic_fixtures/"


def test_fixture_no_pii_leak():
    """No fixture may contain operator-identifying strings."""
    bad_patterns = ("daaji", "C:\\Users\\", "/home/")
    hits = []
    for _, _, path in FIXTURE_CASES:
        text = path.read_text(encoding="utf-8")
        for pat in bad_patterns:
            if pat in text:
                hits.append(f"{path.name}: {pat!r}")
    assert not hits, "PII detected in fixtures: " + ", ".join(hits[:5])
