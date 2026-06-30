"""Health sub-router: ``GET /pine/health`` (D3 §4.6, attribution surface #3).

The §2.6 / §8.2 PyneCore attribution surface #3 — the JSON response field
``results.powered_by`` is the literal :data:`POWERED_BY_SHORT` (the SHORT
form is correct here because the field key already says "powered_by";
prose surfaces use the FULL form).

Health is operator-focused: ``status`` + key issues. ``obb.pine.about()``
is the informational counterpart (PRD §16.3 fields) — both share the same
``diagnostics.run_all_checks()`` backend so a deviation between the two is
a single-file fix.
"""

from __future__ import annotations

import importlib.util
from importlib.metadata import PackageNotFoundError, version

from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_pine import _coverage_manifest  # noqa: F401  - test-seam import
from openbb_pine.about import _detect_pynecore_version
from openbb_pine.attribution import POWERED_BY_SHORT
from openbb_pine.diagnostics import CheckResult, run_all_checks
from openbb_pine.routers._models import PineHealth

# Re-export so the 4-of-4 attribution test (`tests/unit/test_attribution_surfaces.py`)
# can find PineHealth via `from openbb_pine.routers import health_router;
# health_router.PineHealth`. The test instantiates the model with no args
# and asserts the powered_by default matches POWERED_BY_SHORT — a
# regression here is loud-failure, not silent skip.
__all__ = ["router", "PineHealth", "POWERED_BY_SHORT"]


router = Router(
    prefix="",
    description=(
        "Liveness + readiness probe for the Pine extension. Powers the "
        "§2.6 attribution surface #3 (PyneCore Apache-2.0 §4(d) credit)."
    ),
)


def _derive_status(
    results: list[CheckResult],
) -> tuple[str, bool, list[str]]:
    """Roll diagnostic results into ``(status, doctor_ok, doctor_issues)``.

    * Any FAIL -> ``"unhealthy"``, ``doctor_ok=False``, issues lists failing names.
    * Any WARN (but no FAIL) -> ``"degraded"``, ``doctor_ok=True``, issues=[].
      We treat WARN as "still operationally OK" — the doctor CLI uses the
      same convention (warns don't change the exit code).
    * Otherwise -> ``"ok"``, ``doctor_ok=True``, issues=[].
    """
    issues = [r.name for r in results if r.status == "fail"]
    if issues:
        return "unhealthy", False, issues
    if any(r.status == "warn" for r in results):
        return "degraded", True, []
    return "ok", True, []


@router.command(methods=["GET"])
def health() -> OBBject[PineHealth]:
    """Report extension health for ops dashboards / load-balancer probes.

    The response carries the §2.6 attribution surface #3 string verbatim
    (:data:`openbb_pine.attribution.POWERED_BY_SHORT`). The 4-of-4
    attribution CI test (``tests/unit/test_attribution_surfaces.py``) tightens
    automatically once this route is importable — surface #3 flips from
    "skipped silently" to "checked for drift".

    Returns
    -------
    OBBject[PineHealth]
        Typed payload — see :class:`PineHealth`.
    """
    try:
        ext_version = version("openbb-extension-pine")
    except PackageNotFoundError:
        ext_version = "0.0.1"

    fmp_cached_installed = importlib.util.find_spec("openbb_fmp_cached") is not None

    results: list[CheckResult] = run_all_checks(allow_byo_only=False)
    status, doctor_ok, doctor_issues = _derive_status(results)

    by_name = {r.name: r for r in results}
    fmp_key_check = by_name.get("FMP API key present")
    fmp_key_present = fmp_key_check is not None and fmp_key_check.status == "ok"

    payload = PineHealth(
        status=status,  # type: ignore[arg-type]
        extension_version=ext_version,
        pine_version_supported="6 (and v5 via auto-migration once C7 lands)",
        compiler_status=(
            "scaffolded -- compiler not yet implemented (Phase 1 in flight)"
        ),
        runtime=_detect_pynecore_version(),
        powered_by=POWERED_BY_SHORT,  # §2.6 surface #3 — SHORT form
        doctor_ok=doctor_ok,
        doctor_issues=doctor_issues,
        fmp_key_present=fmp_key_present,
        fmp_cached_installed=fmp_cached_installed,
    )
    return OBBject(results=payload)
