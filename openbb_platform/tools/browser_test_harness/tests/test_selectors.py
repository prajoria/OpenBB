"""Selector-graph tests (B10, #1735).

The graph builds a widget_id -> DOM-selector map from widgets.json. These
tests are pure-python (no Playwright required) — they assert graph shape,
coverage, and the load-bearing invariant that every widget in the manifest
has a resolvable selector.
"""

from __future__ import annotations

import json
from pathlib import Path

from openbb_browser_test_harness.selectors import (
    CONTAINER_ATTR,
    _TYPE_CONTENT_SELECTORS,
    container_selector,
    content_selectors_for_type,
    load_endpoint_to_widget_selector,
    resolve,
    selector_for_endpoint,
)
from openbb_browser_test_harness.stories import STORIES


def _widgets_json_path() -> Path:
    # tests/ -> browser_test_harness/ -> tools/ -> openbb_platform/
    return (
        Path(__file__).resolve().parents[3]
        / "extensions"
        / "portfolio_intel"
        / "openbb_portfolio_intel"
        / "widget_backend"
        / "widgets.json"
    )


def test_container_selector_is_stable() -> None:
    """The container attribute matches Workspace's contract."""
    assert CONTAINER_ATTR == "data-widget-id"
    assert (
        container_selector("pi_xray_sector") == '[data-widget-id="pi_xray_sector"]'
    )


def test_container_selector_escapes_double_quotes() -> None:
    """Defensive: a widget_id with a double-quote in it must not break the CSS."""
    got = container_selector('bad"id')
    assert 'bad\\"id' in got


def test_type_defaults_cover_all_four_shapes() -> None:
    """Workspace ships four widget shapes; graph must know all four."""
    assert set(_TYPE_CONTENT_SELECTORS) == {"table", "chart", "markdown", "metric"}
    # Every shape has at least one selector.
    for shape, sels in _TYPE_CONTENT_SELECTORS.items():
        assert len(sels) >= 1, f"{shape} has no content selectors"


def test_unknown_type_falls_back_to_union() -> None:
    """Unknown widget types get the union of all four defaults.

    This is the anti-silent-failure guard: a new widget type appearing in
    a Workspace release shouldn't return an empty tuple (which would make
    every widget of that type silently 'blank').
    """
    got = content_selectors_for_type("brand-new-shape")
    assert got, "unknown type must not return empty tuple"


def test_resolve_returns_container_plus_content() -> None:
    ws = resolve("pi_xray_sector", "table")
    assert ws.widget_id == "pi_xray_sector"
    assert ws.widget_type == "table"
    assert ws.container == '[data-widget-id="pi_xray_sector"]'
    assert len(ws.content_candidates) >= 1


def test_every_widget_in_manifest_resolves_to_a_selector() -> None:
    """The load-bearing B10 invariant — every widget has a selector.

    If a widget lands in widgets.json without a type the graph knows,
    ``content_selectors_for_type`` returns the union fallback, and this
    test PASSES (loud warning becomes visible in production instead of
    silent failure). But if the manifest schema changes such that
    ``endpoint`` disappears, this test loudly fails.
    """
    manifest = json.loads(_widgets_json_path().read_text(encoding="utf-8"))
    for widget_id, spec in manifest.items():
        assert "endpoint" in spec, f"{widget_id} missing endpoint"
        selector = resolve(widget_id, spec.get("type", "unknown"))
        assert selector.container.startswith("[data-widget-id="), (
            f"container malformed for {widget_id}: {selector.container}"
        )
        assert selector.content_candidates, (
            f"{widget_id} type={spec.get('type')} has no content candidates"
        )


def test_endpoint_index_covers_every_story_endpoint() -> None:
    """Every endpoint any story hits must be resolvable to a WidgetSelector.

    This ties B10 to B8's 100% widget coverage: since every widget is now
    exercised by SOME story step, and every widget appears in the
    endpoint-index, the workspace driver has a real selector for every
    endpoint-taking step. No silent 'unverified' sentinels for shape-known
    endpoints.
    """
    index = load_endpoint_to_widget_selector()
    story_endpoints: set[str] = set()
    for story in STORIES.values():
        for step in story.steps:
            if step.endpoint:
                story_endpoints.add(step.endpoint)
    missing = [ep for ep in story_endpoints if ep not in index]
    assert not missing, (
        f"{len(missing)} endpoint(s) exercised by stories have no selector:\n  "
        + "\n  ".join(sorted(missing))
        + "\n\nAdd the widget to widgets.json OR the endpoint is not backed "
        "by a UI widget (e.g. a chrome/context endpoint). If the latter, "
        "these steps are still valid — but consider filing a follow-up."
    )


def test_selector_for_endpoint_returns_none_for_unknown() -> None:
    """Non-widget endpoints (chrome/context) return None gracefully."""
    assert selector_for_endpoint("pi/nonexistent/endpoint") is None


def test_cache_is_lru() -> None:
    """The endpoint index is cached so repeated lookups don't reparse JSON."""
    first = load_endpoint_to_widget_selector()
    second = load_endpoint_to_widget_selector()
    assert first is second, "load_endpoint_to_widget_selector should be cached"
