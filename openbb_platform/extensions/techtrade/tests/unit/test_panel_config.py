"""Tests for engine/panel_config.py — the confluence panel selector.

Contract tests for the frozen versioned enum that gates the classic (14-key,
7-vote) panel vs the extended panel that family PRs (bd-luy/40v/z43/alj)
will populate. Full context: docs/superpowers/plans/2026-07-08-bd-7ct-
confluence-foundation.md Step 1 (bd-d5i).

Design decision (spec §11 OQ1 revised): enum selector NOT bool, so a
future v3 panel isn't a boolean explosion. `PanelConfig(panel="v3")`
composes; `extended=True` doesn't.
"""

from __future__ import annotations

import dataclasses

import pytest

from openbb_techtrade.engine.panel_config import (
    PANEL_CLASSIC,
    PANEL_EXTENDED,
    PanelConfig,
)


class TestPanelConfigInstantiation:
    """Frozen dataclass with validated `panel` field."""

    def test_default_is_classic(self):
        """Default construction picks the classic panel (backward compat)."""
        assert PanelConfig().panel == "classic"

    def test_explicit_classic(self):
        assert PanelConfig(panel="classic").panel == "classic"

    def test_explicit_extended(self):
        assert PanelConfig(panel="extended").panel == "extended"

    def test_unknown_panel_raises_value_error(self):
        """R7.4 seam contract: unknown values rejected at construction, not
        silently at some downstream branch."""
        with pytest.raises(ValueError, match="unknown panel"):
            PanelConfig(panel="v3")

    def test_bool_true_rejected(self):
        """A bool leaks through Literal typing at runtime; a defensive check
        prevents the exact 'oops passed True instead of a string' misuse
        the spec §11 OQ1 revision was designed to eliminate."""
        with pytest.raises(ValueError, match="unknown panel"):
            PanelConfig(panel=True)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "bad_value",
        [False, 0, 1, "", "v3", "CLASSIC", "extended ", [], (), {}, object()],
    )
    def test_various_bad_values_rejected(self, bad_value):
        """iter-1 pr-test M4: R7.4 breadth — the constructor must reject
        every non-literal-string-in-VALID_PANELS value at the seam.
        Includes False, integer variants, empty string, unknown string,
        wrong-case string, string-with-trailing-space, empty containers,
        arbitrary object. A single failing case here means the seam is
        leaky and a downstream comparison would silently misroute the
        dispatch."""
        with pytest.raises(ValueError, match="unknown panel"):
            PanelConfig(panel=bad_value)  # type: ignore[arg-type]

    def test_none_rejected(self):
        with pytest.raises(ValueError, match="unknown panel"):
            PanelConfig(panel=None)  # type: ignore[arg-type]


class TestPanelConfigImmutability:
    """Frozen dataclass — mutation raises."""

    def test_frozen_prevents_field_assignment(self):
        cfg = PanelConfig(panel="classic")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.panel = "extended"  # type: ignore[misc]

    def test_frozen_prevents_new_attribute(self):
        """A ``slots=True`` frozen dataclass raises ``TypeError`` (not
        ``FrozenInstanceError``) on unknown-attribute assignment because
        the object has no ``__dict__`` and slots reject the write before
        the frozen guard runs. Either exception type proves immutability;
        we accept both."""
        cfg = PanelConfig(panel="classic")
        with pytest.raises((dataclasses.FrozenInstanceError, TypeError, AttributeError)):
            cfg.extra = "nope"  # type: ignore[attr-defined]


class TestModuleScopeSentinels:
    """R7.10: the two known configurations are hoisted to module-scope
    named constants so downstream code references `PANEL_CLASSIC` and
    `PANEL_EXTENDED` instead of instantiating fresh objects everywhere
    (which would fragment the identity and defeat quick `is` checks)."""

    def test_panel_classic_is_a_panel_config(self):
        assert isinstance(PANEL_CLASSIC, PanelConfig)

    def test_panel_extended_is_a_panel_config(self):
        assert isinstance(PANEL_EXTENDED, PanelConfig)

    def test_panel_classic_selects_classic(self):
        assert PANEL_CLASSIC.panel == "classic"

    def test_panel_extended_selects_extended(self):
        assert PANEL_EXTENDED.panel == "extended"

    def test_panel_classic_and_extended_are_distinct(self):
        assert PANEL_CLASSIC != PANEL_EXTENDED


class TestPanelConfigEquality:
    """Frozen dataclasses are value-equal by default — verify the same
    configuration compares equal regardless of construction path."""

    def test_equal_configs_compare_equal(self):
        assert PanelConfig(panel="classic") == PanelConfig(panel="classic")

    def test_different_configs_compare_unequal(self):
        assert PanelConfig(panel="classic") != PanelConfig(panel="extended")

    def test_hashable(self):
        """Frozen slots dataclass should be hashable so PanelConfig instances
        can be used as dict keys / set members (useful for shadow-mode
        caches keyed by config)."""
        assert hash(PanelConfig(panel="classic")) == hash(PanelConfig(panel="classic"))
        assert {PANEL_CLASSIC, PANEL_EXTENDED, PanelConfig(panel="classic")} == {
            PANEL_CLASSIC,
            PANEL_EXTENDED,
        }
