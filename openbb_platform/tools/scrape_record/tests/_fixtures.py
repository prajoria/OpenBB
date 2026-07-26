"""Test-only helpers for scrape_record.

Post-#1425 the real snapshots live in a user-local DB. Extractor and
snapshot-envelope tests still need on-disk JSON to parse, so we keep a
minimal set of synthetic fixtures under
``openbb_platform/tools/scrape_record/synthetic_fixtures/`` and route
tests at them via this module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_ROOT = (
    Path(__file__).resolve().parents[1] / "synthetic_fixtures"
).resolve()


def fixture_path(name: str, symbol: str) -> Path:
    """Return the on-disk path for a synthetic fixture snapshot."""
    return FIXTURES_ROOT / name / f"{symbol}.json"


def load_fixture(name: str, symbol: str) -> dict[str, Any]:
    """Return the parsed JSON envelope for a synthetic fixture."""
    return json.loads(fixture_path(name, symbol).read_text(encoding="utf-8"))
