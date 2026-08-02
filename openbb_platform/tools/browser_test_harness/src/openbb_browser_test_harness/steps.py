"""Step + Story + StepResult data model.

Single source of truth for both the manual guide generator (B5, #1727) and the
automation driver (B1 standalone #1723, B6 workspace #1728).

Spec: docs/superpowers/specs/2026-08-01-browser-test-harness-design.md §4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Persona(str, Enum):
    """Who this step is written for (used in manual-guide rendering)."""

    ANALYST = "analyst"
    PM = "pm"
    SYSTEMATIC_TRADER = "systematic_trader"


class ActionKind(str, Enum):
    """Kind of action the tester (human or automation) takes at this step."""

    NAVIGATE = "navigate"  # go to a tab
    OBSERVE = "observe"  # read a widget value
    INPUT = "input"  # type into a param field
    SCREENSHOT = "screenshot"  # capture current state
    ASSERT = "assert"  # check a load-bearing invariant


@dataclass(frozen=True)
class Step:
    """A single step in a Story.

    Every field is required for the manual guide AND the automation driver so
    the two cannot silently diverge. Parity is enforced by
    ``tests/test_parity.py``.
    """

    # Identity
    id: str  # e.g. "W3.observe.xray-sector" — MUST be unique across all stories
    story: str  # "portfolio" or "techtrade"
    notebook_ref: str  # e.g. "notebooks/portfolio/03-basket-xray-and-risk.ipynb"
    persona: Persona
    tab_id: str  # matches apps.json tab id
    action: ActionKind

    # Manual-mode fields (what a human reads in guides/*-manual-guide.md)
    human_title: str  # "Step W3 — Check the X-Ray sector breakdown"
    human_description: str  # 1-3 sentences of prose
    human_expected: str  # what the tester should see

    # Automation-mode fields (what the driver executes)
    endpoint: str | None = None  # e.g. "pi/xray/sector"
    params: dict[str, str] = field(default_factory=dict)
    expected_status: int = 200
    expected_shape_fixture: str | None = (
        None  # path under fixtures/expected_responses/
    )

    # Cross-cutting
    screenshot_name: str | None = None  # if None, derived from id
    tags: tuple[str, ...] = ()  # e.g. ("safety", "verdict-gates-execute")

    def __post_init__(self) -> None:
        # P1-7 schema guard: ASSERT-kind steps MUST have either a fixture OR a
        # registered checker tag. Steps that assert nothing are ceremonial.
        if self.action == ActionKind.ASSERT:
            has_fixture = self.expected_shape_fixture is not None
            has_checker_tag = any(t.startswith("checker:") for t in self.tags)
            if not (has_fixture or has_checker_tag):
                raise ValueError(
                    f"Step {self.id!r} has action=ASSERT but no fixture and no "
                    "checker: tag. ASSERT steps without either are ceremonial "
                    "(pass by doing nothing) — see spec §9 P1-7."
                )

    @property
    def resolved_screenshot_name(self) -> str:
        """Deterministic screenshot filename derived from the step id."""
        return self.screenshot_name or f"{self.id}.png"


@dataclass(frozen=True)
class Story:
    """An ordered list of Steps mapping to a notebook arc.

    Both the manual guide generator and the automation driver consume this
    single object. Adding a step to only one side is impossible by design.
    """

    id: str  # "portfolio" or "techtrade"
    title: str
    notebook_series_root: str  # e.g. "notebooks/portfolio/"
    steps: tuple[Step, ...]

    def __post_init__(self) -> None:
        # Every step in a story must claim membership to that story.
        for step in self.steps:
            if step.story != self.id:
                raise ValueError(
                    f"Step {step.id!r} claims story={step.story!r} but is in "
                    f"Story {self.id!r}"
                )
        # Step ids must be unique within the story.
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            dupes = [x for x in ids if ids.count(x) > 1]
            raise ValueError(f"Story {self.id!r} has duplicate step ids: {dupes}")


@dataclass
class StepResult:
    """The output of running one Step through one Driver.

    Both drivers (standalone HTTP and Playwright workspace) return the same
    shape so the report renderer is driver-agnostic.

    Note the ``"n/a"`` sentinel for standalone-mode observations that require
    a browser (P2-9 fix): standalone driver cannot verify "widget_visible" or
    "not_blank" and must not silently claim True.
    """

    step_id: str
    ok: bool
    duration_ms: int
    screenshot_path: str | None
    observations: dict[str, object]
    error: str | None = None
    # SHA-256 of the screenshot file, for future baseline diff (P2-10)
    screenshot_sha256: str | None = None
