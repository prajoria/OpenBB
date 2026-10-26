"""Assert that the running environment is exactly what a dependency lock pins.

Run inside a replayed MCP environment (``scripts/test_mcp_lock_replay.ps1``)::

    python assert_lock_replay.py <lock.txt>

Depends only on the standard library and ``packaging``, which both locks pin,
because ``scripts/`` is not importable inside the replayed environment.
"""

import json
import re
import sys
from collections.abc import Iterable
from importlib import metadata
from pathlib import Path
from typing import cast

from packaging.markers import Marker, default_environment


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def expected_from_lock(text: str, environment: dict[str, str]) -> dict[str, str]:
    """Return the pins whose environment markers apply to ``environment``."""
    expected = {}
    for line in text.splitlines():
        if not line or line[0] in " #-" or "==" not in line:
            continue
        requirement, _, marker = line.rstrip(" \\").partition(";")
        name, version = requirement.split("==", 1)
        if marker.strip() and not Marker(marker.strip()).evaluate(environment):
            continue
        expected[_normalize(name)] = version.strip()
    return expected


def _is_editable(distribution: metadata.Distribution) -> bool:
    direct_url = distribution.read_text("direct_url.json")
    if not direct_url:
        return False
    return bool(json.loads(direct_url).get("dir_info", {}).get("editable"))


def _in_base_interpreter(
    distribution: metadata.Distribution, base_prefix: str, prefix: str
) -> bool:
    if Path(base_prefix).resolve() == Path(prefix).resolve():
        return False
    location = Path(str(distribution.locate_file(""))).resolve()
    return location.is_relative_to(Path(base_prefix).resolve())


def installed(
    distributions: Iterable[metadata.Distribution] | None = None,
    *,
    base_prefix: str = sys.base_prefix,
    prefix: str = sys.prefix,
) -> dict[str, str]:
    """Return the distributions uv installed into the environment.

    Editables are checkout-local, and packages bundled with the base interpreter
    (for example pip in uv-managed Pythons) were never resolved from the lock.
    """
    if distributions is None:
        distributions = metadata.distributions()
    return {
        _normalize(distribution.metadata["Name"]): distribution.version
        for distribution in distributions
        if not _is_editable(distribution)
        and not _in_base_interpreter(distribution, base_prefix, prefix)
    }


def compare(expected: dict[str, str], actual: dict[str, str]) -> list[str]:
    """Return every difference between the lock and the environment."""
    messages = [
        f"missing {name}=={version}"
        for name, version in expected.items()
        if name not in actual
    ]
    messages += [
        f"unexpected {name}=={version}"
        for name, version in actual.items()
        if name not in expected
    ]
    messages += [
        f"version {name}: lock {version} installed {actual[name]}"
        for name, version in expected.items()
        if name in actual and actual[name] != version
    ]
    return messages


def main(argv: list[str]) -> int:
    """Compare the running environment against the lock named in ``argv``."""
    lock = Path(argv[1])
    expected = expected_from_lock(
        lock.read_text(encoding="utf-8"),
        cast(dict[str, str], default_environment()),
    )
    messages = compare(expected, installed())
    for message in messages:
        sys.stdout.write(f"{message}\n")
    if messages:
        return 1
    sys.stdout.write(f"OK {len(expected)} distributions match {lock.name}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
