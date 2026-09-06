"""Human-readable log emitter + JSON summary for local-ci.

The `--json` payload lives BELOW a delimiter line so both streams can share
stdout without a temp file. Agent skill wrappers slice on the delimiter;
humans read the log above it.

Spec: docs/Specs/Local-CI-Skill-Spec.md §5.3
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from typing import TextIO

from local_ci.compose import SidecarResult, TierResult

JSON_DELIMITER = "---LOCAL-CI-JSON---"
REPORT_SCHEMA_ID = "local-ci/v1"


@dataclass
class RunReport:
    project: str
    tiers: list[TierResult] = field(default_factory=list)
    sidecars: list[SidecarResult] = field(default_factory=list)

    @property
    def overall_status(self) -> str:
        # Invariant: pass ⇒ at least one tier actually executed.
        # `all([])` is True — without this guard, a run that filters out every
        # tier (bug, refactor, empty default_tiers) would emit
        # `overall_status: pass, overall_exit_code: 0` with zero work done
        # (MED #4 from PR #1009 review).
        if not self.tiers:
            return "fail"
        return "pass" if all(t.status == "pass" for t in self.tiers) else "fail"

    @property
    def overall_exit_code(self) -> int:
        return 0 if self.overall_status == "pass" else 1

    def to_json_obj(self) -> dict:
        return {
            "schema": REPORT_SCHEMA_ID,
            "project": self.project,
            "tiers": [
                _tier_to_dict(t) for t in self.tiers
            ],
            "sidecars": [asdict(s) for s in self.sidecars],
            "overall_status": self.overall_status,
            "overall_exit_code": self.overall_exit_code,
        }


def _tier_to_dict(t: TierResult) -> dict:
    d = {
        "name": t.name,
        "status": t.status,
        "duration_s": t.duration_s,
        "exit_code": t.exit_code,
    }
    if t.first_failure_excerpt:
        d["first_failure_excerpt"] = t.first_failure_excerpt
    return d


def print_summary(report: RunReport, out: TextIO | None = None) -> None:
    """One line per tier, then overall. Kept compact for chat + terminals."""
    if out is None:
        out = sys.stdout
    print("", file=out)
    print(f"local-ci: {report.project} — {report.overall_status.upper()}", file=out)
    for t in report.tiers:
        marker = "PASS" if t.status == "pass" else t.status.upper()
        print(f"  [{marker:5}] {t.name:12s} {t.duration_s:>7.2f}s  exit={t.exit_code}", file=out)
    for s in report.sidecars:
        state = "healthy" if s.healthy else ("up" if s.brought_up else "down")
        init = " (init ran)" if s.init_ran else ""
        print(f"  sidecar {s.name}: {state}{init}", file=out)


def print_json_block(report: RunReport, out: TextIO | None = None) -> None:
    if out is None:
        out = sys.stdout
    print(JSON_DELIMITER, file=out)
    json.dump(report.to_json_obj(), out, indent=2, sort_keys=True)
    print("", file=out)


def print_dry_run(
    project: str,
    compose_argvs: list[list[str]],
    tier_argvs: list[tuple[str, list[str]]],
    out: TextIO | None = None,
) -> None:
    """Print what would run, without executing."""
    if out is None:
        out = sys.stdout
    print(f"local-ci --dry-run: {project}", file=out)
    print("", file=out)
    if compose_argvs:
        print("Compose orchestration:", file=out)
        for argv in compose_argvs:
            print(f"  $ {' '.join(argv)}", file=out)
    if tier_argvs:
        print("", file=out)
        print("Tier commands (inside runner container):", file=out)
        for name, argv in tier_argvs:
            print(f"  # tier: {name}", file=out)
            print(f"  $ {' '.join(argv)}", file=out)
