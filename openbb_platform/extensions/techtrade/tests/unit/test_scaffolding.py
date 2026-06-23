"""Unit tests for techtrade scaffolding: package + router imports, command surface."""

from __future__ import annotations


def test_package_imports():
    import openbb_techtrade

    assert openbb_techtrade.__version__


def test_core_modules_import():
    # Leaf modules must import without heavy/optional dependencies.
    import openbb_techtrade.helpers  # noqa: F401
    import openbb_techtrade.models  # noqa: F401


def test_subpackages_import():
    import openbb_techtrade.engine  # noqa: F401
    import openbb_techtrade.reporting  # noqa: F401
    import openbb_techtrade.strategies  # noqa: F401
    import openbb_techtrade.validation  # noqa: F401


def test_router_exposes_about():
    from openbb_techtrade.techtrade_router import router

    # Verified Router API in this checkout: commands are FastAPI routes on
    # `router.api_router.routes`, each with a `.path` like "/about".
    paths = {getattr(route, "path", None) for route in router.api_router.routes}
    assert "/about" in paths


def test_static_package_imports_model_typed_command_params():
    """Generated static package must import every model used as a command-parameter type.

    Regression for the #77 ``orders(plan: TradePlan)`` command: under
    ``from __future__ import annotations`` the parameter annotation stringizes to
    ``"TradePlan"``, which the package builder renders into the generated signature but
    -- lacking a ``__module__`` on a bare string -- never emits an import for, so
    ``import openbb.package.techtrade`` raises ``NameError: name 'TradePlan' is not
    defined``. The fix is to keep ``plan_router`` free of future-annotations (matching
    ``quantitative_router``'s ``data: list[Data]`` convention) so the annotation resolves
    to the real class and its import is generated.
    """
    from openbb_core.app.static.package_builder import ImportDefinition

    code = ImportDefinition.build("/techtrade")
    assert "TradePlan" in code
