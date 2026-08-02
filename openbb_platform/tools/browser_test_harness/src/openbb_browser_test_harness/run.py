"""CLI entrypoint — ``python -m openbb_browser_test_harness.run --story portfolio``.

Design spec: docs/superpowers/specs/2026-08-01-browser-test-harness-design.md §5
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .drivers import HarnessSetupError, StandaloneDriver
from .report import write_report_json, write_report_md
from .steps import Step, StepResult
from .stories import STORIES


async def _run_story(story_id: str, mode: str, out_dir: Path) -> int:
    story = STORIES[story_id]
    steps_by_id: dict[str, Step] = {s.id: s for s in story.steps}

    if mode == "standalone":
        driver = StandaloneDriver()
    else:
        # workspace mode ships with B6 (#1728). Fail loudly for now.
        print(
            "workspace mode is not yet implemented — see #1728 (B6). "
            "Use --mode standalone for now.",
            file=sys.stderr,
        )
        return 2

    try:
        await driver.setup()
    except HarnessSetupError as exc:
        print(f"Harness setup failed: {exc}", file=sys.stderr)
        return 3

    results: list[StepResult] = []
    try:
        for step in story.steps:
            result = await driver.run_step(step)
            status = "OK" if result.ok else "FAIL"
            print(f"  [{status}] {step.id} - {result.duration_ms}ms")
            results.append(result)
    finally:
        await driver.teardown()

    out_dir.mkdir(parents=True, exist_ok=True)
    write_report_md(out_dir / "report.md", story, results, steps_by_id)
    write_report_json(out_dir / "report.json", story, results, steps_by_id)

    passed = sum(1 for r in results if r.ok)
    failed = sum(1 for r in results if not r.ok)
    print(f"\n{passed}/{len(results)} steps passed ({failed} failed)")
    print(f"Reports written to {out_dir.resolve()}")

    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="openbb-browser-harness",
        description="Run the browser test harness against the portfolio or techtrade Workspace app.",
    )
    parser.add_argument(
        "--story",
        choices=list(STORIES.keys()),
        required=True,
        help="Which story to run.",
    )
    parser.add_argument(
        "--mode",
        choices=["standalone", "workspace"],
        default="standalone",
        help="standalone = HTTP-only (default, CI-friendly); workspace = Playwright (B6, WIP).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(".dev-cycle/browser-harness-report"),
        help="Where to write report.md and report.json.",
    )
    args = parser.parse_args()
    return asyncio.run(_run_story(args.story, args.mode, args.out))


if __name__ == "__main__":
    sys.exit(main())
