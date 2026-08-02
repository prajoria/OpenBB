"""Fixture staleness enforcement (§9 P1-5).

Spawns the widget_backend, re-hits every endpoint referenced by any Story
step, and diffs the current response against ``fixtures/expected_responses/``.

If a fixture drifts silently — e.g. a stub value changes but the fixture
isn't updated — this test fails loudly with a re-record command.

Skipped unless BROWSER_HARNESS_LIVE=1 because it spawns a real subprocess.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from openbb_browser_test_harness.drivers.standalone_driver import StandaloneDriver
from openbb_browser_test_harness.stories import STORIES

_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "expected_responses"
)


def _all_endpoint_steps() -> list:
    """All Steps across all stories that have an endpoint."""
    seen: set[str] = set()
    out = []
    for story in STORIES.values():
        for step in story.steps:
            if step.endpoint is None or step.id in seen:
                continue
            seen.add(step.id)
            out.append(step)
    return out


@pytest.mark.skipif(
    os.environ.get("BROWSER_HARNESS_LIVE") != "1",
    reason=(
        "Live subprocess test — set BROWSER_HARNESS_LIVE=1 to enable. "
        "This test is slow (spawns uvicorn) so it's opt-in in CI."
    ),
)
@pytest.mark.asyncio
async def test_fixtures_are_current() -> None:
    """Every endpoint fixture matches the current backend response."""
    driver = StandaloneDriver()
    await driver.setup()
    drifted: list[str] = []
    try:
        for step in _all_endpoint_steps():
            fixture_path = _FIXTURE_ROOT / f"{step.id}.json"
            if not fixture_path.exists():
                drifted.append(f"MISSING: {fixture_path.name}")
                continue
            saved = json.loads(fixture_path.read_text(encoding="utf-8"))
            assert driver.client is not None
            path = (
                step.endpoint
                if step.endpoint.startswith("/")
                else f"/{step.endpoint}"
            )
            resp = await driver.client.get(path, params=step.params)
            current: dict = {
                "endpoint": step.endpoint,
                "params": step.params,
                "status_code": resp.status_code,
            }
            try:
                current["body"] = resp.json()
            except ValueError:
                current["body_text"] = resp.text
            # Compare shape+values.
            if current != saved:
                drifted.append(step.id)
    finally:
        await driver.teardown()
    if drifted:
        pytest.fail(
            f"{len(drifted)} fixture(s) drifted from live response:\n  "
            + "\n  ".join(drifted)
            + "\n\nRe-record with: python -m openbb_browser_test_harness.snapshot"
        )


def test_every_endpoint_step_has_fixture_on_disk() -> None:
    """Non-live version — every endpoint step must have SOME fixture file.

    Runs in CI without spawning uvicorn. Catches the case where a new story
    step was added but the developer forgot to run the snapshot command.
    """
    missing: list[str] = []
    for step in _all_endpoint_steps():
        if not (_FIXTURE_ROOT / f"{step.id}.json").exists():
            missing.append(step.id)
    if missing:
        pytest.fail(
            f"{len(missing)} step(s) have no fixture file:\n  "
            + "\n  ".join(missing)
            + "\n\nCapture with: python -m openbb_browser_test_harness.snapshot"
        )
