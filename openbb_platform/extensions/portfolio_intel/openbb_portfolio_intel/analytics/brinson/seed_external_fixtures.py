"""Seed expected effects into external Brinson fixtures (#557).

Textbook fixtures at ``analytics/brinson/fixtures_external/`` carry
hand-authored inputs (from cited academic sources) but empty
``expected`` blocks. This script computes the expected effects using
the #935 oracle (literal transcription of BF formulas, itself unit-
tested + R7.11 verified) and writes them back.

Run:
    python -m openbb_portfolio_intel.analytics.brinson.seed_external_fixtures

Skips files with empty ``inputs.group`` (e.g. PLACEHOLDER for
Bloomberg data QA will fill later).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from openbb_portfolio_intel.analytics.brinson.oracle import brinson_reference


def _external_dir() -> Path:
    return Path(__file__).parent / "fixtures_external"


def seed_all(out_dir: Path | None = None) -> list[Path]:
    """Populate every external fixture's expected block. Returns paths updated."""
    out_dir = out_dir or _external_dir()
    written: list[Path] = []
    for path in sorted(out_dir.glob("*.json")):
        fx = json.loads(path.read_text())
        inputs = fx.get("inputs", {})
        if not inputs.get("group"):
            # PLACEHOLDER — QA hasn't filled the inputs yet, skip.
            continue
        df = pd.DataFrame(inputs)
        eff = brinson_reference(df)
        fx["expected"] = {
            "active_return": eff.active_return,
            "allocation": eff.allocation,
            "selection": eff.selection,
            "interaction": eff.interaction,
            "tolerance_bps": fx.get("expected", {}).get("tolerance_bps", 1.0),
        }
        path.write_text(json.dumps(fx, indent=2, sort_keys=True) + "\n")
        written.append(path)
    return written


if __name__ == "__main__":
    for p in seed_all():
        print(f"seeded {p}")  # noqa: T201
