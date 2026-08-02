"""Manual guide generator — emit human-readable Markdown from a Story.

Design spec: docs/superpowers/specs/2026-08-01-browser-test-harness-design.md §7

Usage::

    python -m openbb_browser_test_harness.emit_guide --story portfolio
    python -m openbb_browser_test_harness.emit_guide --story techtrade
    python -m openbb_browser_test_harness.emit_guide --story both

Reads the same Story object the automation driver runs and emits a Markdown
guide with per-step instructions, expected values, and screenshot placeholder
paths that B6's workspace driver will populate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .steps import ActionKind, Persona, Step, Story
from .stories import STORIES

_HARNESS_ROOT = Path(__file__).resolve().parents[2]
_GUIDES_DIR = _HARNESS_ROOT / "guides"


_PERSONA_LABEL = {
    Persona.ANALYST: "analyst",
    Persona.PM: "portfolio manager",
    Persona.SYSTEMATIC_TRADER: "systematic trader",
}

_ACTION_VERB = {
    ActionKind.NAVIGATE: "Navigate",
    ActionKind.OBSERVE: "Observe",
    ActionKind.INPUT: "Input & observe",
    ActionKind.SCREENSHOT: "Screenshot",
    ActionKind.ASSERT: "Assert (safety invariant)",
}


def _step_block(step: Step, story_id: str) -> str:
    lines: list[str] = []
    lines.append(f"### {step.human_title}")
    lines.append("")
    lines.append(
        f"**Step ID:** `{step.id}` &nbsp; · &nbsp; "
        f"**Tab:** `{step.tab_id}` &nbsp; · &nbsp; "
        f"**Action:** {_ACTION_VERB[step.action]} &nbsp; · &nbsp; "
        f"**Persona:** {_PERSONA_LABEL[step.persona]}"
    )
    lines.append("")
    lines.append(f"**Notebook anchor:** [`{step.notebook_ref}`](../../../{step.notebook_ref})")
    lines.append("")
    lines.append(step.human_description)
    lines.append("")
    lines.append(f"**Expected:** {step.human_expected}")
    lines.append("")
    if step.params:
        params_line = " · ".join(f"`{k}={v}`" for k, v in step.params.items())
        lines.append(f"**Params:** {params_line}")
        lines.append("")
    if step.endpoint:
        lines.append(f"**Endpoint:** `{step.endpoint}`")
        lines.append("")
    if "safety" in step.tags:
        lines.append(
            "> ⚠️ **Safety invariant** — this step guards a load-bearing "
            "behavior. If it fails, DO NOT ship."
        )
        lines.append("")

    # Screenshot placeholder — B6 workspace driver populates
    screenshot_rel = f"screenshots/{story_id}/{step.resolved_screenshot_name}"
    lines.append(f"![{step.id}]({screenshot_rel})")
    lines.append("")
    lines.append(
        f"*Screenshot will be captured by* "
        f"`python -m openbb_browser_test_harness.run --story {story_id} "
        f"--mode workspace --capture-guide-screenshots` (B6 #1728)."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _emit_guide(story: Story) -> str:
    header = [
        f"# {story.title} — Manual Test Guide",
        "",
        f"**Story:** `{story.id}`",
        f"**Notebook series:** [`{story.notebook_series_root}`](../../../{story.notebook_series_root})",
        f"**Total steps:** {len(story.steps)}",
        "",
        "> This guide is auto-generated from the Story data source. "
        "Do NOT edit by hand — edit "
        f"`src/openbb_browser_test_harness/stories/{story.id}.py` and "
        "regenerate with:",
        "> ",
        f"> ```powershell",
        f"> python -m openbb_browser_test_harness.emit_guide --story {story.id}",
        f"> ```",
        "",
        "## Prep",
        "",
        "1. Activate `.venv_portfolio` and install the harness:",
        "",
        "   ```powershell",
        "   pip install -e openbb_platform/tools/browser_test_harness/",
        "   ```",
        "",
        "2. Start the widget backend (harness spawns it automatically for "
        "automation mode; here for the manual mode you start it yourself):",
        "",
        "   ```powershell",
        "   $env:PI_WIDGET_BACKEND_AUTH_MODE = 'loopback-dev'",
        "   uvicorn openbb_portfolio_intel.widget_backend.main:app --host 127.0.0.1 --port 6120",
        "   ```",
        "",
        "3. In OpenBB Workspace (`https://pro.openbb.co`): "
        "**Data connectors → Custom backend → Add** URL `http://127.0.0.1:6120`.",
        "",
        "4. Load the appropriate Workspace app "
        + (
            "(**Portfolio Intelligence Terminal**)."
            if story.id == "portfolio"
            else "(**Techtrade Trading Desk**)."
        ),
        "",
        "---",
        "",
        "## Steps",
        "",
    ]
    body = [_step_block(step, story.id) for step in story.steps]
    return "\n".join(header) + "\n".join(body)


def _write_guide(story: Story) -> Path:
    _GUIDES_DIR.mkdir(parents=True, exist_ok=True)
    out = _GUIDES_DIR / f"{story.id}-manual-guide.md"
    out.write_text(_emit_guide(story), encoding="utf-8")
    (_GUIDES_DIR / "screenshots" / story.id).mkdir(parents=True, exist_ok=True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="openbb-browser-harness-emit-guide",
        description="Emit a manual test guide from a Story.",
    )
    parser.add_argument(
        "--story",
        choices=[*STORIES.keys(), "both"],
        required=True,
    )
    args = parser.parse_args()
    stories_to_emit = (
        list(STORIES.values()) if args.story == "both" else [STORIES[args.story]]
    )
    for story in stories_to_emit:
        out = _write_guide(story)
        print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
