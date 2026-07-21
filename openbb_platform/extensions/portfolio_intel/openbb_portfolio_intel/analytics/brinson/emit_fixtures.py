"""Emit golden JSON fixtures for #559's attribution engine (#935).

Run:
    python -m openbb_portfolio_intel.analytics.brinson.emit_fixtures

Writes one JSON file per case into ``fixtures/`` next to this module.
The JSON schema is the API contract with #559 — the attribution engine
loads and asserts against these files WITHOUT importing this package
at test time.

Schema (per file):
    {
      "case_id":      "bf-n3-seed1",
      "generator": {"n_groups": 3, "seed": 1, "flags": {...}},
      "inputs": {
        "group": ["S0","S1","S2"],
        "w_p":   [...],  "w_b": [...],
        "r_p":   [...],  "r_b": [...]
      },
      "expected": {
        "active_return": ..., "allocation": ..., "selection": ...,
        "interaction": ..., "tolerance_bps": 1.0
      }
    }

Regenerate whenever the case list below changes; commit the JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openbb_portfolio_intel.analytics.brinson.generator import (
    BrinsonCase,
    make_case,
)
from openbb_portfolio_intel.analytics.brinson.oracle import brinson_reference

# The golden case set — covers all §4.2 edge cases from the spec.
_CASES: list[dict[str, Any]] = [
    {"n_groups": 3, "seed": 1, "flags": {}},  # baseline
    {"n_groups": 11, "seed": 2, "flags": {}},  # GICS-sized
    {"n_groups": 1, "seed": 3, "flags": {}},  # degenerate single group
    {"n_groups": 5, "seed": 4, "flags": {"zero_wp": True}},  # I own none of S0
    {"n_groups": 5, "seed": 5, "flags": {"zero_wb": True}},  # off-benchmark
    {"n_groups": 5, "seed": 6, "flags": {"identical": True}},  # all zeros
    {"n_groups": 7, "seed": 7, "flags": {"all_negative": True}},  # bear market
]


def _case_to_fixture(case: BrinsonCase, flags: dict[str, bool]) -> dict[str, Any]:
    effects = brinson_reference(case.df)
    return {
        "case_id": case.case_id,
        "generator": {
            "n_groups": case.n_groups,
            "seed": case.seed,
            "flags": flags,
        },
        "inputs": {
            "group": case.df["group"].tolist(),
            "w_p": case.df["w_p"].tolist(),
            "w_b": case.df["w_b"].tolist(),
            "r_p": case.df["r_p"].tolist(),
            "r_b": case.df["r_b"].tolist(),
        },
        "expected": {
            **effects.as_dict(),
            "tolerance_bps": 1.0,
        },
    }


def emit_all(out_dir: Path | None = None) -> list[Path]:
    """Regenerate every fixture file. Returns paths written."""
    out_dir = out_dir or Path(__file__).parent / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for spec in _CASES:
        case = make_case(spec["n_groups"], spec["seed"], **spec["flags"])
        fixture = _case_to_fixture(case, spec["flags"])
        path = out_dir / f"{case.case_id}.json"
        path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n")
        written.append(path)
    return written


if __name__ == "__main__":
    paths = emit_all()
    for p in paths:
        print(f"wrote {p}")  # noqa: T201
