"""Confluence panel selector (bd-7ct.1, bd-d5i).

The ``PanelConfig`` frozen dataclass gates which indicator panel the
techtrade pipeline computes:

- ``panel="classic"`` (default) — the 14-key / 7-vote panel that ships
  today. Preserved byte-identically for all existing callers.
- ``panel="extended"`` — the wider panel that family PRs (bd-luy /
  bd-40v / bd-z43 / bd-alj) will populate with best-of-class industry-
  standard indicators, each gated on measured out-of-sample forward IC
  (bd-7ct.10 harness).

Design decision (design spec §11 OQ1 revised): enum selector, not
``bool``. A future ``"v3"`` panel composes; ``extended=True`` doesn't.
Frozen + slotted + hashable so instances can be safely shared as
module-scope sentinels (``PANEL_CLASSIC``, ``PANEL_EXTENDED``) and
used as dict keys in shadow-mode caches (bd-7ct.12).

Full context:
- Design spec: docs/superpowers/specs/2026-07-08-confluence-panel-expansion-design.md
- Implementation plan: docs/superpowers/plans/2026-07-08-bd-7ct-confluence-foundation.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Public type alias — external callers should reference this rather than
# duplicating the literal set.
Panel = Literal["classic", "extended"]

# Module-scope constant — the known-good set of panel values (R7.10). If
# a third panel is added in the future, extend this frozenset AND the
# ``Panel`` type alias above in the same commit.
_VALID_PANELS: frozenset[str] = frozenset({"classic", "extended"})


@dataclass(frozen=True, slots=True)
class PanelConfig:
    """Frozen selector for which confluence panel a build should use.

    Parameters
    ----------
    panel : {"classic", "extended"}
        Which panel to compute. Defaults to ``"classic"`` so any caller
        that omits the kwarg gets the pre-bd-7ct behavior byte-identically.

    Raises
    ------
    ValueError
        If ``panel`` is not one of the known values. This is a defensive
        check: ``Literal`` typing is a lint-time hint only, and callers
        who pass ``True`` (bool) or ``None`` at runtime would otherwise
        silently reach a downstream branch that fails opaquely. Reject
        at construction so the failure is loud and local.
    """

    panel: Panel = "classic"

    def __post_init__(self) -> None:
        # iter-1 pr-test M4: reject *any* non-string value up front so
        # unhashable types (list, dict) don't leak through `not in set`
        # with a confusing TypeError. Callers who pass True/False/0/1/
        # empty containers get a uniform ValueError with the offending
        # value in the message.
        if not isinstance(self.panel, str) or self.panel not in _VALID_PANELS:
            raise ValueError(
                f"unknown panel {self.panel!r}; expected one of {sorted(_VALID_PANELS)}"
            )


#: Sentinel for the classic (14-key / 7-vote) panel. The default kwarg
#: value everywhere ``PanelConfig`` is threaded through the engine.
PANEL_CLASSIC: PanelConfig = PanelConfig(panel="classic")

#: Sentinel for the extended panel. In bd-7ct this is a pass-through
#: stub (produces the same panel as classic); family PRs replace the
#: stub functions with real new indicators.
PANEL_EXTENDED: PanelConfig = PanelConfig(panel="extended")
