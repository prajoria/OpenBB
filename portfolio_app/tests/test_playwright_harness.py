"""Contract tests for the Playwright E2E harness.

Bead: OpenBBTechnical-qy83.1.7 — Playwright E2E harness + widget scaffolds.

M0 scope: the harness directory exists with a valid Playwright config,
a first placeholder widget contract test, and a documented runbook. It
does NOT need to actually launch a browser at M0 (that requires ``npx
playwright install`` which is a dev-machine setup step).

These structural tests guard the *shape* so subsequent P1 widget tests
just add ``.spec.ts`` files without rewriting the harness.

Hardening (PR #468 R2):
- ``playwright.config.ts`` checks upgraded from raw substring to
  regex-scoped presence of ``defineConfig({ ... })`` and load-bearing
  fields (``testDir``, ``baseURL``, at least one project). A file that
  put those tokens in a comment or docstring no longer trips the guard.
- ``package.json`` no longer declares the stale ``typescript`` devDep
  — Playwright bundles its own TS transpile.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

E2E_ROOT = Path(__file__).resolve().parent / "e2e"


def test_e2e_directory_exists() -> None:
    """M0 exit-gate: ``portfolio_app/tests/e2e/`` is on disk."""
    assert E2E_ROOT.is_dir(), f"missing e2e dir: {E2E_ROOT}"


def _config_body_stripped_of_comments() -> str:
    """Return playwright.config.ts with // and /* */ comments removed.

    Playwright config is TS/JS; substring checks on the raw file can be
    fooled by tokens inside comments (PR #468 R2 finding 4). Strip
    comments so structural checks assert on real code only.
    """
    cfg = E2E_ROOT / "playwright.config.ts"
    body = cfg.read_text(encoding="utf-8")
    # Remove /* ... */ blocks and // ... EOL comments. Not a full JS
    # parser but good enough for the well-formed config we ship.
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"//[^\n]*", "", body)
    return body


def test_playwright_config_present_and_structurally_valid() -> None:
    """``playwright.config.ts`` must call defineConfig with load-bearing fields.

    Post-R2 (finding 4): asserts on comment-stripped source so a config
    that put ``defineConfig`` or ``testDir`` in a comment doesn't sneak
    past. Also asserts the three load-bearing fields (testDir, baseURL
    env-override, at least one project).
    """
    cfg = E2E_ROOT / "playwright.config.ts"
    assert cfg.is_file(), "playwright.config.ts missing"
    src = _config_body_stripped_of_comments()

    assert re.search(
        r"defineConfig\s*\(", src
    ), "config must invoke defineConfig(...) — not just mention it in a comment"
    assert re.search(r"testDir\s*:", src), "config must set testDir field"
    assert re.search(r"baseURL\s*:", src), "config must set a baseURL"
    assert (
        "PORTFOLIO_APP_BASE_URL" in src
    ), "config must honor PORTFOLIO_APP_BASE_URL env override (see README)"
    assert re.search(
        r"projects\s*:\s*\[", src
    ), "config must define at least one project (chromium)"
    assert re.search(
        r"name\s*:\s*['\"]chromium['\"]", src
    ), "config must include a `chromium` project — matches README"


def test_package_json_declares_playwright_and_scripts() -> None:
    """``package.json`` must pin Playwright and expose an ``e2e`` script.

    Locks the dependency so `npm install` in this dir gives every
    developer the same Playwright version. The ``e2e`` script is the
    single documented entry point used by CI and by devs alike.

    Post-R2 (finding 5): asserts the stale `typescript` devDep was
    removed. Playwright bundles its own TS transpile; carrying the
    devDep without a tsconfig was dead weight.
    """
    pkg = E2E_ROOT / "package.json"
    assert pkg.is_file(), "package.json missing under tests/e2e/"
    data = json.loads(pkg.read_text(encoding="utf-8"))
    assert data.get("name"), "package.json must declare name"
    dev_deps = data.get("devDependencies", {})
    assert "@playwright/test" in dev_deps, "Playwright must be pinned as devDependency"
    assert "typescript" not in dev_deps, (
        "typescript devDep should be removed (Playwright bundles its own "
        "transpile; no tsconfig.json is checked in). PR #468 R2 finding 5."
    )
    scripts = data.get("scripts", {})
    for required in ("e2e", "e2e:headed", "e2e:ui", "e2e:report"):
        assert (
            required in scripts
        ), f"package.json must expose `{required}` script (README lists it)"


def test_placeholder_widget_spec_present_and_actually_a_test() -> None:
    """At least one ``.spec.ts`` file must live under ``e2e/tests/`` and
    contain a real ``test(...)`` call.

    Post-R2 finding 4: an empty ``.spec.ts`` file would satisfy the
    previous test. Assert the file actually calls ``test(...)`` so a
    literal placeholder file (all comments) doesn't fake the harness.
    """
    specs = list((E2E_ROOT / "tests").glob("*.spec.ts"))
    assert specs, "at least one .spec.ts file must exist under tests/e2e/tests/"
    for spec in specs:
        body = spec.read_text(encoding="utf-8")
        assert re.search(r"\btest\s*\(", body), (
            f"{spec.name}: file must contain a `test(...)` call, not just "
            "comments or imports"
        )


def test_readme_documents_setup_and_runbook_and_ci_status() -> None:
    """``README.md`` must document install + run + CI status.

    Post-R2 finding 2: the harness is dev-machine-only at M0. README now
    explicitly documents that no GitHub Actions workflow runs the suite,
    so a downstream engineer doesn't wait for green CI that will never
    come.
    """
    readme = E2E_ROOT / "README.md"
    assert readme.is_file(), "README.md missing under tests/e2e/"
    body = readme.read_text(encoding="utf-8").lower()
    assert "npm install" in body, "README must document npm install"
    assert (
        "playwright install" in body
    ), "README must document `npx playwright install` browser download"
    assert "npm run e2e" in body, "README must document how to run the suite"
    assert (
        "dev-machine only" in body or "no github actions" in body or "no ci" in body
    ), "README must explicitly note that this harness is not wired to CI at M0"


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
