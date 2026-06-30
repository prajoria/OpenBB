"""Smoke tests for the openbb-pine scaffold (PRD section 16.5)."""

from __future__ import annotations

import sys


def test_about_returns_obbject_with_expected_fields():
    """``about()`` must return an OBBject whose ``.results`` is a PineAbout."""
    from openbb_pine.about import about

    result = about()
    assert result.results.extension_name == "pine"
    assert "PyneSys" in result.results.powered_by
    assert result.results.providers_supported == ["fmp", "fmp_cached"]


def test_import_has_no_unexpected_side_effects_on_sys_modules():
    """Importing ``openbb_pine`` must not pull sibling extensions or heavy deps.

    PRD section 16.5 demands the import be self-contained. Sibling extensions
    (``openbb_backtest``, ``openbb_techtrade``, ``openbb_equity``, etc.) and
    heavy data-stack modules (``pandas``, ``numpy``) must not be transitively
    loaded by ``import openbb_pine``. The sys.path bridge is allowed to
    register the vendored ``pynecore`` location but must not import it.
    """
    # Remove the targets if a prior test already imported them so this test is
    # honest about openbb_pine's own behavior, not the test-runner's history.
    targets = (
        "openbb_pine",
        "openbb_backtest",
        "openbb_techtrade",
        "openbb_equity",
        "pynecore",  # only the sys.path insert is allowed, not an import
    )
    saved = {name: sys.modules.pop(name) for name in targets if name in sys.modules}
    # Also strip any submodules so the parent re-import is clean.
    for name in list(sys.modules):
        if any(name.startswith(f"{t}.") for t in targets):
            saved[name] = sys.modules.pop(name)

    try:
        import openbb_pine  # noqa: F401

        loaded = set(sys.modules)
        for sibling in (
            "openbb_backtest",
            "openbb_techtrade",
            "openbb_equity",
        ):
            assert sibling not in loaded, (
                f"openbb_pine import unexpectedly loaded sibling extension {sibling!r}"
            )
        assert "pynecore" not in loaded, (
            "openbb_pine import must not eagerly load pynecore (sys.path bridge only)"
        )
    finally:
        # Restore so other tests in the session see whatever was there before.
        for name, mod in saved.items():
            sys.modules.setdefault(name, mod)
