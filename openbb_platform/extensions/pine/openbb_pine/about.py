"""``obb.pine.about()`` model and command implementation (PRD §16.3, D3 §3 + §11).

Field-for-field map of the PRD §16.3 example payload. Every field sources
from real state:

* ``extension_version`` — ``importlib.metadata.version("openbb-extension-pine")``
* ``runtime``           — PyneCore pinned_version from L0.3 license manifest
* ``builtins_implemented`` — ``len(_coverage_manifest.BUILTINS_IMPLEMENTED)``
* ``fmp_key_present`` / ``fmp_cached_installed`` — shared ``diagnostics``
                          checks (single source of truth, also consumed by
                          the ``openbb-pine doctor`` CLI per D3 §10.6)
* ``doctor_ok`` / ``doctor_issues`` — derived from ``run_all_checks()``

P5 (bead 0e9.5.56) replaces the L0.2 hardcoded placeholders.
"""

from __future__ import annotations

import importlib.util
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from openbb_core.app.model.obbject import OBBject

from openbb_pine import _coverage_manifest
from openbb_pine.attribution import POWERED_BY_FULL
from pyne_compiler.errors.diagnostics import (
    USER_SETTINGS_PATH,  # noqa: F401 - re-exported for monkeypatch convenience
    CheckResult,
    run_all_checks,
)

# ----------------------------------------------------------------------
# Module-level constants (test seams)
# ----------------------------------------------------------------------

# Path: openbb_pine/about.py -> parents[0]=openbb_pine, [1]=pine,
# [2]=extensions, [3]=openbb_platform, [4]=repo root.
LICENSE_MANIFEST_PATH: Path = (
    Path(__file__).resolve().parents[4]
    / "third_party"
    / "pynecore.license_manifest.json"
)
"""Where ``runtime`` sources the PyneCore version from (created by L0.3)."""

PYNECORE_VERSION_FALLBACK: str = "6.5.2"
"""Used when the L0.3 manifest is absent — matches the current pin."""

# Placeholder until the Pine v6 reference corpus is fully indexed and the
# total can be derived. Tracked separately from BUILTINS_IMPLEMENTED so the
# numerator can climb monotonically without changing this denominator.
BUILTINS_TOTAL_PLACEHOLDER: int = 357


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _detect_pynecore_version() -> str:
    """Source the PyneCore version from the L0.3 license manifest, with fallback.

    The L0.3 manifest at ``third_party/pynecore.license_manifest.json`` carries
    the authoritative ``pinned_version`` (also reviewed by the license-SHA CI
    on every submodule bump). If the manifest is missing or unreadable, fall
    back to the documented v6.5.2 pin.
    """
    pinned = PYNECORE_VERSION_FALLBACK
    try:
        if LICENSE_MANIFEST_PATH.is_file():
            data = json.loads(LICENSE_MANIFEST_PATH.read_text(encoding="utf-8"))
            v = data.get("pinned_version")
            if isinstance(v, str) and v:
                pinned = v
    except (OSError, ValueError):
        pass
    return f"PyneCore {pinned} (Apache-2.0)"


# ----------------------------------------------------------------------
# Pydantic model
# ----------------------------------------------------------------------


class PineAbout(BaseModel):
    """Extension metadata returned by ``obb.pine.about()`` -- PRD §16.3 contract."""

    extension_name: Literal["pine"] = "pine"
    extension_version: str = Field(description="Installed package version.")
    pine_version_supported: str = Field(
        description='e.g. "6 (and v5 via auto-migration once C7 lands)".'
    )
    runtime: str = Field(description='e.g. "PyneCore 6.5.2 (Apache-2.0)".')
    powered_by: str = Field(
        description="§2.6 surface #3 -- PyneSys §4(d) attribution."
    )
    compiler_status: str = Field(
        description="Free-form status string -- locked to typed enum once compiler ships."
    )
    builtins_implemented: int = Field(ge=0)
    builtins_total: int = Field(ge=0)
    providers_supported: list[str] = Field(
        default_factory=lambda: ["fmp", "fmp_cached"],
        description="Locked to FMP / fmp_cached in v1.x (PRD §13.8).",
    )
    fmp_key_present: bool
    fmp_cached_installed: bool
    compile_cache_dir: str
    doctor_ok: bool
    doctor_issues: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------
# Command
# ----------------------------------------------------------------------


def about() -> OBBject:
    """Return pine extension metadata (PRD §16.3).

    Every field is sourced from real state via the shared ``diagnostics``
    module — same backend as ``openbb-pine doctor``. ``doctor_issues``
    contains the *names* of failing checks (status == "fail"), matching the
    one-line-fix promise of PRD §16.3.

    Return type note: **bare `OBBject`** (not `OBBject[PineAbout]`) —
    matches the techtrade extension's `about()` convention. The static
    package builder generates a facade that would need to import
    `PineAbout` from us to parametrize the annotation, and the auto-gen
    tooling doesn't wire that import through; a typed return therefore
    breaks `obb.pine.about()` at package-load time with a NameError.
    Caught by real-world smoke bead 0e9.5.63; documented in D3 §5 as an
    exception to the general "typed for stable-key returns" rule.
    """
    try:
        ext_version = version("openbb-extension-pine")
    except PackageNotFoundError:
        ext_version = "0.0.1"

    fmp_cached_installed = importlib.util.find_spec("openbb_fmp_cached") is not None
    compile_cache_dir = str(Path.home() / ".openbb" / "pine_cache")

    # Run the shared diagnostic pass once; cherry-pick what we need for
    # the payload (the CLI consumes the same list directly).
    results: list[CheckResult] = run_all_checks(allow_byo_only=False)
    by_name = {r.name: r for r in results}
    doctor_issues = [r.name for r in results if r.status == "fail"]
    doctor_ok = len(doctor_issues) == 0

    # fmp_key_present is the OK-or-WARN status of the named check (WARN under
    # BYO-only also counts as "we have what we need"). Here BYO-only is False
    # so OK is the only positive — but coded defensively for the WARN branch.
    fmp_key_check = by_name.get("FMP API key present")
    fmp_key_present = fmp_key_check is not None and fmp_key_check.status == "ok"

    return OBBject(
        results=PineAbout(
            extension_name="pine",
            extension_version=ext_version,
            pine_version_supported="6 (and v5 via auto-migration once C7 lands)",
            runtime=_detect_pynecore_version(),
            powered_by=POWERED_BY_FULL,
            compiler_status=(
                "scaffolded -- compiler not yet implemented (Phase 1 in flight)"
            ),
            builtins_implemented=len(_coverage_manifest.BUILTINS_IMPLEMENTED),
            builtins_total=BUILTINS_TOTAL_PLACEHOLDER,
            providers_supported=["fmp", "fmp_cached"],
            fmp_key_present=fmp_key_present,
            fmp_cached_installed=fmp_cached_installed,
            compile_cache_dir=compile_cache_dir,
            doctor_ok=doctor_ok,
            doctor_issues=doctor_issues,
        )
    )
