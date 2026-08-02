"""emit_guide tests (B5, #1727).

Verifies the generator emits Markdown for both stories that contains every
step's key metadata and load-bearing safety markers.
"""

from __future__ import annotations

from openbb_browser_test_harness.emit_guide import _emit_guide
from openbb_browser_test_harness.steps import ActionKind
from openbb_browser_test_harness.stories import PORTFOLIO_STORY, TECHTRADE_STORY


def test_portfolio_guide_includes_every_step_id() -> None:
    md = _emit_guide(PORTFOLIO_STORY)
    for step in PORTFOLIO_STORY.steps:
        assert f"`{step.id}`" in md, f"missing step id {step.id!r} in guide"


def test_techtrade_guide_includes_every_step_id() -> None:
    md = _emit_guide(TECHTRADE_STORY)
    for step in TECHTRADE_STORY.steps:
        assert f"`{step.id}`" in md, f"missing step id {step.id!r} in guide"


def test_safety_tagged_steps_show_warning_marker() -> None:
    """Steps tagged 'safety' must render the ⚠️ Safety invariant warning."""
    for story in (PORTFOLIO_STORY, TECHTRADE_STORY):
        md = _emit_guide(story)
        for step in story.steps:
            if "safety" in step.tags:
                # Marker text should follow the step-id header.
                assert "Safety invariant" in md
                assert step.id in md


def test_guide_embeds_screenshot_placeholder_per_step() -> None:
    """Every step's manual guide block references a screenshot path
    matching the pattern B6 will populate."""
    for story in (PORTFOLIO_STORY, TECHTRADE_STORY):
        md = _emit_guide(story)
        for step in story.steps:
            expected = f"screenshots/{story.id}/{step.resolved_screenshot_name}"
            assert expected in md, (
                f"missing screenshot placeholder for {step.id}: {expected}"
            )


def test_guide_prep_section_documents_the_manual_backend_start() -> None:
    md = _emit_guide(PORTFOLIO_STORY)
    assert "uvicorn openbb_portfolio_intel.widget_backend.main:app" in md
    assert "PI_WIDGET_BACKEND_AUTH_MODE" in md


def test_guide_lists_notebook_series_root_link() -> None:
    md = _emit_guide(PORTFOLIO_STORY)
    assert "notebooks/portfolio/" in md
    md_tt = _emit_guide(TECHTRADE_STORY)
    assert "notebooks/techtrade/" in md_tt


def test_guide_regeneration_command_documented() -> None:
    md = _emit_guide(PORTFOLIO_STORY)
    assert "emit_guide --story portfolio" in md


def test_action_verbs_render_correctly() -> None:
    """Sanity check on the action-verb table — reveals typos immediately."""
    md = _emit_guide(TECHTRADE_STORY)
    # T5.execute-blocked is ASSERT-kind and safety-tagged.
    execute_blocked = next(
        s for s in TECHTRADE_STORY.steps if s.id == "T5.execute-blocked"
    )
    assert execute_blocked.action == ActionKind.ASSERT
    assert "Assert (safety invariant)" in md
