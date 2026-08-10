"""Guard that ``portfolio_intel`` declares ``openbb-techtrade`` as a real dep.

Regression coverage for #1971 (Phase A1 of the as-of snapshot cache design;
spec §9 D1 / §10 Phase A). ``portfolio_intel`` imports ``openbb_techtrade``
at runtime for segments / scan / signals / plan / movers / execution surfaces
(all lazily wrapped), but before A1 the ``pyproject.toml`` did not list
``openbb-techtrade`` in its dependencies at all — ``.venv_portfolio`` only
worked because the sibling ``openbb-techtrade`` happened to be
editable-installed alongside it. This test file is the durable contract that
the install-time seam stays honest.

Two discriminating checks (per repo rule R7 — fixtures must fail on the
reverted primitive):

* ``test_pyproject_declares_openbb_techtrade`` parses the tracked
  ``pyproject.toml`` directly and asserts the dep line is present. Would
  fail even in an environment where ``openbb_techtrade`` is coincidentally
  importable from a sibling install — because the *declaration* is what
  documents the seam, not the environment happening to have it.
* ``test_openbb_techtrade_is_importable`` runs the actual import as a smoke
  test — catches a future accidental undeclare + a missing package on a
  clean venv.

The A1 DoD also stipulates that the dep is expressed as a Poetry
path/develop dependency (not a version pin like ``^0.1.0``), because there
is no ``openbb-techtrade`` wheel on any index. The third test guards that
shape so a well-meaning "let's normalize this to a version" refactor does
not silently break ``.venv_portfolio``.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
import tomllib

# Path to the tracked pyproject.toml — resolve from this test file's location
# (works regardless of pytest invocation cwd).
_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _load_deps() -> dict[str, object]:
    """Return the [tool.poetry.dependencies] table from the tracked pyproject."""
    with _PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    return data["tool"]["poetry"]["dependencies"]


def test_pyproject_declares_openbb_techtrade() -> None:
    """portfolio_intel/pyproject.toml MUST declare openbb-techtrade (#1971).

    Discriminating: reverting the ``pyproject.toml`` change (removing the
    ``openbb-techtrade = ...`` line) makes this test fail immediately, even
    on a machine where ``openbb_techtrade`` remains importable from a
    sibling editable install. That's the whole point of A1 — the *declared*
    seam, not the *happens-to-work* environment.
    """
    deps = _load_deps()
    assert "openbb-techtrade" in deps, (
        "openbb-techtrade must be declared in "
        "openbb_platform/extensions/portfolio_intel/pyproject.toml "
        "[tool.poetry.dependencies] — see #1971 / spec §9 D1. "
        f"Current deps: {sorted(deps)}"
    )


def test_openbb_techtrade_dep_is_path_develop_not_version_pin() -> None:
    """Guard the review-item-#8 shape: path/develop dep, not a version pin.

    A published version pin like ``openbb-techtrade = "^0.1.0"`` would
    break every fresh ``.venv_portfolio`` install because there is no
    ``openbb-techtrade`` wheel on any index. Poetry expresses a
    path/develop dep as a **table** with a ``path`` key, e.g.
    ``{ path = "../techtrade", develop = true }``. A string value (any
    string) is a version pin and MUST fail this test.
    """
    deps = _load_deps()
    entry = deps.get("openbb-techtrade")
    assert entry is not None, "openbb-techtrade dep missing (covered above)"
    assert isinstance(entry, dict), (
        "openbb-techtrade dep must be a Poetry path/develop table "
        f'(e.g. {{ path = "../techtrade", develop = true }}), '
        f"not a bare version string. Got: {entry!r}. "
        "See spec §10 Phase A A1 (review item #8): there is no wheel of "
        "openbb-techtrade on any index, so a version pin would break "
        "every fresh .venv_portfolio install."
    )
    assert "path" in entry, (
        "openbb-techtrade path/develop dep must carry a 'path' key "
        f"pointing at the sibling extension. Got keys: {sorted(entry)}."
    )


def test_openbb_techtrade_is_importable() -> None:
    """Smoke: ``import openbb_techtrade`` must succeed in-process (#1971 DoD).

    Complements the pyproject check: catches the case where the dep is
    declared but the sibling extension is broken / uninstalled in the
    current interpreter. If either half of the seam fails, portfolio_intel
    surfaces that lazy-wrap techtrade will fail at first use — the
    declared-and-installed guarantee is what makes those lazy wraps safe.
    """
    # Force a clean import so a previously cached bad import object
    # does not mask a real breakage between test runs.
    sys.modules.pop("openbb_techtrade", None)
    try:
        mod = importlib.import_module("openbb_techtrade")
    except ImportError as exc:  # pragma: no cover — surfaces the diagnostic
        pytest.fail(
            "openbb_techtrade is not importable in the current interpreter. "
            "portfolio_intel's segments/scan/signals/plan/movers surfaces "
            "lazy-wrap this module; a fresh .venv_portfolio must install "
            "the sibling extension. See #1971 / spec §10 Phase A A1. "
            f"ImportError: {exc}"
        )
    # Basic sanity: the module has *something* under it, i.e. we didn't
    # accidentally import an empty stub.
    assert dir(mod), "openbb_techtrade imported but exposes no attributes"
