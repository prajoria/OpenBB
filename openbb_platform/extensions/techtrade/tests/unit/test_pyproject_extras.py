"""Unit tests that pyproject.toml declares the [tuneta] and [validation] extras (#82 + #83)."""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover - python 3.10 fallback
    import tomli as tomllib  # type: ignore[import-not-found]


_PYPROJECT = (
    Path(__file__).resolve().parents[2] / "pyproject.toml"
)


def _read_extras() -> dict[str, list[str]]:
    with _PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    return data["tool"]["poetry"]["extras"]


def test_tuneta_extra_is_declared():
    """#83 L8: `tuneta` ships as an optional extra users install via [tuneta]."""
    extras = _read_extras()
    assert "tuneta" in extras, (
        "pyproject.toml [tool.poetry.extras] is missing the `tuneta` entry. "
        "Add: tuneta = [\"tuneta\"]"
    )
    assert extras["tuneta"] == ["tuneta"]


def test_validation_extra_is_still_declared():
    """#82 regression: declaring [tuneta] must not remove the [validation] extra."""
    extras = _read_extras()
    assert extras.get("validation") == ["openbb-backtest"]
