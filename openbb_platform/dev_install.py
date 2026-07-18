"""Install for development script.

Iterates the LOCAL_DEPS declaration and pip-installs each entry as editable.
Replaces the previous poetry-based flow (see #865) which silently no-op'd
in fresh pip venvs — poetry saw no [tool.poetry] project spec and reported
'no dependencies to install or update' without writing anything.

Usage:
    python dev_install.py            # core + platform-required extensions
    python dev_install.py -e         # + community/optional deps + per-package dev deps
    python dev_install.py -c         # also install the openbb-cli package
    python dev_install.py -e -c      # both
"""

# flake8: noqa: S603

import subprocess
import sys
from pathlib import Path

from tomlkit import load, loads

PLATFORM_PATH = Path(__file__).parent.resolve()
CLI_PATH = Path(__file__).parent.parent.resolve() / "cli"

LOCAL_DEPS = """
[tool.poetry.dependencies]
python = ">=3.10,<3.14"
openbb-devtools = { path = "./extensions/devtools", develop = true, markers = "python_version >= '3.10'" }
openbb-core = { path = "./core", develop = true }
openbb-platform-api = { path = "./extensions/platform_api", develop = true }

openbb-benzinga = { path = "./providers/benzinga", develop = true }
openbb-bls = { path = "./providers/bls", develop = true }
openbb-cftc = { path = "./providers/cftc", develop = true }
openbb-congress-gov = { path = "./providers/congress_gov", develop = true }
openbb-econdb = { path = "./providers/econdb", develop = true }
openbb-federal-reserve = { path = "./providers/federal_reserve", develop = true }
openbb-fmp = { path = "./providers/fmp", develop = true }
openbb-fred = { path = "./providers/fred", develop = true }
openbb-government-us = { path = "./providers/government_us", develop = true }
openbb-imf = { path = "./providers/imf", develop = true }
openbb-intrinio = { path = "./providers/intrinio", develop = true }
openbb-oecd = { path = "./providers/oecd", develop = true }
openbb-sec = { path = "./providers/sec", develop = true }
openbb-tiingo = { path = "./providers/tiingo", develop = true }
openbb-tradingeconomics = { path = "./providers/tradingeconomics", develop = true }
openbb-us-eia = { path = "./providers/eia", develop = true }
openbb-yfinance = { path = "./providers/yfinance", develop = true }

openbb-commodity = { path = "./extensions/commodity", develop = true }
openbb-crypto = { path = "./extensions/crypto", develop = true }
openbb-currency = { path = "./extensions/currency", develop = true }
openbb-derivatives = { path = "./extensions/derivatives", develop = true }
openbb-economy = { path = "./extensions/economy", develop = true }
openbb-equity = { path = "./extensions/equity", develop = true }
openbb-etf = { path = "./extensions/etf", develop = true }
openbb-techtrade = { path = "./extensions/techtrade", develop = true }
openbb-fixedincome = { path = "./extensions/fixedincome", develop = true }
openbb-index = { path = "./extensions/index", develop = true }
openbb-news = { path = "./extensions/news", develop = true }
openbb-regulators = { path = "./extensions/regulators", develop = true }
openbb-mcp-server = { path = "./extensions/mcp_server", develop = true, markers = "python_version >= '3.10'" }

# Fork-only extensions (Portfolio Intelligence Engine + backtest primitives).
# openbb-portfolio-intel imports from openbb_backtest.interfaces at runtime
# (SimpleFillModel implements the Broker Protocol — issue #498 A' resolution),
# so both must be installed together on any dev checkout.
openbb-backtest = { path = "./extensions/backtest", develop = true }
openbb-portfolio-intel = { path = "./extensions/portfolio_intel", develop = true }

# Community dependencies
openbb-alpha-vantage = { path = "./providers/alpha_vantage", optional = true, develop = true }
openbb-biztoc = { path = "./providers/biztoc", optional = true, develop = true }
openbb-cboe = { path = "./providers/cboe", optional = true, develop = true }
openbb-deribit = { path = "./providers/deribit", optional = true, develop = true }
openbb-ecb = { path = "./providers/ecb", optional = true, develop = true }
openbb-famafrench = { path = "./providers/famafrench", optional = true, develop = true }
openbb-finra = { path = "./providers/finra", optional = true, develop = true }
openbb-finviz = { path = "./providers/finviz", optional = true, develop = true }
openbb-multpl = { path = "./providers/multpl", optional = true, develop = true }
openbb-nasdaq = { path = "./providers/nasdaq", optional = true, develop = true }
openbb-seeking-alpha = { path = "./providers/seeking_alpha", optional = true, develop = true }
openbb-stockgrid = { path = "./providers/stockgrid" , optional = true,  develop = true }
openbb_tmx = { path = "./providers/tmx", optional = true, develop = true }
openbb_tradier = { path = "./providers/tradier", optional = true, develop = true }
openbb-wsj = { path = "./providers/wsj", optional = true, develop = true }

openbb-charting = { path = "./obbject_extensions/charting", optional = true, develop = true }
openbb-econometrics = { path = "./extensions/econometrics", optional = true, develop = true }
openbb-quantitative = { path = "./extensions/quantitative", optional = true, develop = true }
openbb-technical = { path = "./extensions/technical", optional = true, develop = true }
"""


