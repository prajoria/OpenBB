"""Catalog sub-router: ``GET /pine/indicators/list`` + ``GET /pine/builtins/coverage`` (D3 §4.4, §4.5).

Two read-only command endpoints over static state:

* ``/pine/indicators/list`` reports the bundled-indicator catalog. Wave 5B
  (P2 bead 0e9.5.53) ships the first entry — ``pine_bollinger_bands`` —
  loaded from :func:`openbb_pine._load_bundled_widgets`. When the catalog
  is empty (dev-mode with widgets.json removed) the response is an empty
  list plus a warning that says so.
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

from openbb_pine import _coverage_manifest, _load_bundled_widgets
from openbb_pine.routers._models import BundledIndicatorEntry, BuiltinsCoverage

router = Router(
    prefix="",
    description="Bundled-indicator catalog and Pine-builtins coverage manifest.",
)


# ---------------------------------------------------------------------------
# Module-level config seams (patched in unit tests)
# ---------------------------------------------------------------------------

# The universe of Pine versions the compiler ARCHITECTURE targets. The
# _supported_ list (currently empty) comes from the coverage manifest;
# this is the wider "could-eventually-support" set.
_PINE_VERSIONS_KNOWN: list[int] = [5, 6]


def _widgets_to_entries() -> list[BundledIndicatorEntry]:
    """Map the ``widgets.json`` catalog to typed :class:`BundledIndicatorEntry`.

    The widget spec is Workspace-shaped (name/description/category/type/
    endpoint/params/footer/openapi_ref). :class:`BundledIndicatorEntry` is
    catalog-shaped (name/pine_source_path/description/category/pine_version).
    We project one to the other; the ``pine_source_path`` is synthesised as
    ``"inline:<widgetId>"`` since Wave 5B bundles Pine sources verbatim in
    the widget's ``params.source`` rather than as separate .pine files.
    """
    entries: list[BundledIndicatorEntry] = []
    for widget_id, spec in _load_bundled_widgets().items():
        entries.append(
            BundledIndicatorEntry(
                name=spec.get("name", widget_id),
                pine_source_path=f"inline:{widget_id}",
                description=spec.get("description", ""),
                category=spec.get("category", "indicator"),
                pine_version=6,
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@router.command(methods=["GET"], path="/indicators/list")
def indicators_list() -> OBBject[list[BundledIndicatorEntry]]:
    """List the bundled Pine indicators shipped with the extension.

    Reads :func:`openbb_pine._load_bundled_widgets` (widgets.json). When the
    catalog is empty (e.g. widgets.json removed for a dev build), returns
    ``[]`` plus a PineCatalogEmpty warning so callers can distinguish
    "no bundled indicators" from "endpoint broken."

    Returns
    -------
    OBBject[list[BundledIndicatorEntry]]
        One entry per widgets.json top-level key.
    """
    entries = _widgets_to_entries()
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
def builtins_coverage() -> OBBject:
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
