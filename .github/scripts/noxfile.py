"""Nox sessions."""

from pathlib import Path

import nox

ROOT_DIR = Path(__file__).parent.parent.parent
PLATFORM_DIR = ROOT_DIR / "openbb_platform"
PLATFORM_TESTS = [str(PLATFORM_DIR / p) for p in ["tests", "core", "providers", "extensions"]]
CLI_DIR = ROOT_DIR / "cli"
CLI_TESTS = CLI_DIR / "tests"


@nox.session(python=["3.10", "3.11", "3.12", "3.13", "3.14"])
def unit_test_platform(session):
    """Run the test suite."""
    session.install("poetry")
    session.run(
        "python",
        str(PLATFORM_DIR / "dev_install.py"),
        "-e",
        external=True,
    )
    session.install("pytest")
    session.install("pytest-cov")

    session.run(
        "pytest",
        *PLATFORM_TESTS,
        f"--cov={PLATFORM_DIR}",
        "-m",
        # Skip:
        # - integration (need API keys / network)
        # - requires_agents (openbb-agents needs Rust toolchain for litellm; too heavy for stock CI)
        # - requires_mysql (fmp_cached tests need a live MySQL container)
        # - nightly (expensive subprocess-spawning tests)
        "not integration and not requires_agents and not requires_mysql and not nightly",
    )


@nox.session(python=["3.10", "3.11", "3.12", "3.13", "3.14"])
def unit_test_cli(session):
    """Run the test suite."""
    session.install("poetry")
    session.run(
        "python",
        str(PLATFORM_DIR / "dev_install.py"),
        "-e",
        "--cli",
        external=True,
    )
    session.install("pytest")
    session.install("pytest-cov")
    session.run("pytest", CLI_TESTS, f"--cov={CLI_DIR}")
