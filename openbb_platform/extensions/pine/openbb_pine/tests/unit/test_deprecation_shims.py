"""Verify §13.5 deprecation shims fire ``DeprecationWarning`` on import
or attribute access, and preserve identity with the real pyne_compiler
modules (bd-ijq / E3.5, updated bd-579 for sys.modules alias shims).

Post-bd-579, shims are ``sys.modules[__name__] = <real>`` alias shims
rather than PEP 562 ``__getattr__`` shims. The behavioral contract is:
(1) importing the shim path emits a ``DeprecationWarning``; (2) the
shim path resolves to the same module object as the real path; (3)
public attributes on the shim ``is`` the same object as on the real
module.
"""
from __future__ import annotations

import importlib
import sys
import warnings

import pytest

SHIMS = [
    ("openbb_pine.compiler", "pyne_compiler.compiler"),
    ("openbb_pine.compiler.builtin_signatures",
     "pyne_compiler.compiler.builtin_signatures"),
    ("openbb_pine.compiler.codegen", "pyne_compiler.compiler.codegen"),
    ("openbb_pine.compiler.compile_cache",
     "pyne_compiler.compiler.compile_cache"),
    ("openbb_pine.compiler.ir", "pyne_compiler.compiler.ir"),
    ("openbb_pine.compiler.lexer", "pyne_compiler.compiler.lexer"),
    ("openbb_pine.compiler.parser", "pyne_compiler.compiler.parser"),
    ("openbb_pine.compiler.type_checker",
     "pyne_compiler.compiler.type_checker"),
    ("openbb_pine.compiler.types", "pyne_compiler.compiler.types"),
    ("openbb_pine.compiler.v5_migration",
     "pyne_compiler.compiler.v5_migration"),
    ("openbb_pine.compiler_errors", "pyne_compiler.errors.base"),
    ("openbb_pine.error_codes", "pyne_compiler.errors.codes"),
    ("openbb_pine.diagnostics", "pyne_compiler.errors.diagnostics"),
    ("openbb_pine.telemetry", "pyne_compiler.telemetry"),
]


def _pick_public_attr(mod):
    """Return the name of a public attribute on ``mod`` for identity check.

    Prefers ``__all__`` when present so re-export shims that intentionally
    expose a subset of the real module (e.g. the ``openbb_pine.compiler``
    package shim) don't trip on stdlib symbol bleed like ``Any``.
    """
    exported = list(getattr(mod, "__all__", ()))
    if exported:
        return exported[0]
    for name in dir(mod):
        if name.startswith("_"):
            continue
        # Skip re-exported stdlib helpers that may not be identical across
        # imports (e.g. ``annotations`` from ``__future__``, ``Any`` from typing).
        if name in {"annotations", "Any", "TYPE_CHECKING"}:
            continue
        return name
    raise AssertionError(f"no public attribute on {mod!r}")


@pytest.mark.parametrize("shim_name,real_name", SHIMS,
                         ids=[s[0] for s in SHIMS])
def test_shim_fires_deprecation_warning(shim_name, real_name):
    """Importing (or re-importing) the shim emits DeprecationWarning + is-identical.

    With ``sys.modules`` alias shims (post-bd-579), the warning fires
    at shim-module load time, not per attribute access. This test
    forces a fresh load by evicting the shim from ``sys.modules`` and
    re-importing it inside a ``catch_warnings`` block, then asserts the
    warning was emitted and identity is preserved for a public attribute.
    """
    # Ensure a clean load — the shim may already be cached from a prior
    # import (e.g. openbb_pine.__init__ or a sibling test).
    sys.modules.pop(shim_name, None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        shim = importlib.import_module(shim_name)
        real = importlib.import_module(real_name)
        attr_name = _pick_public_attr(real)
        obj = getattr(shim, attr_name)

    assert obj is getattr(real, attr_name), (
        f"identity broken: {shim_name}.{attr_name} is not "
        f"{real_name}.{attr_name}"
    )
    matches = [
        w for w in caught
        if issubclass(w.category, DeprecationWarning)
        and shim_name in str(w.message)
    ]
    assert matches, (
        f"expected DeprecationWarning mentioning {shim_name!r}; "
        f"got {[str(w.message) for w in caught]}"
    )


@pytest.mark.parametrize("shim_name,real_name", SHIMS,
                         ids=[s[0] for s in SHIMS])
def test_shim_dir_includes_real_module_attrs(shim_name, real_name):
    """``dir(shim)`` at minimum exposes the real module's public names.

    With alias shims, ``shim is real`` after import — ``dir(shim)``
    returns the same list as ``dir(real)``. With the package-level
    shim (``openbb_pine.compiler`` -> ``pyne_compiler.compiler``), the
    re-export __init__ is intentionally not a full alias (aliasing a
    package confuses importlib's leaf-module resolution — see bd-579
    subagent report). Use a subset check with the intended re-exports.
    """
    shim = importlib.import_module(shim_name)
    real = importlib.import_module(real_name)
    # For package-level compiler shim: assert the __all__ symbols the
    # shim explicitly re-exports are present, not that dir() is a
    # superset of the entire real module (which includes private
    # submodules not intended for shim consumption).
    if shim_name == "openbb_pine.compiler":
        expected = set(getattr(shim, "__all__", []))
        assert expected, f"{shim_name} must declare __all__ for re-export"
        shim_dir = set(dir(shim))
        missing = expected - shim_dir
        assert not missing, f"{shim_name} dir() missing __all__ entries: {sorted(missing)}"
        return
    # For leaf-module alias shims: shim is real, so dir agreement is trivial
    real_public = {n for n in dir(real) if not n.startswith("_")}
    shim_dir = set(dir(shim))
    missing = real_public - shim_dir
    assert not missing, f"{shim_name} dir() missing: {sorted(missing)}"


def test_shim_unknown_attr_raises_attribute_error():
    """Unknown attributes raise ``AttributeError`` — not a bare warning."""
    from openbb_pine.compiler import lexer as shim  # noqa: PLC0415
    with pytest.raises(AttributeError):
        shim.NoSuchAttribute  # noqa: B018
