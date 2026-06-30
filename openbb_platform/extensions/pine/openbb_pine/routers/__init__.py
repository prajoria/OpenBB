"""HTTP / Python-API thin layer for ``openbb-pine`` (D3 §3 + §4).

This package houses the five sub-routers attached lazily by
:func:`openbb_pine.pine_router._include_subrouters`. Each module exports a
``router`` symbol (an ``openbb_core.app.router.Router`` instance) decorated
with the M1 endpoints listed in D3 §1.2.

No eager imports — heavy modules (compiler, runtime, pandas) only land on
first command call so ``import openbb_pine`` stays under the PRD §16.5
200 ms budget.
"""
