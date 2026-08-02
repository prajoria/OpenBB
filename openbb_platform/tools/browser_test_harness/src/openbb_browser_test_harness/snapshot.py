"""Snapshot command — capture current endpoint responses into fixture files.

Design spec: docs/superpowers/specs/2026-08-01-browser-test-harness-design.md §9 (P1-5)

Usage::

    python -m openbb_browser_test_harness.snapshot

Spawns the widget_backend via B1's standalone driver, hits every endpoint
referenced by any step in any story, and writes the JSON response to
``fixtures/expected_responses/<step-id>.json``. Also writes
``fixtures/expected_layouts/`` from ``/apps.json``.

Re-run after a stub value legitimately changes; commit the updated fixtures
alongside the endpoint change so ``test_fixtures_are_current`` stays green.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from .drivers.standalone_driver import StandaloneDriver
from .stories import STORIES

_HARNESS_ROOT = Path(__file__).resolve().parents[2]  # browser_test_harness/
_FIXTURE_ROOT = _HARNESS_ROOT / "fixtures" / "expected_responses"
_LAYOUT_ROOT = _HARNESS_ROOT / "fixtures" / "expected_layouts"


async def _snapshot_all() -> int:
    # Extended step_timeout because pi/equity/analyst-forecasts hits the live
    # fmp_cached fetcher and can spike above the default 5s.
    driver = StandaloneDriver(step_timeout_s=30.0)
    await driver.setup()
    try:
        _FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
        _LAYOUT_ROOT.mkdir(parents=True, exist_ok=True)

        # 1) Per-step endpoint snapshots
        seen: set[str] = set()
        n = 0
        for story in STORIES.values():
            for step in story.steps:
                if step.endpoint is None:
                    continue
                key = f"{step.id}"
                if key in seen:
                    continue
                seen.add(key)
                assert driver.client is not None
                path = (
                    step.endpoint
                    if step.endpoint.startswith("/")
                    else f"/{step.endpoint}"
                )
                resp = await driver.client.get(path, params=step.params)
                payload = {
                    "endpoint": step.endpoint,
                    "params": step.params,
                    "status_code": resp.status_code,
                }
                try:
                    payload["body"] = resp.json()
                except ValueError:
                    payload["body_text"] = resp.text
                out = _FIXTURE_ROOT / f"{key}.json"
                out.write_text(
                    json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
                )
                print(f"  wrote {out.relative_to(_FIXTURE_ROOT.parents[1])}")
                n += 1

        # 2) apps.json snapshot for per-tab widget-id sets
        assert driver.client is not None
        apps_resp = await driver.client.get("/apps.json")
        apps = apps_resp.json()
        for app in apps if isinstance(apps, list) else []:
            app_id = app.get("id") or app.get("name") or "unknown-app"
            layout_summary: dict[str, list[str]] = {}
            for tab_id, tab in app.get("tabs", {}).items():
                layout_summary[tab_id] = [slot["i"] for slot in tab.get("layout", [])]
            out = _LAYOUT_ROOT / f"{app_id}.json"
            out.write_text(
                json.dumps(layout_summary, indent=2, sort_keys=True), encoding="utf-8"
            )
            print(f"  wrote {out.relative_to(_LAYOUT_ROOT.parents[1])}")

        print(f"\nSnapshot complete. {n} endpoint fixtures written.")
        return 0
    finally:
        await driver.teardown()


def main() -> int:
    return asyncio.run(_snapshot_all())


if __name__ == "__main__":
    sys.exit(main())
