"""Tests for :mod:`openbb_pine.routers.strategies_router` — /list endpoint (#588).

Mirrors the ``/pine/indicators/list`` pattern established in D3 §4.4 /
:mod:`openbb_pine.routers.catalog_router`. Locks down:

* Bare ``OBBject`` return (PRD §16.6 — no typed generics on
  ``@router.command`` return annotations).
* ``results`` is always a ``list`` (possibly empty).
* When no bundled strategies are shipped, results is ``[]`` and a
  ``PineStrategyCatalogEmpty`` warning fires so callers distinguish
  "no strategies bundled yet" from "endpoint broken".
* When populated (monkeypatched fixture), each entry surfaces as a
  typed :class:`BundledStrategyEntry` with the fields projected off the
  strategies.json spec.
* No side channel: the loader is a module-level seam
  (:func:`_load_bundled_strategies`) tests can monkeypatch, same as
  :func:`_load_bundled_widgets` on the indicators side.
"""

from __future__ import annotations

from openbb_core.app.model.obbject import OBBject

from openbb_pine.routers._models import BundledStrategyEntry

# ---------------------------------------------------------------------------
# /pine/strategies/list — shape
# ---------------------------------------------------------------------------


def test_strategies_list_returns_obbject_list():
    """Endpoint returns a bare ``OBBject`` whose ``results`` is a list (D3 §4.4 shape)."""
    from openbb_pine.routers.strategies_router import strategies_list

    obj = strategies_list()
    assert isinstance(obj, OBBject)
    assert isinstance(obj.results, list)


def test_strategies_list_empty_when_catalog_missing(monkeypatch):
    """When strategies.json is absent, the endpoint returns ``[]`` cleanly."""
    import openbb_pine.routers.strategies_router as sr

    monkeypatch.setattr(sr, "_load_bundled_strategies", lambda: {})
    obj = sr.strategies_list()
    assert obj.results == []


def test_strategies_list_carries_empty_warning_when_catalog_missing(monkeypatch):
    """Empty catalog must surface a warning so callers can distinguish
    'no bundled strategies yet' from 'endpoint broken'.

    Mirrors ``test_indicators_list_carries_empty_warning_when_widgets_missing``
    in test_routers_catalog.py.
    """
    import openbb_pine.routers.strategies_router as sr

    monkeypatch.setattr(sr, "_load_bundled_strategies", lambda: {})
    obj = sr.strategies_list()
    assert obj.warnings is not None
    assert len(obj.warnings) == 1
    w = obj.warnings[0]
    assert w.category == "PineStrategyCatalogEmpty"
    # The message must reference the widgets bead (#587) so an operator
    # reading the warning can trace when bundled strategies will land.
    assert "587" in w.message or "bundled" in w.message.lower()


def test_strategies_list_populated_from_catalog(monkeypatch):
    """When strategies.json is populated, each entry projects to a typed
    :class:`BundledStrategyEntry` and the empty-catalog warning drops.
    """
    import openbb_pine.routers.strategies_router as sr

    fake_strategy = {
        "name": "RSI Reversal",
        "description": "Long-only RSI reversal — buys oversold, sells overbought.",
        "category": "strategy",
        "strategy_type": "long_only",
        "initial_capital_default": 100_000.0,
        "pine_version": 6,
    }
    monkeypatch.setattr(
        sr,
        "_load_bundled_strategies",
        lambda: {"pine_rsi_reversal": fake_strategy},
    )
    obj = sr.strategies_list()
    assert len(obj.results) == 1
    entry = obj.results[0]
    assert isinstance(entry, BundledStrategyEntry)
    assert entry.name == "RSI Reversal"
    assert entry.pine_source_path == "inline:pine_rsi_reversal"
    assert entry.strategy_type == "long_only"
    assert entry.initial_capital_default == 100_000.0
    assert entry.pine_version == 6
    # No warning when populated.
    assert obj.warnings is None


def test_strategies_list_defaults_strategy_type_when_omitted(monkeypatch):
    """Catalog entries without ``strategy_type`` fall back to ``long_short``
    (the widest surface). Missing ``initial_capital_default`` defaults to
    the Pine engine default of 100_000.
    """
    import openbb_pine.routers.strategies_router as sr

    minimal = {
        "name": "Minimal",
        "description": "A strategy with only the required fields.",
    }
    monkeypatch.setattr(
        sr, "_load_bundled_strategies", lambda: {"pine_minimal": minimal}
    )
    obj = sr.strategies_list()
    entry = obj.results[0]
    assert entry.strategy_type == "long_short"
    assert entry.initial_capital_default == 100_000.0


# ---------------------------------------------------------------------------
# _load_bundled_strategies — same semantics as _load_bundled_widgets
# ---------------------------------------------------------------------------


def test_load_bundled_strategies_returns_empty_dict_when_file_missing(
    monkeypatch, tmp_path
):
    """No strategies.json on disk → ``{}`` (graceful scaffold-phase degrade)."""
    import openbb_pine as pkg

    monkeypatch.setattr(pkg, "_STRATEGIES_JSON", tmp_path / "does_not_exist.json")
    assert pkg._load_bundled_strategies() == {}


def test_load_bundled_strategies_parses_json_object(monkeypatch, tmp_path):
    """A JSON object at the top level round-trips through the loader unchanged."""
    import openbb_pine as pkg

    path = tmp_path / "strategies.json"
    path.write_text('{"foo": {"name": "Foo"}}', encoding="utf-8")
    monkeypatch.setattr(pkg, "_STRATEGIES_JSON", path)
    assert pkg._load_bundled_strategies() == {"foo": {"name": "Foo"}}


def test_load_bundled_strategies_raises_on_non_object_top_level(monkeypatch, tmp_path):
    """A malformed strategies.json (top-level array/string) must NOT silently
    yield ``{}`` — dropping the catalog would mask an incident. Same policy
    as :func:`_load_bundled_widgets`.
    """
    import pytest

    import openbb_pine as pkg

    path = tmp_path / "strategies.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setattr(pkg, "_STRATEGIES_JSON", path)
    with pytest.raises(ValueError, match="top-level type must be an object"):
        pkg._load_bundled_strategies()
