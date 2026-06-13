"""``obb.backtest.*`` sub-router package (component 09).

The top-level :data:`openbb_backtest.backtest_router.router` lazily attaches the
sub-routers defined here as each is implemented:

- ``run_router``    — ``run`` / ``sweep`` / ``reconcile`` (component 09.2),
- ``factor_router`` — ``pipeline`` / ``factor_eval`` (component 09.3),
- ``validate_router`` — ``validate`` / ``tearsheet`` (component 09.4),
- ``bundle_router`` — nested ``bundle.ingest`` / ``bundle.list`` (component 09.5).

This package intentionally performs **no** imports at load time: the parent
router imports each sub-module under a guarded ``try/except ImportError`` so the
extension keeps importing cleanly while sub-routers are still being built, and so
heavy optional dependencies stay out of ``import openbb`` time.

See ``docs/designs/backtest-design/09-api-surface.md``.
"""

from __future__ import annotations

__all__: list[str] = []
