"""``obb.pine.about()`` model and command implementation (PRD section 16.3).

Field-for-field map of the PRD section 16.3 example payload. Scaffold variant:
heavy ``doctor`` checks are not yet wired (P0-L0.3 / P1 work), so ``doctor_ok``
defaults to True and the compiler/runtime status reflects the scaffold state.
"""

from __future__ import annotations

import importlib.util
import json
import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from openbb_core.app.model.obbject import OBBject

from openbb_pine.attribution import POWERED_BY_FULL


def _detect_pynecore_version() -> str:
    """Best-effort PyneCore version detection.

    Prefer ``importlib.metadata.version("pynesys-pynecore")`` (works for both
    PyPI installs and the vendored editable install, when present). Falls back
    to a hardcoded label matching the submodule pin if metadata lookup fails.
    """
    try:
        return f"PyneCore {version('pynesys-pynecore')} (Apache-2.0)"
    except PackageNotFoundError:
        return "PyneCore 6.5.2 (Apache-2.0)"


def _detect_fmp_key_present() -> bool:
    """Best-effort FMP API key detection (env var OR user_settings.json)."""
    if os.environ.get("OPENBB_API_FMP_API_KEY"):
        return True
    settings_path = Path.home() / ".openbb_platform" / "user_settings.json"
    if not settings_path.is_file():
        return False
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    creds = (data.get("credentials") or {}) if isinstance(data, dict) else {}
    return bool(creds.get("fmp_api_key"))


class PineAbout(BaseModel):
    """Extension metadata returned by ``obb.pine.about()`` -- PRD section 16.3 contract."""

    extension_name: Literal["pine"] = "pine"
    extension_version: str = Field(description="Installed package version.")
    pine_version_supported: str = Field(
        description='e.g. "6 (and v5 via auto-migration)".'
    )
    runtime: str = Field(description='e.g. "PyneCore 6.5.2 (Apache-2.0)".')
    powered_by: str = Field(
        description="Section 2.6 surface #3 -- PyneSys section 4(d) attribution."
    )
    compiler_status: str = Field(
        description="Free-form status string -- locked to typed enum once compiler ships."
    )
    builtins_implemented: int = Field(ge=0)
    builtins_total: int = Field(ge=0)
    providers_supported: list[str] = Field(
        default_factory=lambda: ["fmp", "fmp_cached"],
        description="Locked to FMP / fmp_cached in v1.x (PRD section 13.8).",
    )
    fmp_key_present: bool
    fmp_cached_installed: bool
    compile_cache_dir: str
    doctor_ok: bool
    doctor_issues: list[str] = Field(default_factory=list)


def about() -> OBBject[PineAbout]:
    """Return pine extension metadata (PRD section 16.3)."""
    try:
        ext_version = version("openbb-extension-pine")
    except PackageNotFoundError:
        ext_version = "0.0.1"

    fmp_cached_installed = importlib.util.find_spec("openbb_fmp_cached") is not None
    compile_cache_dir = str(Path.home() / ".openbb" / "pine_cache")

    return OBBject(
        results=PineAbout(
            extension_name="pine",
            extension_version=ext_version,
            pine_version_supported="6 (and v5 via auto-migration)",
            runtime=_detect_pynecore_version(),
            powered_by=POWERED_BY_FULL,
            compiler_status=(
                "scaffolded -- compiler not yet implemented (Phase 1)"
            ),
            builtins_implemented=0,
            builtins_total=357,
            providers_supported=["fmp", "fmp_cached"],
            fmp_key_present=_detect_fmp_key_present(),
            fmp_cached_installed=fmp_cached_installed,
            compile_cache_dir=compile_cache_dir,
            doctor_ok=True,
            doctor_issues=[],
        )
    )
