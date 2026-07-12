"""Regression test for the openbb-techtrade python constraint bug.

Bead: OpenBBTechnical-qy83.1.13 — dev_install.py -e fails because
openbb-techtrade declares Python >=3.10,<3.14 while the platform
declares >=3.10,<4. Poetry solver cannot converge.

Bead: OpenBBTechnical-qy83.1.14 — downstream symptom: because
dev_install.py -e never completes, openbb-fmp is not editable-installed
from the in-tree source, so openbb_fmp_cached fails to import
'openbb_fmp.models.aftermarket_trade' (present in-tree, absent from
PyPI's openbb-fmp 1.6.1).

This test asserts the constraint is compatible with the platform's
range. It is a static check that reads pyproject.toml — it does not
require running poetry lock. If someone re-narrows the constraint,
this test fails loudly instead of silently breaking dev_install
next time an engineer tries to set up a fresh venv.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
PLATFORM_PYPROJECT = REPO_ROOT / "openbb_platform" / "pyproject.toml"
TECHTRADE_PYPROJECT = (
    REPO_ROOT / "openbb_platform" / "extensions" / "techtrade" / "pyproject.toml"
)


def _python_upper_bound(pyproject_path: Path) -> str:
    """Extract the `<X.Y` upper bound from a Poetry python-range string."""
    body = pyproject_path.read_text(encoding="utf-8")
    # Only look at the [tool.poetry.dependencies] python line — avoid
    # matching python-constraint mentions in extras/deps.
    m = re.search(
        r"\[tool\.poetry\.dependencies\][\s\S]+?python\s*=\s*\"[^<]*(<[^\"]+)\"",
        body,
    )
    assert m, f"could not locate python constraint in {pyproject_path}"
    return m.group(1).strip()


def test_techtrade_python_bound_matches_or_widens_platform() -> None:
    """openbb-techtrade must not be *narrower* than the platform's range.

    If techtrade caps python lower than the platform, dev_install.py -e's
    poetry lock step cannot converge and the whole editable install
    fails. This is the regression we're preventing.

    Allowed:
      - platform '<4' + techtrade '<4'  -> passes
      - platform '<4' + techtrade '<5'  -> passes (wider still ok)
    Forbidden:
      - platform '<4' + techtrade '<3.14'  -> the qy83.1.13 bug
    """
    platform_upper = _python_upper_bound(PLATFORM_PYPROJECT)
    techtrade_upper = _python_upper_bound(TECHTRADE_PYPROJECT)

    # Parse `<3.14` -> (3, 14) and `<4` -> (4,) for numeric comparison.
    def parse(s: str) -> tuple[int, ...]:
        m = re.match(r"<\s*([\d.]+)", s)
        assert m, f"unparseable upper bound: {s}"
        return tuple(int(x) for x in m.group(1).split("."))

    def normalise(t: tuple[int, ...]) -> tuple[int, ...]:
        # Pad to the same length for lexicographic compare.
        return t + (0,) * (3 - len(t))

    platform_key = normalise(parse(platform_upper))
    techtrade_key = normalise(parse(techtrade_upper))

    assert techtrade_key >= platform_key, (
        f"openbb-techtrade python upper bound '{techtrade_upper}' is "
        f"NARROWER than platform's '{platform_upper}' — this breaks "
        "dev_install.py -e (bead qy83.1.13). Widen techtrade to at "
        "least match the platform range."
    )
