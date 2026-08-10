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


# Steps whose endpoint hits a live external provider (fmp_cached, yfinance,
# etc.) and returns nondeterministic content (timestamps, recomputed values).
# These are exercised at run-time but excluded from drift comparison — the
# fixture proves the endpoint responds 200; the response shape is validated
# by the story step's expected_status.
_NONDETERMINISTIC_STEP_IDS: frozenset[str] = frozenset(
    {
        "CX.equity-analyst-forecasts",  # hits live fmp_cached; drifts with server clock
        # T5.paper-status-empty reads from ~/.portfolio_intel/paper.db.
        # If a prior CI step or a runner-level artifact created that file,
        # the "no batches yet" body diverges from the fixture. The
        # standalone-harness (TestClient) test asserts the body shape
        # with a controlled env; this drift check just proves the
        # endpoint responds 200 without touching state.
        "T5.paper-status-empty",
        # --- Live-wired / environment-dependent endpoints (#1878) ---
        # These four were originally deterministic stubs, but the recent
        # widget-wiring cycles made them serve real, environment-dependent
        # content. Their body no longer has a single frozen value that holds
        # across dev / CI / prod, so — like ``CX.equity-analyst-forecasts``
        # above — the drift check guarantees only that the endpoint is
        # callable (status 200); the response *shape* is asserted by each
        # story step's expected_status + the endpoint's own unit tests.
        #
        # W0.provider-health: since #1956 the server registers real
        # reachability probers at startup, so the strip renders live per-tier
        # HTTP-HEAD latencies (e.g. ``fmp_cached (436ms)``) that vary every
        # run. #1961 also dropped the Track B row. Body is inherently
        # nondeterministic.
        "W0.provider-health",
        # W1.key-stats: live-wired to fmp_cached (#1958). Values (market cap,
        # P/E, volume, next-earnings date) drift with the server clock and
        # market data; the fabricated stub fields it replaced no longer exist.
        "W1.key-stats",
        # CX.equity-price-history: live-wired to fmp_cached. The OHLC series
        # ends at the latest trading session, so it drifts with the clock.
        "CX.equity-price-history",
        # CX.company-filings: live-wired to fmp_cached (#1914/#1935). New
        # filings appear over time and the shape was realigned to the live
        # tier, so the body is not a frozen value.
        "CX.company-filings",
        # T5.engine-status: full-wired to observable engine state (#1931) —
        # openbb_techtrade version + capability matrix + configured paper
        # backend (PI_PAPER_ENGINE). The body depends on whether the engine
        # is installed and which backend is configured, i.e. it drifts across
        # deploy environments (CI has no openbb_techtrade → import fallback).
        "T5.engine-status",
    }
)


@pytest.mark.skipif(
    os.environ.get("BROWSER_HARNESS_LIVE") != "1",
    reason=(
        "Live subprocess test — set BROWSER_HARNESS_LIVE=1 to enable. "
        "This test is slow (spawns uvicorn) so it's opt-in in CI."
    ),
)
@pytest.mark.asyncio
async def test_fixtures_are_current() -> None:
    """Every endpoint fixture matches the current backend response.

    Nondeterministic endpoints (see _NONDETERMINISTIC_STEP_IDS) are
    exercised but not diffed — their fixtures only guarantee the
    endpoint is callable, not that the body is byte-identical.
    """
    # Extended step_timeout for endpoints that hit live fmp_cached.
    driver = StandaloneDriver(step_timeout_s=30.0)
    await driver.setup()
    drifted: list[str] = []
    try:
        for step in _all_endpoint_steps():
            fixture_path = _FIXTURE_ROOT / f"{step.id}.json"
            if not fixture_path.exists():
                drifted.append(f"MISSING: {fixture_path.name}")
                continue
            assert driver.client is not None
            path = (
                step.endpoint
                if step.endpoint.startswith("/")
                else f"/{step.endpoint}"
            )
            resp = await driver.client.get(path, params=step.params)
            # For nondeterministic steps: only check status_code equals fixture.
            if step.id in _NONDETERMINISTIC_STEP_IDS:
                saved = json.loads(fixture_path.read_text(encoding="utf-8"))
                if saved.get("status_code") != resp.status_code:
                    drifted.append(f"{step.id} (status_code diff)")
                continue
            saved = json.loads(fixture_path.read_text(encoding="utf-8"))
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
