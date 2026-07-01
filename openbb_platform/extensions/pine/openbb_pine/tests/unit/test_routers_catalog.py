"""Tests for :mod:`openbb_pine.routers.catalog_router` (P1 — bead 0e9.5.52).

Pin the two read-only GET endpoints:

* ``/pine/indicators/list`` returns the bundled-widget catalog loaded from
  :func:`openbb_pine._load_bundled_widgets`. Wave 5B-5 (P2 bead 0e9.5.53)
  ships the first entry — ``pine_bollinger_bands``. When the catalog is
  empty (widgets.json removed for a dev build) the endpoint returns
  ``[]`` plus a ``PineCatalogEmpty`` warning.
* ``/pine/builtins/coverage`` reads the
  :mod:`openbb_pine._coverage_manifest` frozensets verbatim — Phase 0
  baseline = all counts at zero, ``pine_versions_known`` always [5, 6].

Monkeypatch the manifest frozensets to verify the sort + count plumbing
without waiting for sibling beads to land a real implementation.
"""

from __future__ import annotations

from openbb_core.app.model.obbject import OBBject

from openbb_pine.routers._models import (
    BuiltinsCoverage,
    BundledIndicatorEntry,
)


# ---------------------------------------------------------------------------
# /pine/indicators/list
# ---------------------------------------------------------------------------


def test_indicators_list_returns_obbject_list():
    from openbb_pine.routers.catalog_router import indicators_list

    obj = indicators_list()
    assert isinstance(obj, OBBject)
    assert isinstance(obj.results, list)


def test_indicators_list_empty_when_widgets_missing(monkeypatch):
    """When widgets.json is absent, the endpoint returns ``[]`` cleanly."""
    import openbb_pine.routers.catalog_router as cr

    monkeypatch.setattr(cr, "_load_bundled_widgets", lambda: {})
    obj = cr.indicators_list()
    assert obj.results == []


def test_indicators_list_carries_empty_warning_when_widgets_missing(monkeypatch):
    """Empty catalog must surface a warning so callers can distinguish
    'intentional empty' from 'endpoint broken'."""
    import openbb_pine.routers.catalog_router as cr

    monkeypatch.setattr(cr, "_load_bundled_widgets", lambda: {})
    obj = cr.indicators_list()
    assert obj.warnings is not None
    assert len(obj.warnings) == 1
    w = obj.warnings[0]
    assert w.category == "PineCatalogEmpty"
    assert "Phase 1" in w.message or "bundled indicators" in w.message


def test_indicators_list_populated_from_widgets_json(monkeypatch):
    """When the catalog is populated, the warning drops and each widget
    surfaces as a typed :class:`BundledIndicatorEntry`."""
    import openbb_pine.routers.catalog_router as cr

    fake_widget = {
        "name": "Pine — Bollinger Bands",
        "description": "20-period Bollinger Bands (2σ) via openbb-pine.",
        "category": "technical-analysis",
        "type": "chart",
        "endpoint": "/api/v1/pine/run",
    }
    monkeypatch.setattr(
        cr, "_load_bundled_widgets", lambda: {"pine_bollinger_bands": fake_widget}
    )
    obj = cr.indicators_list()
    assert len(obj.results) == 1
    entry = obj.results[0]
    assert isinstance(entry, BundledIndicatorEntry)
    assert entry.name == "Pine — Bollinger Bands"
    assert entry.pine_source_path == "inline:pine_bollinger_bands"
    assert entry.description.startswith("20-period Bollinger Bands")
    assert entry.pine_version == 6
    # No warning when populated.
    assert obj.warnings is None


def test_indicators_list_surfaces_shipped_bollinger_widget():
    """Integration-shape: the shipped widgets.json contains one entry
    named 'Pine — Bollinger Bands' (D3 §16 / PRD §8.1 M1 gate (c))."""
    from openbb_pine.routers.catalog_router import indicators_list

    obj = indicators_list()
    names = [e.name for e in obj.results]
    assert "Pine — Bollinger Bands" in names, (
        f"P2 widget missing from catalog; got names={names!r}"
    )


# ---------------------------------------------------------------------------
# /pine/builtins/coverage
# ---------------------------------------------------------------------------


def test_builtins_coverage_returns_obbject_with_typed_payload():
    from openbb_pine.routers.catalog_router import builtins_coverage

    obj = builtins_coverage()
    assert isinstance(obj, OBBject)
    assert isinstance(obj.results, BuiltinsCoverage)


def test_builtins_coverage_phase_0_baseline_is_zero(monkeypatch):
    """Phase 0: every frozenset is empty -> count=0, lists=[]."""
    from openbb_pine import _coverage_manifest
    from openbb_pine.routers.catalog_router import builtins_coverage

    monkeypatch.setattr(_coverage_manifest, "PINE_VERSIONS_SUPPORTED", frozenset())
    monkeypatch.setattr(_coverage_manifest, "BUILTINS_IMPLEMENTED", frozenset())
    monkeypatch.setattr(_coverage_manifest, "FEATURES_IMPLEMENTED", frozenset())

    obj = builtins_coverage()
    assert obj.results.builtins_implemented_count == 0
    assert obj.results.builtins_implemented == []
    assert obj.results.features_implemented == []
    assert obj.results.pine_versions_supported == []
    # Architecture-supported versions are independent of what's implemented.
    assert obj.results.pine_versions_known == [5, 6]


def test_builtins_coverage_reads_manifest_implemented(monkeypatch):
    from openbb_pine import _coverage_manifest
    from openbb_pine.routers.catalog_router import builtins_coverage

    monkeypatch.setattr(
        _coverage_manifest,
        "BUILTINS_IMPLEMENTED",
        frozenset({"ta.sma", "math.abs", "ta.crossover"}),
    )
    obj = builtins_coverage()
    assert obj.results.builtins_implemented_count == 3
    # Sorted output — frozenset iteration order is implementation-defined.
    assert obj.results.builtins_implemented == ["math.abs", "ta.crossover", "ta.sma"]


def test_builtins_coverage_reads_manifest_features(monkeypatch):
    from openbb_pine import _coverage_manifest
    from openbb_pine.routers.catalog_router import builtins_coverage

    monkeypatch.setattr(
        _coverage_manifest,
        "FEATURES_IMPLEMENTED",
        frozenset({"indicator", "strategy"}),
    )
    obj = builtins_coverage()
    assert obj.results.features_implemented == ["indicator", "strategy"]


def test_builtins_coverage_reads_manifest_versions_supported(monkeypatch):
    from openbb_pine import _coverage_manifest
    from openbb_pine.routers.catalog_router import builtins_coverage

    monkeypatch.setattr(
        _coverage_manifest, "PINE_VERSIONS_SUPPORTED", frozenset({6})
    )
    obj = builtins_coverage()
    assert obj.results.pine_versions_supported == [6]


def test_builtins_coverage_pine_versions_known_is_constant():
    """The 'could-eventually-support' set is independent of what's shipped."""
    from openbb_pine.routers.catalog_router import builtins_coverage

    obj = builtins_coverage()
    assert obj.results.pine_versions_known == [5, 6]
