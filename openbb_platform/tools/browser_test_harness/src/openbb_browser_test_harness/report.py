"""Report emitters — write report.md + report.json from a list of StepResults.

Design spec: docs/superpowers/specs/2026-08-01-browser-test-harness-design.md §2, §10
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .steps import Step, StepResult, Story


def write_report_json(
    out_path: Path,
    story: Story,
    results: list[StepResult],
    steps_by_id: dict[str, Step],
) -> None:
    """Machine-readable report for CI."""
    payload = {
        "story_id": story.id,
        "story_title": story.title,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_steps": len(results),
        "passed": sum(1 for r in results if r.ok),
        "failed": sum(1 for r in results if not r.ok),
        "steps": [
            {
                "step_id": r.step_id,
                "human_title": steps_by_id[r.step_id].human_title,
                "notebook_ref": steps_by_id[r.step_id].notebook_ref,
                "ok": r.ok,
                "duration_ms": r.duration_ms,
                "screenshot_path": r.screenshot_path,
                "screenshot_sha256": r.screenshot_sha256,
                "observations": r.observations,
                "error": r.error,
            }
            for r in results
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_report_md(
    out_path: Path,
    story: Story,
    results: list[StepResult],
    steps_by_id: dict[str, Step],
) -> None:
    """Human-readable report."""
    passed = sum(1 for r in results if r.ok)
    failed = sum(1 for r in results if not r.ok)
    lines: list[str] = [
        f"# {story.title} — Test Report",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "",
        f"**Steps:** {len(results)} total, {passed} passed, {failed} failed",
        "",
        "| Step | Status | Duration | Notebook |",
        "|---|---|---:|---|",
    ]
    for r in results:
        step = steps_by_id[r.step_id]
        badge = "✅" if r.ok else "❌"
        lines.append(
            f"| `{r.step_id}` — {step.human_title} | {badge} | "
            f"{r.duration_ms}ms | {step.notebook_ref} |"
        )
    lines.append("")

    # Failures section
    if failed > 0:
        lines.append("## Failures")
        lines.append("")
        for r in results:
            if r.ok:
                continue
            step = steps_by_id[r.step_id]
            lines.append(f"### {r.step_id} — {step.human_title}")
            lines.append("")
            lines.append(f"**Error:** {r.error}")
            lines.append("")
            lines.append("**Observations:**")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(r.observations, indent=2, default=str))
            lines.append("```")
            lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
