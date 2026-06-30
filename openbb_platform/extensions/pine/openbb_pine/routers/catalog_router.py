"""Catalog sub-router: ``GET /pine/indicators/list`` + ``GET /pine/builtins/coverage`` (D3 §4.4, §4.5).

Two read-only command endpoints over static state:

* ``/pine/indicators/list`` reports the bundled-indicator catalog. At M1
  the catalog is empty (Workspace widgets land with the P2 bead) — the
  response is an empty list plus a warning that says so.
* ``/pine/builtins/coverage`` exposes the
  :mod:`openbb_pine._coverage_manifest` frozensets so the coverage
  dashboard / CI metrics can read them as JSON.

Both endpoints return typed ``OBBject[Model]`` per D3 §5 — the schemas are
ours and consumers want stable keys.
"""

from __future__ import annotations

from openbb_core.app.model.abstract.warning import Warning_
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_pine import _coverage_manifest
from openbb_pine.routers._models import BundledIndicatorEntry, BuiltinsCoverage

router = Router(
    prefix="",
    description="Bundled-indicator catalog and Pine-builtins coverage manifest.",
)


# ---------------------------------------------------------------------------
# Module-level config seams (patched in unit tests)
# ---------------------------------------------------------------------------

# Until a bundled-indicator catalog ships (P2), this list is empty. Defined
# as a module-level constant rather than recomputed in the command body so
# tests can monkeypatch it to verify the encoding path without touching the
# manifest module.
_BUNDLED_INDICATORS: list[BundledIndicatorEntry] = []

# The universe of Pine versions the compiler ARCHITECTURE targets. The
# _supported_ list (currently empty) comes from the coverage manifest;
# this is the wider "could-eventually-support" set.
_PINE_VERSIONS_KNOWN: list[int] = [5, 6]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@router.command(methods=["GET"], path="/indicators/list")
def indicators_list() -> OBBject[list[BundledIndicatorEntry]]:
    """List the bundled Pine indicators shipped with the extension.

    At M1 there are no bundled indicators — Workspace widgets land with the
    P2 bead. The response is an empty list plus a warning so callers know
    the catalog is intentionally empty rather than missing due to error.

    Returns
    -------
    OBBject[list[BundledIndicatorEntry]]
        Empty list at M1; populated as the P2 widgets bead lands.
    """
    entries = list(_BUNDLED_INDICATORS)
    warnings: list[Warning_] = []
    if not entries:
        warnings.append(
            Warning_(
                category="PineCatalogEmpty",
                message=(
                    "no bundled indicators yet (Phase 1 in progress) — "
                    "bundled .pine sources land with the P2 widgets bead"
                ),
            )
        )
    return OBBject(results=entries, warnings=warnings or None)


@router.command(methods=["GET"], path="/builtins/coverage")
def builtins_coverage() -> OBBject[BuiltinsCoverage]:
    """Report which Pine builtins / grammar features / versions are implemented.

    Reads :mod:`openbb_pine._coverage_manifest` (the single source of
    truth). At Phase 0 every set is empty -> all counts are 0. Each PR
    that lands a builtin updates the manifest, automatically updating this
    endpoint's payload.

    Returns
    -------
    OBBject[BuiltinsCoverage]
        Sorted lists + counts pulled from the frozensets.
    """
    builtins_sorted = sorted(_coverage_manifest.BUILTINS_IMPLEMENTED)
    features_sorted = sorted(_coverage_manifest.FEATURES_IMPLEMENTED)
    versions_supported_sorted = sorted(_coverage_manifest.PINE_VERSIONS_SUPPORTED)

    payload = BuiltinsCoverage(
        pine_versions_supported=versions_supported_sorted,
        builtins_implemented_count=len(builtins_sorted),
        builtins_implemented=builtins_sorted,
        features_implemented=features_sorted,
        pine_versions_known=list(_PINE_VERSIONS_KNOWN),
    )
    return OBBject(results=payload)
