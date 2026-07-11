"""Verify §13.5 deprecation shims fire ``DeprecationWarning`` on attribute
access and preserve identity with the real pyne_compiler modules (bd-ijq /
E3.5).

Every shim is a PEP 562 module with a module-level ``__getattr__`` that
emits a :class:`DeprecationWarning` and returns the attribute from the
real module.  The `is` check confirms that isinstance / pytest.raises
against the shim path still recognises the extracted class.
"""
from __future__ import annotations

import importlib
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
    """Return the name of a public attribute on ``mod`` for identity check."""
    for name in dir(mod):
        if name.startswith("_"):
            continue
        # Skip re-exported stdlib helpers that may not be identical across
        # imports (e.g. ``annotations`` from ``__future__``).
        if name in {"annotations"}:
            continue
        return name
    raise AssertionError(f"no public attribute on {mod!r}")


@pytest.mark.parametrize("shim_name,real_name", SHIMS,
                         ids=[s[0] for s in SHIMS])
def test_shim_fires_deprecation_warning(shim_name, real_name):
    """Attribute access on the shim emits DeprecationWarning + is-identical."""
    shim = importlib.import_module(shim_name)
    real = importlib.import_module(real_name)
    attr_name = _pick_public_attr(real)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
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
    """``dir(shim)`` at minimum exposes the real module's public names."""
    shim = importlib.import_module(shim_name)
    real = importlib.import_module(real_name)
    real_public = {n for n in dir(real) if not n.startswith("_")}
    shim_dir = set(dir(shim))
    missing = real_public - shim_dir
    assert not missing, f"{shim_name} dir() missing: {sorted(missing)}"


def test_shim_unknown_attr_raises_attribute_error():
    """Unknown attributes raise ``AttributeError`` — not a bare warning."""
    from openbb_pine.compiler import lexer as shim  # noqa: PLC0415
    with pytest.raises(AttributeError):
        shim.NoSuchAttribute  # noqa: B018
