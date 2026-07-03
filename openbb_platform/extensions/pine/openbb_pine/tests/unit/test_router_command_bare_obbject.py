"""Regression guard for PRD section 16.6: no typed generics in @router.command
return annotations.

Background
----------
The OpenBB static package builder walks ``@router.command`` return type
annotations to synthesise ``openbb.package.<extension>`` facades. It does
not chase transitive imports — if a decorated function returns
``OBBject[SomeModel]`` and ``SomeModel`` is defined in this extension, the
generated facade will reference ``SomeModel`` without importing it,
raising ``NameError: name 'SomeModel' is not defined`` when
``obb.<extension>.<method>()`` is called.

PRD section 16.6 codifies the workaround: every ``@router.command`` return
annotation must be **bare ``OBBject``** (not ``OBBject[T]``). The runtime
payload shape is unchanged — the annotation is documentation-only for the
facade, and the actual ``.results`` value carries the real type. Real
users hit the untyped facade path; the typed shape is available via the
direct-import path (``from openbb_pine.routers.foo import foo``).

Historical failures
-------------------
This invariant leaked twice, both caught by smoke tests rather than by
unit tests:

- Bead #0e9.5.63 — ``obb.pine.about()`` raised ``NameError: PineAbout``
  because ``pine_router.about() -> OBBject[PineAbout]``. Fixed in commit
  ``ecee35428``.
- (This guard's motivation) — ``obb.pine.indicators.list()`` raised
  ``NameError: BundledIndicatorEntry`` because
  ``catalog_router.indicators_list() -> OBBject[list[BundledIndicatorEntry]]``.
  Missed by the ``6e1ff5dc3`` audit sweep. Fixed alongside this test.

This unit-level guard trips as soon as anyone re-introduces a typed
generic, without needing a full ``openbb.build()`` cycle to notice.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

EXT_ROOT = pathlib.Path(__file__).resolve().parents[3]  # openbb_pine/
ROUTER_FILES = sorted(EXT_ROOT.rglob("routers/*_router.py")) + [
    EXT_ROOT / "pine_router.py",
]


def _decorated_with_router_command(node: ast.FunctionDef) -> bool:
    """True if ``node`` carries an ``@router.command(...)`` decorator.

    Matches both ``@router.command`` (bare) and ``@router.command(...)``
    (called). Any other decorator on the function is irrelevant to the
    facade generator.
    """
    for deco in node.decorator_list:
        # @router.command(...)  -> deco is Call(func=Attribute(value=Name('router'), attr='command'))
        # @router.command       -> deco is Attribute(value=Name('router'), attr='command')
        target = deco.func if isinstance(deco, ast.Call) else deco
        if (
            isinstance(target, ast.Attribute)
            and target.attr == "command"
            and isinstance(target.value, ast.Name)
            and target.value.id == "router"
        ):
            return True
    return False


def _annotation_source(annotation: ast.expr | None) -> str:
    """Human-readable representation of an annotation expression.

    ``ast.unparse`` is stable across Python 3.9+ and gives us
    ``OBBject[list[BundledIndicatorEntry]]`` rather than a raw AST dump,
    which is what the failure message needs to be actionable.
    """
    if annotation is None:
        return "<no return annotation>"
    return ast.unparse(annotation)


def _is_bare_obbject(annotation: ast.expr | None) -> bool:
    """True if the annotation is bare ``OBBject`` (a Name, not a Subscript).

    ``OBBject`` -> Name('OBBject')            -> bare, OK
    ``OBBject[X]`` -> Subscript(...)          -> parametrized, BAD
    ``list[X]`` or any other name is flagged too so a maintainer accidentally
    typing ``-> list[Model]`` also fails loudly.
    """
    return isinstance(annotation, ast.Name) and annotation.id == "OBBject"


def _collect_offenders() -> list[tuple[pathlib.Path, str, str]]:
    """Walk every router file, find @router.command sites with non-bare returns.

    Returns a list of ``(file, function_name, annotation_source)`` triples
    — the same shape the failure message needs. Empty list means the
    invariant holds.
    """
    offenders: list[tuple[pathlib.Path, str, str]] = []
    for path in ROUTER_FILES:
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not _decorated_with_router_command(node):
                continue
            if _is_bare_obbject(node.returns):
                continue
            offenders.append(
                (path, node.name, _annotation_source(node.returns))
            )
    return offenders


def test_router_files_discovered():
    """Sanity: make sure the glob actually finds the router files.

    If the extension layout ever changes (e.g. routers move out of
    ``routers/*_router.py``), this test would silently pass with an
    empty ROUTER_FILES list — which would mean the invariant isn't
    actually being checked. Fail loudly instead.
    """
    existing = [p for p in ROUTER_FILES if p.exists()]
    assert len(existing) >= 5, (
        f"Expected >=5 router files under {EXT_ROOT}, found {len(existing)}. "
        f"Update ROUTER_FILES glob if the layout changed. Discovered: {existing}"
    )


def test_router_command_returns_are_bare_obbject():
    """Every @router.command must return bare ``OBBject`` (PRD 16.6).

    On failure, the message lists every offender with file, function, and
    the offending annotation source — a maintainer can copy-paste the fix
    from any of the bare siblings (e.g. ``pine_router.about()``,
    ``catalog_router.builtins_coverage()``).
    """
    offenders = _collect_offenders()
    if offenders:
        formatted = "\n".join(
            f"  {path.relative_to(EXT_ROOT.parent)}::{name} -> {anno}"
            for path, name, anno in offenders
        )
        pytest.fail(
            "PRD 16.6 violation — @router.command return annotations must be "
            f"bare ``OBBject``, not parametrized. Offenders:\n{formatted}\n\n"
            "Fix: strip the [T] and describe the payload shape in the docstring "
            "instead. See catalog_router.builtins_coverage() for the canonical "
            "pattern."
        )
