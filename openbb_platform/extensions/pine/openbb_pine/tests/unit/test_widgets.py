"""Tests for the P2 Workspace-widget bundle (bead 0e9.5.53).

Locks the wire-shape of ``openbb_pine/assets/widgets.json`` and the
:func:`openbb_pine._load_bundled_widgets` loader:

1. widgets.json exists at the canonical asset path and parses as strict
   JSON.
2. The M1 acceptance-gate (PRD §8.1 M1 gate (c)) — the
   ``pine_bollinger_bands`` entry — is present with the required shape:
   ``name``, ``description``, ``category``, ``type``, ``endpoint``,
   ``params``, ``footer``.
3. Footer literal exactly equals
   :data:`openbb_pine.attribution.POWERED_BY_FULL` — the 4-of-4
   attribution CI test surface #2 depends on this pin.
4. The bundled Pine source in ``params.source`` compiles cleanly via
   :func:`openbb_pine.compiler.compile_pine` — a broken widget source
   would fail the M1 gate.

The loader:
* Returns ``{}`` when the file is missing (dev-mode).
* Raises :class:`ValueError` when the file is malformed (never silent).
* Returns a ``dict[str, dict]`` when the file is valid.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openbb_pine import _load_bundled_widgets, _WIDGETS_JSON
from openbb_pine.attribution import POWERED_BY_FULL
from openbb_pine.compiler import compile_pine


# ---------------------------------------------------------------------------
# widgets.json shape / presence
# ---------------------------------------------------------------------------


def test_widgets_json_exists_at_canonical_asset_path() -> None:
    """The P2 bundle ships widgets.json at ``openbb_pine/assets/widgets.json``."""
    assert _WIDGETS_JSON.is_file(), (
        f"widgets.json not found at {_WIDGETS_JSON}"
    )


def test_widgets_json_is_strict_json() -> None:
    """widgets.json must be parseable as strict JSON (no trailing commas)."""
    text = _WIDGETS_JSON.read_text(encoding="utf-8")
    parsed = json.loads(text)  # raises on malformed
    assert isinstance(parsed, dict), (
        f"widgets.json top-level must be object, got {type(parsed).__name__}"
    )


def test_widgets_json_has_pine_bollinger_bands_entry() -> None:
    """PRD §8.1 M1 gate (c) — the Bollinger Bands widget must ship."""
    widgets = _load_bundled_widgets()
    assert "pine_bollinger_bands" in widgets, (
        f"pine_bollinger_bands missing from widgets.json; "
        f"got keys={sorted(widgets)!r}"
    )


def test_bollinger_widget_has_required_fields() -> None:
    """Each widget must carry the fields the Workspace UI + MCP hook use."""
    spec = _load_bundled_widgets()["pine_bollinger_bands"]
    required_fields = {
        "name",
        "description",
        "category",
        "type",
        "endpoint",
        "params",
        "footer",
    }
    missing = required_fields - set(spec)
    assert not missing, (
        f"pine_bollinger_bands widget missing fields: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Footer == POWERED_BY_FULL (attribution surface #2)
# ---------------------------------------------------------------------------


def test_bollinger_widget_footer_matches_powered_by_full() -> None:
    """Widget footer must be the EXACT PyneCore §4(d) attribution literal.

    This is what the ``test_all_four_pynecore_attribution_surfaces`` test
    (Wave 1E) uses to gate CI on attribution correctness across all four
    surfaces (about, widget footer, health, CLI banner).
    """
    spec = _load_bundled_widgets()["pine_bollinger_bands"]
    assert spec["footer"] == POWERED_BY_FULL, (
        f"widget footer drifted from POWERED_BY_FULL:\n"
        f"  widget: {spec['footer']!r}\n"
        f"  canonical: {POWERED_BY_FULL!r}"
    )


# ---------------------------------------------------------------------------
# The bundled Pine source itself compiles
# ---------------------------------------------------------------------------


def test_bollinger_widget_pine_source_compiles_cleanly() -> None:
    """The Pine source embedded in ``params.source`` must compile via
    :func:`compile_pine` — a broken widget source would fail the M1 gate."""
    spec = _load_bundled_widgets()["pine_bollinger_bands"]
    pine_source = spec["params"]["source"]
    module = compile_pine(pine_source)
    # Sanity: the emitted Python must reference ta.sma + ta.stdev (the two
    # Bollinger-Bands primitives).
    assert "ta.sma" in module.builtins_used
    assert "ta.stdev" in module.builtins_used


def test_bollinger_widget_endpoint_is_pine_run() -> None:
    """The widget must route to the Pine-run endpoint (D3 §4.3)."""
    spec = _load_bundled_widgets()["pine_bollinger_bands"]
    assert spec["endpoint"] == "/api/v1/pine/run"


def test_bollinger_widget_defaults_fmp_cached_provider() -> None:
    """The M1 default provider is fmp_cached — free-tier friendly."""
    params = _load_bundled_widgets()["pine_bollinger_bands"]["params"]
    assert params.get("provider") == "fmp_cached"


# ---------------------------------------------------------------------------
# _load_bundled_widgets loader behavior
# ---------------------------------------------------------------------------


def test_loader_returns_dict() -> None:
    """The public shape is ``dict[str, dict]`` — never None, never a list."""
    widgets = _load_bundled_widgets()
    assert isinstance(widgets, dict)


def test_loader_returns_empty_dict_when_file_missing(monkeypatch, tmp_path) -> None:
    """A missing widgets.json is not an error — dev builds may strip it."""
    import openbb_pine as pkg

    fake_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(pkg, "_WIDGETS_JSON", fake_path)
    assert pkg._load_bundled_widgets() == {}


def test_loader_raises_on_malformed_json(monkeypatch, tmp_path) -> None:
    """A malformed widgets.json must surface as a ValueError — silent
    fallback would hide an incident."""
    import openbb_pine as pkg

    bad = tmp_path / "widgets.json"
    bad.write_text("{ this is not valid json }", encoding="utf-8")
    monkeypatch.setattr(pkg, "_WIDGETS_JSON", bad)
    with pytest.raises(json.JSONDecodeError):
        pkg._load_bundled_widgets()


def test_loader_raises_on_non_object_top_level(monkeypatch, tmp_path) -> None:
    """A JSON list at the top level is a schema violation — reject it
    rather than let the router blow up later on missing keys."""
    import openbb_pine as pkg

    bad = tmp_path / "widgets.json"
    bad.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(pkg, "_WIDGETS_JSON", bad)
    with pytest.raises(ValueError, match="top-level type must be an object"):
        pkg._load_bundled_widgets()
