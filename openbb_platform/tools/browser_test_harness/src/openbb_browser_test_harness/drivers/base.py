"""Driver Protocol — both standalone (B1 #1723) and workspace (B6 #1728) implement.

Spec: docs/superpowers/specs/2026-08-01-browser-test-harness-design.md §5
"""

from __future__ import annotations

from typing import Protocol

from ..steps import Step, StepResult


class Driver(Protocol):
    """A driver runs Story steps and produces StepResults.

    Two implementations:

    - ``StandaloneDriver`` — subprocess + httpx, no browser. CI-friendly.
    - ``WorkspaceDriver`` — Playwright chromium + persistent-context or CDP
      attach. Requires user login to Workspace.
    """

    async def setup(self) -> None:
        """Spawn any resources (subprocess, browser). Idempotent."""

    async def teardown(self) -> None:
        """Kill spawned resources cleanly. Idempotent."""

    async def run_step(self, step: Step) -> StepResult:
        """Execute one step and return the observation."""
