"""Regression test: every local Poetry package must be declared in main pyproject.toml.

Root cause caught 2026-07-14: fork-specific extensions
(openbb-techtrade, openbb-regime, openbb-fmp-trading, openbb-fmp-cached,
openbb-backtest, openbb-financialtoolkit, openbb-devtools) had their
code merged from trading_technicals → develop via PR #470 without
being declared in `openbb_platform/pyproject.toml` as path-based
`develop = true` deps.

Symptom: two devs on the same commit SHA got different test results
(one reported 94 failures in Analysis tests; the other reported
265 pass) because `dev_install.py -e` only installs what Poetry
knows about. Missing local extensions → tests using
`from openbb_techtrade import ...` fail on ImportError.

This test blocks the pattern by asserting every locally-present
Poetry package appears in the main pyproject.toml deps section.
Non-Poetry packages (e.g. `openbb-agents` uses PEP 621 + flit) are
in an explicit allow-list.
"""

from __future__ import annotations

import re
from pathlib import Path

from tomlkit import load


ROOT = Path(__file__).parent.parent


# Locally-present packages that CANNOT be Poetry path deps because
# their pyproject uses PEP 621 [project] + flit_core (or similar
# non-Poetry backend). Devs install these manually per README.
NON_POETRY_LOCAL_PACKAGES = {
    "openbb-agents",  # flit_core; needs pip install -e + git submodule init
}


def _find_local_poetry_packages() -> dict[str, Path]:
    """Return {name: pyproject_path} for every local pyproject.toml
    that declares a Poetry package (i.e. has [tool.poetry] with a name).
    """
    packages: dict[str, Path] = {}
    for pj in ROOT.rglob("pyproject.toml"):
        # Skip external / vendored trees
        if any(part in ("external", "pandas-ta-classic", "third_party", "node_modules")
               for part in pj.parts):
            continue
        # Skip the main platform pyproject itself
        if pj.resolve() == (ROOT / "pyproject.toml").resolve():
            continue
        with open(pj, encoding="utf-8") as f:
            data = load(f)
        poetry_section = data.get("tool", {}).get("poetry", {})  # type: ignore
        name = poetry_section.get("name")  # type: ignore
        if name:
            packages[str(name)] = pj
    return packages


def _find_main_pyproject_deps() -> set[str]:
    """Return the set of openbb-* package names declared as deps in
    the main platform pyproject.toml.
    """
    with open(ROOT / "pyproject.toml", encoding="utf-8") as f:
        data = load(f)
    deps = data["tool"]["poetry"]["dependencies"]  # type: ignore
    return {name for name in deps if str(name).startswith("openbb-")}


def test_every_local_poetry_package_is_declared_in_main_pyproject():
    """Guardrail against the 2026-07-14 root cause.

    Every locally-checked-in Poetry package that starts with `openbb-`
    must appear in `openbb_platform/pyproject.toml` as a dep entry
    (path-based `develop = true` is fine, and is in fact the
    canonical pattern for fork-specific extensions).

    Explicitly-known non-Poetry packages are in
    `NON_POETRY_LOCAL_PACKAGES` — adding an entry there must be a
    deliberate, reviewer-visible act (this test's failure message
    will name any new package that needs a decision).
    """
    local = _find_local_poetry_packages()
    declared = _find_main_pyproject_deps()

    # Missing = locally present, not declared, not in the non-Poetry allow-list
    missing = sorted(
        name for name in local
        if name not in declared and name not in NON_POETRY_LOCAL_PACKAGES
    )

    assert not missing, (
        f"\n\n{len(missing)} local Poetry package(s) are NOT declared in "
        f"openbb_platform/pyproject.toml:\n\n"
        + "\n".join(f"  - {n}  (at {local[n].relative_to(ROOT).as_posix()})" for n in missing)
        + "\n\n"
        "Every locally-present openbb-* Poetry package MUST be declared in "
        "the main pyproject.toml as a path-based dep so `dev_install.py -e` "
        "picks it up automatically. Pattern:\n\n"
        '  openbb-<name> = { path = "extensions/<dir>", version = "X.Y.Z", '
        'develop = true, optional = true }\n\n'
        "Also add it to the appropriate `[tool.poetry.extras]` block and "
        "to the `all = [...]` list. Without these entries, new developers "
        "who run `python dev_install.py -e` will NOT get the extension "
        "installed and will see mysterious ImportErrors in tests — this "
        "is the exact root cause caught 2026-07-14. If the package "
        "genuinely cannot be a Poetry dep (e.g. it uses PEP 621 + flit), "
        "add it to NON_POETRY_LOCAL_PACKAGES in this file with a comment "
        "explaining why."
    )


def test_non_poetry_allowlist_entries_actually_exist_and_are_non_poetry():
    """Sanity: every name in NON_POETRY_LOCAL_PACKAGES must actually be
    a real local package AND use a non-Poetry build backend. Otherwise
    the allow-list has drifted from reality and someone could use it
    to bypass the guardrail.
    """
    all_pyprojects = list(ROOT.rglob("pyproject.toml"))
    for allow_name in NON_POETRY_LOCAL_PACKAGES:
        matched = None
        for pj in all_pyprojects:
            if any(part in ("external", "pandas-ta-classic", "third_party", "node_modules")
                   for part in pj.parts):
                continue
            with open(pj, encoding="utf-8") as f:
                text = f.read()
            # Either [tool.poetry] name = "..." or [project] name = "..."
            for m in re.finditer(r'^name\s*=\s*"([^"]+)"', text, flags=re.MULTILINE):
                if m.group(1) == allow_name:
                    matched = pj
                    break
            if matched:
                break
        assert matched, (
            f"{allow_name} is in NON_POETRY_LOCAL_PACKAGES but no local "
            f"pyproject.toml declares it. Either remove from the allow-list "
            f"or add the package."
        )
        # And confirm it really is non-Poetry (build backend not poetry)
        text = matched.read_text(encoding="utf-8")
        assert "poetry.core.masonry.api" not in text, (
            f"{allow_name} is in NON_POETRY_LOCAL_PACKAGES but its "
            f"pyproject.toml uses poetry.core.masonry.api — it can and "
            f"should be declared as a Poetry path dep in main "
            f"openbb_platform/pyproject.toml. Remove from the allow-list."
        )
