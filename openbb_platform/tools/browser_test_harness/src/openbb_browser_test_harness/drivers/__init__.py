"""Driver registry."""

from __future__ import annotations

from .base import Driver
from .standalone_driver import (
    BackendCrashedError,
    HarnessSetupError,
    StandaloneDriver,
)

# Workspace driver is playwright-optional; guard the import so the standalone
# path stays usable even without playwright installed.
try:
    from .workspace_driver import WorkspaceDriver, WorkspaceDriverError

    _WORKSPACE_AVAILABLE = True
except ImportError:  # pragma: no cover — trivial import guard
    _WORKSPACE_AVAILABLE = False
    WorkspaceDriver = None  # type: ignore[assignment,misc]
    WorkspaceDriverError = None  # type: ignore[assignment,misc]

__all__ = [
    "Driver",
    "StandaloneDriver",
    "HarnessSetupError",
    "BackendCrashedError",
    "WorkspaceDriver",
    "WorkspaceDriverError",
    "_WORKSPACE_AVAILABLE",
]
