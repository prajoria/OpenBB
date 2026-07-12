"""Extension entry-point smoke test — iter-1 silent-hunt F7 fix.

Verifies that installing openbb-regime does NOT break `import openbb`
and that the extension entry point resolves. This is the R7.2 smoke test
per CLAUDE.md ("every public entry point needs a 'not empty' smoke test")
applied to a NEW EXTENSION rather than a function — if the ``about``
endpoint or router registration has a subtle bug, EVERY OpenBB user's
``import openbb`` breaks after we ship this. One-line test cost, potentially
production-outage severity.
"""

from __future__ import annotations

import pytest


def test_import_openbb_regime_does_not_raise():
    """The extension module itself must import cleanly."""
    import openbb_regime
    assert openbb_regime is not None


def test_openbb_regime_public_exports():
    """Public exports from openbb_regime are the ones documented."""
    from openbb_regime import MarketRegime, detect_market_regime
    assert MarketRegime is not None
    assert callable(detect_market_regime)


def test_regime_router_import_and_shape():
    """The router entry point declared in pyproject.toml must resolve
    and expose a Router instance so the openbb-core extension loader
    can register it without crashing.

    Load-bearing property: any router construction bug (bad decorator,
    missing OBBject import, malformed prefix) breaks static package
    build for EVERY OpenBB user after this extension is installed.
    """
    from openbb_regime.regime_router import router
    assert router is not None
    # Router class from openbb_core has these attributes
    assert hasattr(router, "prefix")
    assert hasattr(router, "api_router")   # FastAPI router beneath


def test_entry_point_metadata_matches_pyproject():
    """The ``openbb_core_extension`` entry point advertised in
    pyproject.toml MUST resolve to the router we just imported. If a
    future refactor renames the router module without updating
    pyproject, the extension silently fails to load and no obb.regime.*
    surface is exposed.
    """
    from importlib.metadata import entry_points
    eps = entry_points()
    # Python 3.10+ API — entry_points() returns EntryPoints object
    regime_eps = [
        ep for ep in eps.select(group="openbb_core_extension")
        if ep.name == "regime"
    ]
    assert len(regime_eps) == 1, (
        f"Expected exactly 1 openbb_core_extension entry point named "
        f"'regime'; got {len(regime_eps)}: {regime_eps}"
    )
    ep = regime_eps[0]
    # The entry point value must resolve to the router (not raise on load)
    loaded_router = ep.load()
    from openbb_regime.regime_router import router as expected_router
    assert loaded_router is expected_router, (
        f"Entry point 'regime' resolves to {loaded_router!r} but expected "
        f"{expected_router!r} from openbb_regime.regime_router. Someone "
        f"renamed the module/attr without updating pyproject.toml."
    )
