"""Tests for :mod:`openbb_pine.routers.compile_router` (P1 — bead 0e9.5.52).

Pin the ``POST /pine/compile`` command's contract:

* Lex + parse via Wave-1A (tokenize) and Wave-2A (parse). On success
  return a :class:`PineCompileResponse` with a stub ``python_source``
  pointing at the codegen bead (C5, 0e9.5.5).
* Detect ``//@version=`` pragma; falls back to ``target_version`` arg.
* Malformed source raises :class:`PineSyntaxError` (which the platform
  middleware serializes via the §4.1 error envelope).
* ``builtins_used`` populated from C3 type-checker when importable;
  empty otherwise.
"""

from __future__ import annotations

import pytest

from openbb_core.app.model.obbject import OBBject

from openbb_pine import __version__ as _pine_version
from openbb_pine.errors import PineSyntaxError
from openbb_pine.routers._models import PineCompileResponse


# A minimum-viable Pine v6 source the parser accepts unedited. Trailing
# newline is required by the parser (NEWLINE is a statement terminator).
_TRIVIAL_V6 = "//@version=6\nindicator(\"BB\")\nx = 1\n"
_TRIVIAL_V5 = "//@version=5\nindicator(\"BB\")\nx = 1\n"
_NO_PRAGMA = "indicator(\"BB\")\nx = 1\n"


def test_compile_returns_obbject_with_typed_payload():
    from openbb_pine.routers.compile_router import compile as compile_fn

    obj = compile_fn(source=_TRIVIAL_V6)
    assert isinstance(obj, OBBject)
    assert isinstance(obj.results, PineCompileResponse)


def test_compile_python_source_is_stub_at_m1():
    """Codegen hasn't landed -> python_source is a stub message."""
    from openbb_pine.routers.compile_router import compile as compile_fn

    obj = compile_fn(source=_TRIVIAL_V6)
    assert "not yet implemented" in obj.results.python_source.lower() or \
        "C5" in obj.results.python_source


def test_compile_detects_v6_pragma():
    from openbb_pine.routers.compile_router import compile as compile_fn

    obj = compile_fn(source=_TRIVIAL_V6)
    assert obj.results.pine_version == 6


def test_compile_detects_v5_pragma():
    """v5 grammar is a v6 placeholder until C7 lands; lex+parse still work."""
    from openbb_pine.routers.compile_router import compile as compile_fn

    obj = compile_fn(source=_TRIVIAL_V5)
    assert obj.results.pine_version == 5


def test_compile_falls_back_to_target_version_when_no_pragma():
    from openbb_pine.routers.compile_router import compile as compile_fn

    obj = compile_fn(source=_NO_PRAGMA, target_version=6)
    assert obj.results.pine_version == 6


def test_compile_sha_is_deterministic_for_same_input():
    from openbb_pine.routers.compile_router import compile as compile_fn

    a = compile_fn(source=_TRIVIAL_V6)
    b = compile_fn(source=_TRIVIAL_V6)
    assert a.results.sha == b.results.sha


def test_compile_sha_differs_for_different_input():
    from openbb_pine.routers.compile_router import compile as compile_fn

    a = compile_fn(source=_TRIVIAL_V6)
    b = compile_fn(source=_TRIVIAL_V6.replace("x = 1", "y = 2"))
    assert a.results.sha != b.results.sha


def test_compile_carries_compiler_version():
    from openbb_pine.routers.compile_router import compile as compile_fn

    obj = compile_fn(source=_TRIVIAL_V6)
    assert obj.results.compiler_version == _pine_version


def test_compile_malformed_source_raises_pine_syntax_error():
    """The lexer barfs on stray characters -> PineSyntaxError."""
    from openbb_pine.routers.compile_router import compile as compile_fn

    with pytest.raises(PineSyntaxError):
        compile_fn(source="//@version=6\n@@@invalid@@@\n")


def test_compile_unparseable_source_raises_pine_syntax_error():
    """Parser-level failure -> PineSyntaxError with parse-error message."""
    from openbb_pine.routers.compile_router import compile as compile_fn

    with pytest.raises(PineSyntaxError):
        # Stray unclosed paren — lexes fine, parses with error.
        compile_fn(source="//@version=6\nindicator(\"BB\"\nx = 1\n")


def test_compile_builtins_used_empty_when_no_type_checker(monkeypatch):
    """C3 type checker not yet landed -> builtins_used = []."""
    import openbb_pine.routers.compile_router as cr

    # Force the import-or-skip helper to return empty by simulating ImportError.
    monkeypatch.setattr(
        cr, "_maybe_typecheck_builtins", lambda _program: []
    )
    from openbb_pine.routers.compile_router import compile as compile_fn

    obj = compile_fn(source=_TRIVIAL_V6)
    assert obj.results.builtins_used == []


def test_compile_warnings_empty_at_m1():
    """M1 surface returns no warnings (C7 migration shim lands later)."""
    from openbb_pine.routers.compile_router import compile as compile_fn

    obj = compile_fn(source=_TRIVIAL_V6)
    assert obj.results.warnings == []


def test_compile_target_version_param_overridden_by_pragma():
    """When //@version= is present, it wins over the explicit target_version."""
    from openbb_pine.routers.compile_router import compile as compile_fn

    obj = compile_fn(source=_TRIVIAL_V6, target_version=5)
    # Pragma says 6, so detected version is 6 despite target_version=5.
    assert obj.results.pine_version == 6


def test_compile_blake2b_sha_is_hex_string():
    """The cache key is a hex digest (blake2b_16 -> 32 hex chars)."""
    from openbb_pine.routers.compile_router import compile as compile_fn

    obj = compile_fn(source=_TRIVIAL_V6)
    assert isinstance(obj.results.sha, str)
    assert len(obj.results.sha) == 32  # blake2b digest_size=16 -> 32 hex
    int(obj.results.sha, 16)  # asserts hex-ness


def test_compile_typechecker_hook_calls_check_when_present(monkeypatch):
    """When C3 lands, ``builtins_used`` comes from the type-checker result."""
    import openbb_pine.routers.compile_router as cr

    class _FakeResult:
        builtins_used = frozenset({"ta.sma", "math.abs"})

    monkeypatch.setattr(
        cr, "_maybe_typecheck_builtins",
        lambda _program: sorted(_FakeResult.builtins_used),
    )
    obj = cr.compile(source=_TRIVIAL_V6)
    assert obj.results.builtins_used == ["math.abs", "ta.sma"]
