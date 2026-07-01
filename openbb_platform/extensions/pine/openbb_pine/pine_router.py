"""Top-level pine router.

Assembles the public ``obb.pine.*`` surface. Sub-routers (compile, run,
strategies, catalog, health) are attached lazily inside
:func:`_include_subrouters` so a missing optional sub-router is skipped at
import -- the extension keeps importing cleanly during incremental development.
At scaffold time **none** of the sub-routers exist; this module is intentionally
written so the lazy include silently skips each missing module.

The ``about`` command returns ``OBBject[PineAbout]`` (typed model) so the
section 2.6 attribution surface is part of the schema and the static package
builder gets a concrete return annotation. The bare-``OBBject`` convention
(techtrade style) is used only for free-form returns where the schema would
otherwise have to be ``OBBject[dict]``.

See ``docs/designs/openbb-pine/D3-platform-integration.md``, PRD sections 4.2
and 4.3.
"""

from __future__ import annotations

from importlib import import_module

from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_pine.about import PineAbout, about as _about_impl

router = Router(
    prefix="",
    description=(
        "Pine Script compatibility -- compile and run Pine v5/v6 indicators "
        "and strategies through the OpenBB Platform."
    ),
)


def _include_subrouters() -> None:
    """Lazily attach sub-routers as their components are implemented.

    Each entry is attempted once its module exists; missing optional
    sub-routers are skipped so the extension imports cleanly during
    incremental development. At scaffold time **every** target raises
    ImportError and is skipped silently -- which is the desired behavior.
    """
    for module_path, attr in (
        ("openbb_pine.routers.compile_router", "router"),
        ("openbb_pine.routers.run_router", "router"),
        ("openbb_pine.routers.strategies_router", "router"),
        ("openbb_pine.routers.catalog_router", "router"),
        ("openbb_pine.routers.health_router", "router"),
    ):
        try:
            module = import_module(module_path)
        except ImportError:
            continue
        router.include_router(getattr(module, attr))


_include_subrouters()


@router.command(methods=["GET"])
def about() -> OBBject:
    """Return pine extension metadata (PRD section 16.3).

    Bare ``OBBject`` (not ``OBBject[PineAbout]``) — the static package
    builder generates ``openbb.package.pine`` from this annotation and
    would need to import ``PineAbout`` from us to parametrize the
    typed variant; the auto-gen tooling doesn't wire that import through,
    so ``obb.pine.about()`` breaks at package-load time with ``NameError:
    name 'PineAbout' is not defined``. Caught by real-world smoke bead
    0e9.5.63 (smoke test STEP 2). See ``about.py::about()`` note for
    the mirror decision at the implementation site.
    """
    return _about_impl()
