"""Story schema tests — every Story loads, every Step's schema validates.

Design spec: §9 P1-7 (ASSERT-kind steps must have fixture or checker tag)
"""

from __future__ import annotations

import pytest

from openbb_browser_test_harness.steps import ActionKind, Step, Story
from openbb_browser_test_harness.stories import PORTFOLIO_STORY, STORIES, TECHTRADE_STORY


def test_both_stories_load() -> None:
    assert "portfolio" in STORIES
    assert "techtrade" in STORIES


def test_portfolio_story_has_16_steps() -> None:
    assert len(PORTFOLIO_STORY.steps) == 16


def test_techtrade_story_has_12_steps() -> None:
    assert len(TECHTRADE_STORY.steps) == 12


def test_all_step_ids_are_unique_within_story() -> None:
    for story in STORIES.values():
        ids = [s.id for s in story.steps]
        assert len(ids) == len(set(ids)), f"duplicate ids in {story.id}"


def test_all_step_notebook_refs_start_with_notebooks() -> None:
    """Narrative anchor: every step points at a real notebook path."""
    for story in STORIES.values():
        for step in story.steps:
            assert step.notebook_ref.startswith("notebooks/"), (
                f"{step.id}: notebook_ref must anchor to notebooks/ tree, "
                f"got {step.notebook_ref!r}"
            )


def test_p1_7_assert_steps_have_fixture_or_checker_tag() -> None:
    """§9 P1-7: ASSERT steps must have a fixture OR a checker: tag."""
    for story in STORIES.values():
        for step in story.steps:
            if step.action != ActionKind.ASSERT:
                continue
            has_fixture = step.expected_shape_fixture is not None
            has_checker = any(t.startswith("checker:") for t in step.tags)
            assert has_fixture or has_checker, (
                f"ASSERT step {step.id!r} has no fixture and no checker: tag "
                "— see spec §9 P1-7."
            )


def test_step_frozen_raises_on_ceremonial_assert() -> None:
    """R7.11 mutation: authoring an ASSERT with no fixture/tag must raise."""
    with pytest.raises(ValueError, match="ceremonial"):
        Step(
            id="bad",
            story="portfolio",
            notebook_ref="notebooks/portfolio/01-getting-started-and-providers.ipynb",
            persona=step_persona_analyst_or_die(),
            tab_id="overview",
            action=ActionKind.ASSERT,
            human_title="bad",
            human_description="bad",
            human_expected="bad",
            # No fixture, no checker tag.
        )


def step_persona_analyst_or_die():
    """Helper for the ceremonial-assert test."""
    from openbb_browser_test_harness.steps import Persona

    return Persona.ANALYST


def test_story_rejects_step_with_wrong_story_id() -> None:
    """Guard against copy-paste error where a Step's story field mismatches."""
    from openbb_browser_test_harness.steps import Persona

    bad_step = Step(
        id="X.wrong",
        story="techtrade",  # WRONG on purpose
        notebook_ref="notebooks/portfolio/01-getting-started-and-providers.ipynb",
        persona=Persona.ANALYST,
        tab_id="overview",
        action=ActionKind.OBSERVE,
        human_title="",
        human_description="",
        human_expected="",
    )
    with pytest.raises(ValueError, match="claims story"):
        Story(
            id="portfolio",
            title="",
            notebook_series_root="notebooks/portfolio/",
            steps=(bad_step,),
        )