def _is_python_version_dep(name: str) -> bool:
    """Skip the pseudo-dep 'python' declared as version-range in LOCAL_DEPS."""
    return name == "python"


def _package_marker_active(info: dict) -> bool:
    """Honor the ``markers = "python_version >= 'X.Y'"`` gate if present.

    LOCAL_DEPS uses this on ``openbb-devtools`` and ``openbb-mcp-server``.
    We evaluate the marker with the actual runtime interpreter version.
    """
    marker = info.get("markers")
    if not marker:
        return True
    try:
        # pylint: disable=import-outside-toplevel
        # Deliberate lazy import: packaging may not exist yet at bootstrap
        # (pre-first-install) — falling through to the permissive branch
        # below is safer than crashing.
        from packaging.markers import Marker
    except ImportError:
        # If packaging isn't available at bootstrap time, be permissive —
        # a marker miss here just installs one extra package.
        return True
    return Marker(marker).evaluate()


def _iter_paths(include_optional: bool):
    """Yield (name, path_str) for every LOCAL_DEPS entry to install.

    Skips the ``python`` pseudo-dep, skips ``optional`` entries when
    ``include_optional`` is False, honors ``markers`` on gated packages.
    """
    local_deps = loads(LOCAL_DEPS).get("tool", {}).get("poetry", {})["dependencies"]
    for name, info in local_deps.items():
        if _is_python_version_dep(name):
            continue
        if not isinstance(info, dict) or "path" not in info:
            continue
        if info.get("optional") and not include_optional:
            continue
        if not _package_marker_active(info):
            continue
        yield name, info["path"]


def _extract_dev_deps_from_pyproject(package_path: Path) -> dict:
    """Return the ``[tool.poetry.group.dev.dependencies]`` table for a package.

    Empty if the package has no dev group. Used to install pytest / mypy /
    ruff (etc.) into the venv when the user passes ``--extras``.
    """
    pyproject = package_path / "pyproject.toml"
    if not pyproject.exists():
        return {}
    with open(pyproject, encoding="utf-8") as f:
        data = load(f)
    return (
        data.get("tool", {})
        .get("poetry", {})
        .get("group", {})
        .get("dev", {})
        .get("dependencies", {})
    )


def _collect_dev_deps() -> list[str]:
    """Aggregate dev-dep NAMES across every LOCAL_DEPS package (extras mode).

    Returns a sorted, de-duplicated list of package names (no version
    constraints — pip resolves the latest compatible). Poetry-only version
    syntax (``^1.2``, ``~=1.2``) isn't pip-parseable, so we ship the name
    only and let pip pick.
    """
    names: set[str] = set()
    for _, path_str in _iter_paths(include_optional=True):
        deps = _extract_dev_deps_from_pyproject(PLATFORM_PATH / path_str)
        for dep_name in deps:
            if dep_name == "python":
                continue
            names.add(dep_name)
    return sorted(names)


def _pip_install(pip_args: list[str], cwd: Path | None = None) -> None:
    """Run ``python -m pip install`` with the given args, streaming output.

    Uses the currently-running interpreter, so this installs into whichever
    venv the user invoked the script from. That is the fix for #865: poetry
    couldn't do this reliably; pip always does.
    """
    cmd = [sys.executable, "-m", "pip", "install", *pip_args]
    print(f"$ {' '.join(cmd)}", flush=True)  # noqa: T201
    subprocess.run(cmd, cwd=cwd, check=True)


def install_platform_local(_extras: bool = False) -> None:
    """Install the Platform locally for development purposes.

    Iterates LOCAL_DEPS and pip-installs each entry as editable. When
    ``_extras`` is True, also installs community/optional packages plus the
    per-package dev dependencies (pytest, mypy, ruff, etc.).
    """
    paths = list(_iter_paths(include_optional=_extras))
    print(f"Installing {len(paths)} editable package(s)...", flush=True)  # noqa: T201
    editable_args: list[str] = []
    for _name, path_str in paths:
        editable_args.extend(["-e", str(PLATFORM_PATH / path_str)])
    # Single pip invocation resolves the dependency graph across all
    # packages at once, avoiding N re-resolves and version-thrash.
    _pip_install(editable_args)

    if _extras:
        dev_names = _collect_dev_deps()
        if dev_names:
            print(
                f"Installing {len(dev_names)} dev dependency package(s)...", flush=True
            )  # noqa: T201
            _pip_install(dev_names)


def install_platform_cli() -> None:
    """Install the openbb-cli package locally for development.

    The CLI's pyproject depends on the meta ``openbb`` package (which we
    don't install here — the individual extensions above are already
    editable). pip resolves the direct CLI deps against site-packages.
    """
    print("Installing openbb-cli (editable)...", flush=True)  # noqa: T201
    _pip_install(["-e", str(CLI_PATH)])


if __name__ == "__main__":
    args = sys.argv[1:]
    extras = any(arg.lower() in ["-e", "--extras"] for arg in args)
    cli = any(arg.lower() in ["-c", "--cli"] for arg in args)
    install_platform_local(extras)
    if cli:
        install_platform_cli()
