"""Workspace selector graph (B10, #1735).

Maps ``widget_id`` -> a Playwright locator selector so ``WorkspaceDriver``
can turn ``widget_visible`` and ``not_blank`` from ``"unverified"`` sentinels
into real UI assertions.

Design principle
----------------

The Workspace UI wraps every widget in a container carrying
``data-widget-id="<widget_id>"`` (the same identifier the backend serves
in ``widgets.json``). Inside each container the render is a table, chart,
markdown block, or metric card — one of four shapes determined by the
widget's ``type`` field.

We therefore build the selector graph in **two layers**:

1. **Container selector** (uniform across widgets):
   ``[data-widget-id="<widget_id>"]``
2. **Content selector** (dispatched by widget type):

   ==========  =====================================================
   type        content-not-blank selector (rooted inside container)
   ==========  =====================================================
   table       ``role=table`` OR ``table`` OR ``[data-testid=table]``
   chart       ``canvas`` OR ``svg`` OR ``[data-testid=chart]``
   markdown    ``[data-testid=markdown-body]`` OR any ``> *`` with text
   metric      ``[data-testid=metric-value]`` OR ``[class*=metric]``
   ==========  =====================================================

If a specific widget's DOM diverges from the type default, register an
override in ``_WIDGET_ID_OVERRIDES`` and the graph respects it.

Why not per-widget CSS classes
-------------------------------

Workspace ships a shared component library — every ``table`` widget uses
the same table component, every ``chart`` widget uses the same chart
component. Encoding type-based defaults keeps the graph small
(N ≈ 4 lines instead of N ≈ 60 lines) and the failure mode is loud: if
Workspace changes the container attribute name from ``data-widget-id`` to
``data-widget-slug``, EVERY widget fails at once, immediately flagging
the migration. That's the invariant we want.

This module is import-safe with or without Playwright installed — it only
returns strings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# ----------------------------------------------------------------------
# Public data
# ----------------------------------------------------------------------

CONTAINER_ATTR: str = "data-widget-id"
"""Attribute Workspace puts on every widget container."""


_TYPE_CONTENT_SELECTORS: dict[str, tuple[str, ...]] = {
    "table": (
        "[role='table']",
        "table",
        "[data-testid='widget-table']",
    ),
    "chart": (
        "canvas",
        "svg",
        "[data-testid='widget-chart']",
    ),
    "markdown": (
        "[data-testid='markdown-body']",
        "[data-testid='widget-markdown']",
        ".markdown-body",
    ),
    "metric": (
        "[data-testid='metric-value']",
        "[class*='metric']",
        "[data-testid='widget-metric']",
    ),
}
"""Ordered content-selector candidates per widget type.

The driver iterates them and considers the widget non-blank if ANY match
has non-empty ``innerText`` or non-zero bounding-box area.
"""

# Per-widget-id overrides for widgets whose DOM doesn't match its type default.
# Empty at launch — file an entry here when a widget's render is bespoke and
# has a stable ``data-testid`` we can pin.
_WIDGET_ID_OVERRIDES: dict[str, tuple[str, ...]] = {
    # example (currently unused, kept as documentation):
    # "pi_charting": ("[data-testid='trading-view-frame']",),
}


# ----------------------------------------------------------------------
# API
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class WidgetSelector:
    """Resolved selectors for a single widget."""

    widget_id: str
    widget_type: str  # "table" | "chart" | "markdown" | "metric"
    container: str  # e.g. '[data-widget-id="pi_xray_sector"]'
    content_candidates: tuple[str, ...]
    """Content selectors to try inside the container, in priority order."""


def container_selector(widget_id: str) -> str:
    """Return the Playwright selector for a widget's container."""
    # Quote for CSS attribute selectors; widget_ids in Workspace are
    # ``[a-z0-9_]``, but defensively escape any double-quotes.
    safe = widget_id.replace('"', r"\"")
    return f'[{CONTAINER_ATTR}="{safe}"]'


def content_selectors_for_type(widget_type: str) -> tuple[str, ...]:
    """Return content-not-blank selector candidates for the given type.

    Unknown types fall back to the union of the four defaults so we never
    return an empty tuple (silent failure).
    """
    known = _TYPE_CONTENT_SELECTORS.get(widget_type)
    if known:
        return known
    all_defaults: list[str] = []
    for sels in _TYPE_CONTENT_SELECTORS.values():
        all_defaults.extend(sels)
    return tuple(all_defaults)


def resolve(widget_id: str, widget_type: str) -> WidgetSelector:
    """Build a fully-resolved WidgetSelector for a widget id + type.

    Overrides in ``_WIDGET_ID_OVERRIDES`` take precedence over the type
    default.
    """
    if widget_id in _WIDGET_ID_OVERRIDES:
        content = _WIDGET_ID_OVERRIDES[widget_id]
    else:
        content = content_selectors_for_type(widget_type)
    return WidgetSelector(
        widget_id=widget_id,
        widget_type=widget_type,
        container=container_selector(widget_id),
        content_candidates=content,
    )


# ----------------------------------------------------------------------
# widgets.json -> endpoint->widget-selector index
# ----------------------------------------------------------------------


def _widgets_manifest_path() -> Path:
    """Absolute path to the extension's widgets.json.

    Layout (from ``src/openbb_browser_test_harness/selectors.py``):

        parents[0] = openbb_browser_test_harness/
        parents[1] = src/
        parents[2] = browser_test_harness/
        parents[3] = tools/
        parents[4] = openbb_platform/  <- widgets.json lives under here
    """
    return (
        Path(__file__).resolve().parents[4]
        / "extensions"
        / "portfolio_intel"
        / "openbb_portfolio_intel"
        / "widget_backend"
        / "widgets.json"
    )


@lru_cache(maxsize=1)
def load_endpoint_to_widget_selector() -> dict[str, WidgetSelector]:
    """Return endpoint -> WidgetSelector for every widget in the manifest.

    A step's ``endpoint`` field is the join key. The driver looks up the
    selector by endpoint (steps carry endpoint, not widget_id, in the
    current story model).

    Returns:
        Mapping from endpoint (str) to WidgetSelector.
    """
    manifest = json.loads(_widgets_manifest_path().read_text(encoding="utf-8"))
    out: dict[str, WidgetSelector] = {}
    for widget_id, spec in manifest.items():
        endpoint = spec.get("endpoint")
        widget_type = spec.get("type", "unknown")
        if not endpoint:
            continue
        # A single endpoint may back multiple widgets (rare in this
        # backend but possible). Keep the FIRST binding; test asserts
        # this is unambiguous.
        if endpoint not in out:
            out[endpoint] = resolve(widget_id, widget_type)
    return out


def selector_for_endpoint(endpoint: str) -> WidgetSelector | None:
    """Look up the WidgetSelector backing an endpoint, or None."""
    return load_endpoint_to_widget_selector().get(endpoint)
