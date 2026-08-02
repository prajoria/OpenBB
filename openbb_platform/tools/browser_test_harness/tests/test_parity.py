"""Parity test — every Step in every Story loads cleanly and has a matching
notebook anchor (spec §2 parity gate).

Full manual-guide-vs-automation parity ships with B5 (#1727) — this file
tests the code-side parity invariants B0 can enforce today.
"""

from __future__ import annotations

from openbb_browser_test_harness.stories import STORIES


def test_no_step_belongs_to_more_than_one_story() -> None:
    seen: dict[str, str] = {}
    for story in STORIES.values():
        for step in story.steps:
            assert (
                step.id not in seen
            ), f"step {step.id!r} in both {story.id!r} and {seen[step.id]!r}"
            seen[step.id] = story.id


def test_all_steps_have_notebook_ref() -> None:
    for story in STORIES.values():
        for step in story.steps:
            assert step.notebook_ref, f"step {step.id!r} missing notebook_ref"


def test_all_steps_have_prose_fields() -> None:
    """Manual guide generation requires human_* fields to be non-empty."""
    for story in STORIES.values():
        for step in story.steps:
            assert step.human_title, f"step {step.id!r} missing human_title"
            assert (
                step.human_description
            ), f"step {step.id!r} missing human_description"
            assert step.human_expected, f"step {step.id!r} missing human_expected"


def test_safety_tagged_steps_are_asserts() -> None:
    """Any step tagged 'safety' MUST be action=ASSERT — otherwise it's just a
    label with no test discrimination behind it."""
    from openbb_browser_test_harness.steps import ActionKind

    for story in STORIES.values():
        for step in story.steps:
            if "safety" in step.tags:
                assert step.action == ActionKind.ASSERT, (
                    f"step {step.id!r} is tagged 'safety' but action="
                    f"{step.action.value!r}; must be ASSERT"
                )
