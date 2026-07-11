"""Contract tests for the Playwright E2E harness.

Bead: OpenBBTechnical-qy83.1.7 — Playwright E2E harness + widget scaffolds.

M0 scope: the harness directory exists with a valid Playwright config,
a first placeholder widget contract test, and a documented runbook. It
does NOT need to actually launch a browser at M0 (that requires ``npx
playwright install`` which is a dev-machine setup step).

These structural tests guard the *shape* so subsequent P1 widget tests
just add ``.spec.ts`` files without rewriting the harness.
"""

from __future__ import annotations

import json
from pathlib import Path

E2E_ROOT = Path(__file__).resolve().parent / "e2e"


def test_e2e_directory_exists() -> None:
    """M0 exit-gate: ``portfolio_app/tests/e2e/`` is on disk."""
    assert E2E_ROOT.is_dir(), f"missing e2e dir: {E2E_ROOT}"


def test_playwright_config_present_and_parseable() -> None:
    """``playwright.config.ts`` must exist and be non-empty.

    Playwright refuses to run without a config; the harness is unusable
    if this file is missing. We check the file exists and has enough
    body to hold at least a ``defineConfig`` call.
    """
    cfg = E2E_ROOT / "playwright.config.ts"
    assert cfg.is_file(), "playwright.config.ts missing"
    body = cfg.read_text(encoding="utf-8")
    assert "defineConfig" in body, "playwright.config.ts must call defineConfig()"
    assert "testDir" in body, "playwright.config.ts must set testDir"


def test_package_json_declares_playwright_and_scripts() -> None:
    """``package.json`` must pin Playwright and expose an ``e2e`` script.

    Locks the dependency so `npm install` in this dir gives every
    developer the same Playwright version. The ``e2e`` script is the
    single documented entry point used by CI and by devs alike.
    """
    pkg = E2E_ROOT / "package.json"
    assert pkg.is_file(), "package.json missing under tests/e2e/"
    data = json.loads(pkg.read_text(encoding="utf-8"))
    assert data.get("name"), "package.json must declare name"
    dev_deps = data.get("devDependencies", {})
    assert "@playwright/test" in dev_deps, "Playwright must be pinned as devDependency"
    scripts = data.get("scripts", {})
    assert "e2e" in scripts, (
        "package.json must expose an `e2e` script (single documented "
        "entry point for CI and devs)"
    )


def test_placeholder_widget_spec_present() -> None:
    """At least one ``.spec.ts`` file must live under ``e2e/tests/``.

    The M0 placeholder test proves the harness *shape* — future P1
    widget tests (`xray_sector.spec.ts`, `blotter.spec.ts`, etc.) drop
    into the same directory and inherit the config automatically.
    """
    specs = list((E2E_ROOT / "tests").glob("*.spec.ts"))
    assert specs, "at least one .spec.ts file must exist under tests/e2e/tests/"


def test_readme_documents_setup_and_runbook() -> None:
    """``README.md`` must document install + run so nobody guesses.

    Playwright requires an out-of-band ``npx playwright install`` after
    ``npm install`` — the number one gotcha for new devs. The README
    calls it out explicitly.
    """
    readme = E2E_ROOT / "README.md"
    assert readme.is_file(), "README.md missing under tests/e2e/"
    body = readme.read_text(encoding="utf-8").lower()
    assert "npm install" in body, "README must document npm install"
    assert (
        "playwright install" in body
    ), "README must document `npx playwright install` browser download"
    assert "npm run e2e" in body, "README must document how to run the suite"


def test_gitignore_excludes_playwright_output() -> None:
    """Playwright's default output dirs must be gitignored.

    ``test-results/`` and ``playwright-report/`` are per-run artefacts
    that must never be committed. Also excludes ``node_modules/``.
    """
    ignore = E2E_ROOT / ".gitignore"
    assert ignore.is_file(), ".gitignore missing under tests/e2e/"
    body = ignore.read_text(encoding="utf-8")
    for expected in ("node_modules", "test-results", "playwright-report"):
        assert expected in body, f".gitignore must exclude {expected}"
