"""Regression tests for #1788 - portfolio_intel routes must expose concrete
``response_model`` objects, never unresolved forward-ref strings.

Root cause (#1788): the ``openbb_core`` ``Router.command`` decorator reads the
*raw* ``func.__annotations__["return"]`` and uses it directly as the FastAPI
``response_model`` (see ``openbb_core/app/router.py``). When a router module
declares ``from __future__ import annotations`` every annotation becomes a
string, so ``-> OBBject`` is stored as the literal ``"OBBject"``. At
``app.openapi()`` schema-generation time pydantic then fails with
``PydanticUserError: TypeAdapter[... ForwardRef('OBBject') ...] is not fully
defined`` and the entire platform OpenAPI (hence every ``openbb-api`` launch,
including the portfolio Workspace backend) crashes.

These tests fail on the pre-fix code (string ``response_model``) and pass once
the offending ``from __future__ import annotations`` imports are removed so the
annotation is the real ``OBBject`` class / ``OBBject[Result]`` generic alias.
"""

from fastapi import FastAPI
from openbb_portfolio_intel.portfolio_intel_router import router as pi_router


def test_no_route_has_string_response_model():
    """No portfolio_intel route may carry a string/forward-ref response_model.

    A ``str`` response_model is the exact #1788 defect: the annotation was
    captured as text (``"OBBject"`` / ``"OBBject[...]"``) instead of the real
    type, so pydantic cannot build a schema for it.
    """
    offenders = [
        (getattr(route, "path", "?"), route.response_model)
        for route in pi_router.api_router.routes
        if isinstance(getattr(route, "response_model", None), str)
    ]
    assert not offenders, (
        "portfolio_intel routes expose string (unresolved forward-ref) "
        f"response_model - see #1788: {offenders}"
    )


def test_portfolio_intel_openapi_schema_builds():
    """A FastAPI app built from the portfolio_intel router must emit OpenAPI.

    This drives the real failing code path from #1788: ``app.openapi()`` walks
    every route's ``response_model`` and builds a pydantic schema. Any
    unresolved ``ForwardRef('OBBject')`` raises ``PydanticUserError`` here.
    """
    app = FastAPI(title="portfolio_intel openapi regression")
    app.include_router(pi_router.api_router)

    schema = app.openapi()

    assert isinstance(schema, dict)
    assert "paths" in schema and schema["paths"], "no paths in generated schema"
