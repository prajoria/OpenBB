"""CLI entrypoint — ``python -m openbb_browser_test_harness.run --story portfolio``.

Design spec: docs/superpowers/specs/2026-08-01-browser-test-harness-design.md §5
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .drivers import (
    HarnessSetupError,
    StandaloneDriver,
    WorkspaceDriver,
    _WORKSPACE_AVAILABLE,
)
from .report import write_report_json, write_report_md
from .steps import Step, StepResult
from .stories import STORIES


async def _run_story(
    story_id: str,
    mode: str,
    out_dir: Path,
    workspace_mode: str,
    capture_guide_screenshots: bool,
) -> int:
    story = STORIES[story_id]
    steps_by_id: dict[str, Step] = {s.id: s for s in story.steps}

    driver: object
    if mode == "standalone":
        # Extended step_timeout for endpoints that hit live fmp_cached
        # (e.g. pi/equity/analyst-forecasts).
        driver = StandaloneDriver(step_timeout_s=30.0)
    elif mode == "workspace":
        if not _WORKSPACE_AVAILABLE:
            print(
                "workspace mode requires playwright. Install with:\n"
                "  pip install -e "
                "openbb_platform/tools/browser_test_harness/[workspace]\n"
                "  python -m playwright install chromium",
                file=sys.stderr,
            )
            return 2
        assert WorkspaceDriver is not None
        # If --capture-guide-screenshots is set, save PNGs into the guides/
        # tree so B5's manual guide auto-populates them.
        screenshots_dir: Path | None = None
        if capture_guide_screenshots:
            screenshots_dir = (
                Path(__file__).resolve().parents[2]
                / "guides"
                / "screenshots"
                / story_id
            )
        driver = WorkspaceDriver(
            mode=workspace_mode,
            screenshots_dir=screenshots_dir,
        )
    else:
        print(f"Unknown mode {mode!r}", file=sys.stderr)
        return 2

    try:
        await driver.setup()  # type: ignore[attr-defined]
    except HarnessSetupError as exc:
        print(f"Harness setup failed: {exc}", file=sys.stderr)
        return 3

    results: list[StepResult] = []
    try:
        for step in story.steps:
            result = await driver.run_step(step)  # type: ignore[attr-defined]
            status = "OK" if result.ok else "FAIL"
            print(f"  [{status}] {step.id} - {result.duration_ms}ms")
            results.append(result)
    finally:
        await driver.teardown()  # type: ignore[attr-defined]

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
        help="standalone = HTTP-only (default, CI-friendly); workspace = Playwright.",
    )
    parser.add_argument(
        "--workspace-mode",
        choices=["persistent-context", "cdp-attach"],
        default="persistent-context",
        help="How Playwright attaches to Chrome (workspace mode only).",
    )
    parser.add_argument(
        "--capture-guide-screenshots",
        action="store_true",
        help=(
            "In workspace mode, save screenshots to guides/screenshots/<story>/ "
            "so the B5 manual-guide generator can embed them."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(".dev-cycle/browser-harness-report"),
        help="Where to write report.md and report.json.",
    )
    args = parser.parse_args()
    return asyncio.run(
        _run_story(
            args.story,
            args.mode,
            args.out,
            args.workspace_mode,
            args.capture_guide_screenshots,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
