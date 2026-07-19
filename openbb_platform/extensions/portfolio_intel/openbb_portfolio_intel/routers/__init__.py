"""Sub-router package for the portfolio_intel extension.

Each sub-router file (``xray_router.py``, ``events_router.py``, ...) exposes
a ``router`` attribute that ``portfolio_intel_router._include_subrouters()``
picks up and mounts under the parent router. The parent's guard swallows
``ModuleNotFoundError`` for still-unimplemented sub-routers so the extension
imports cleanly during scaffolding (see #802 for the guard invariant).
"""
