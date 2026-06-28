"""Reusable golden-file test harness for techtrade (issue #71, PRD §17).

A small, dependency-light, fully-typed helper that the techtrade test suites
(#72-#82) use to lock deterministic engine outputs against committed golden JSON
fixtures. Modelled on the merged ``openbb-backtest`` golden harness and on the
``pandas.testing`` / ``numpy.testing`` convention of shipping test utilities
inside the package so every test gets an unambiguous import that is stable across
pytest import modes.

Two public entry points:

``to_jsonable``
    Recursively coerces an arbitrary engine result into a JSON-stable structure:
    pydantic ``Data`` / ``BaseModel`` -> ``model_dump()``; ``Decimal`` -> ``str``
    (lossless, mirrors the money/quantity Decimal discipline); ``datetime`` /
    ``date`` -> ISO ``str``; non-finite floats (NaN / +Inf / -Inf) -> a stable
    ``"__nonfinite__:..."`` sentinel string; containers recurse.

``assert_matches_golden``
    Serializes a payload with ``to_jsonable`` and compares it against the
    committed ``<name>.json`` under a caller-supplied ``fixture_dir`` within a
    float tolerance. Setting ``TECHTRADE_REGEN_GOLDEN=1`` rewrites the fixture
    instead of asserting, so goldens are regenerated intentionally after a
    *reviewed* behavioural change -- never blindly.
"""

from __future__ import annotations

import json
import math
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

#: Environment variable that, when set to ``"1"``, rewrites goldens in place.
REGEN_ENV = "TECHTRADE_REGEN_GOLDEN"
#: Default absolute tolerance for float comparisons in :func:`assert_matches_golden`.
DEFAULT_TOL = 1e-9


def to_jsonable(obj: object) -> object:
    """Recursively coerce ``obj`` into a JSON-stable, comparable structure.

    The coercion is deterministic and lossless for the techtrade value types:
    pydantic models become plain dicts, ``Decimal`` becomes its exact ``str``
    form, and dates/datetimes become ISO strings. Plain JSON scalars pass through
    untouched; anything unrecognised falls back to ``str(obj)``.

    Parameters
    ----------
    obj : object
        An arbitrary value -- a pydantic ``Data`` / ``BaseModel``, ``Decimal``,
        ``date`` / ``datetime``, mapping, sequence, JSON scalar, or other object.

    Returns
    -------
    object
        A structure composed only of ``dict`` / ``list`` / ``str`` / ``int`` /
        ``float`` / ``bool`` / ``None``, safe to ``json.dumps`` and to compare.
    """
    if isinstance(obj, BaseModel):
        return to_jsonable(obj.model_dump())
    if isinstance(obj, Decimal):
        return str(obj)
    # ``datetime`` must be checked before ``date`` -- it is a ``date`` subclass.
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {key: to_jsonable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(item) for item in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        # NaN / +Inf / -Inf are not valid strict JSON and NaN never equals
        # itself; coerce to a stable, comparable sentinel so indicator goldens
        # (which produce NaN during warm-up bars) serialize and lock cleanly.
        return f"__nonfinite__:{obj}"
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    return str(obj)


def assert_matches_golden(
    name: str,
    payload: object,
    *,
    fixture_dir: Path | str,
    tol: float = DEFAULT_TOL,
) -> None:
    """Assert ``payload`` matches the committed ``<name>.json`` golden fixture.

    ``payload`` is first normalised with :func:`to_jsonable`. When the
    :data:`REGEN_ENV` environment variable is ``"1"`` the normalised payload is
    written to ``fixture_dir/<name>.json`` (pretty-printed, key-sorted) and the
    function returns without asserting -- this is the intentional regeneration
    path. Otherwise the golden is read and compared structurally, with floats
    matched within absolute tolerance ``tol``.

    Parameters
    ----------
    name : str
        Fixture stem; the file is ``fixture_dir/<name>.json``.
    payload : object
        The value under test (coerced via :func:`to_jsonable`).
    fixture_dir : Path | str
        Directory holding the golden fixture for this test.
    tol : float, optional
        Absolute float tolerance, defaulting to :data:`DEFAULT_TOL`.

    Raises
    ------
    AssertionError
        If the normalised payload diverges from the golden (structure or value).
    FileNotFoundError
        If the golden fixture is absent and regeneration is not requested.
    """
    normalised = to_jsonable(payload)
    path = Path(fixture_dir) / f"{name}.json"

    if os.environ.get(REGEN_ENV) == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(normalised, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return

    golden = json.loads(path.read_text(encoding="utf-8"))
    _assert_equal(golden, normalised, tol, name)


def _assert_equal(golden: object, actual: object, tol: float, path_str: str) -> None:
    """Recursively assert ``actual`` equals ``golden``, reporting the JSON path.

    Dicts must share the same key set; lists the same length; floats (on either
    side) match within absolute tolerance ``tol``; everything else by ``==``. On
    any divergence an :class:`AssertionError` is raised carrying the
    dotted/indexed ``path_str`` to the offending node.

    Parameters
    ----------
    golden : object
        The committed expected value at this node.
    actual : object
        The normalised actual value at this node.
    tol : float
        Absolute float tolerance.
    path_str : str
        Human-readable path to this node (for the assertion message).
    """
    if isinstance(golden, dict) or isinstance(actual, dict):
        if not (isinstance(golden, dict) and isinstance(actual, dict)):
            raise AssertionError(f"{path_str}: type mismatch {golden!r} != {actual!r}")
        if set(golden) != set(actual):
            raise AssertionError(
                f"{path_str}: keys differ -- golden {sorted(golden)} vs actual {sorted(actual)}"
            )
        for key in golden:
            _assert_equal(golden[key], actual[key], tol, f"{path_str}.{key}")
        return

    if isinstance(golden, list) or isinstance(actual, list):
        if not (isinstance(golden, list) and isinstance(actual, list)):
            raise AssertionError(f"{path_str}: type mismatch {golden!r} != {actual!r}")
        if len(golden) != len(actual):
            raise AssertionError(
                f"{path_str}: length differs -- golden {len(golden)} vs actual {len(actual)}"
            )
        for index, (g_item, a_item) in enumerate(zip(golden, actual)):
            _assert_equal(g_item, a_item, tol, f"{path_str}[{index}]")
        return

    if isinstance(golden, float) or isinstance(actual, float):
        if not isinstance(golden, (int, float)) or not isinstance(actual, (int, float)):
            raise AssertionError(f"{path_str}: type mismatch {golden!r} != {actual!r}")
        if abs(float(actual) - float(golden)) > tol:
            raise AssertionError(f"{path_str}: {actual!r} != {golden!r} (abs tol {tol})")
        return

    if golden != actual:
        raise AssertionError(f"{path_str}: {actual!r} != {golden!r}")
