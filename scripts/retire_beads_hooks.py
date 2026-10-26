"""Retire the Beads Git hook integration from a checkout (#2235).

Beads (``bd``) is no longer this repository's tracker, but checkouts set up
with ``bd hooks install`` still carry ``core.hooksPath`` pointing at
``.beads/hooks`` or Beads sections inside ``.git/hooks``. Either way every
commit runs ``bd`` and may rewrite ``.beads/issues.jsonl``. The setting also
makes ``pre-commit install`` refuse to install the supported hooks.

Usage::

    python scripts/retire_beads_hooks.py          # migrate (idempotent)
    python scripts/retire_beads_hooks.py --check  # exit 1 if Beads hooks remain

Migration keeps any non-Beads lines: they move into the default hooks
directory. It never overwrites an existing hook there.
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

BEADS_SECTION = re.compile(
    r"^# --- BEGIN BEADS INTEGRATION[^\n]*\n.*?^# --- END BEADS INTEGRATION[^\n]*(?:\n|$)",
    re.MULTILINE | re.DOTALL,
)
RETIRED_STUB = re.compile(r"^# Retired Beads [\w-]+ hook \(#2235\)", re.MULTILINE)


class MigrationConflict(RuntimeError):
    """A hook to preserve would overwrite an existing default hook."""


@dataclass
class _Plan:
    writes: dict[Path, str] = field(default_factory=dict)
    deletes: list[Path] = field(default_factory=list)
    unset_hooks_path: bool = False


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    # Fixed executable; arguments are passed without a shell.
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=check,
    )


def _hooks_dir(repo: Path) -> Path:
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common.stdout.strip()) / "hooks"


def _beads_hooks_path(repo: Path) -> Path | None:
    """Return the configured hooksPath when it is a Beads hooks directory."""
    result = _git(repo, "config", "--get", "core.hooksPath", check=False)
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = repo / path
    return path if ".beads" in path.parts else None


def _read(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    path.chmod(0o755)


def _hooks(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        p for p in directory.iterdir() if p.is_file() and p.suffix != ".sample"
    )


def strip_beads(text: str) -> str | None:
    """Return ``text`` without Beads sections, or None if nothing else remains."""
    remainder = BEADS_SECTION.sub("", text)
    meaningful = [
        line
        for line in remainder.splitlines()
        if line.strip() and not line.startswith("#!")
    ]
    return remainder if meaningful else None


def is_retired_stub(text: str) -> bool:
    """Return True for an unmodified retired ``.beads/hooks`` stub."""
    if not RETIRED_STUB.search(text):
        return False
    return all(
        not line.strip() or line.startswith(("#", "echo ", "exit 0"))
        for line in text.splitlines()
    )


def find_problems(repo: Path) -> list[str]:
    """Return every remaining way this checkout would run Beads hooks."""
    problems = []
    if _beads_hooks_path(repo) is not None:
        problems.append("core.hooksPath points at the retired Beads hooks directory")
    for hook in _hooks(_hooks_dir(repo)):
        text = _read(hook)
        if BEADS_SECTION.search(text):
            problems.append(f"{hook.name}: contains the Beads integration section")
        elif is_retired_stub(text):
            problems.append(f"{hook.name}: is a retired Beads stub")
    return problems


def _plan(repo: Path) -> _Plan:
    plan = _Plan()
    hooks_dir = _hooks_dir(repo)
    for hook in _hooks(hooks_dir):
        text = _read(hook)
        if is_retired_stub(text):
            plan.deletes.append(hook)
            continue
        if not BEADS_SECTION.search(text):
            continue
        kept = strip_beads(text)
        if kept is None:
            plan.deletes.append(hook)
        else:
            plan.writes[hook] = kept

    beads_dir = _beads_hooks_path(repo)
    if beads_dir is None:
        return plan
    plan.unset_hooks_path = True
    conflicts = []
    for hook in _hooks(beads_dir):
        # A retired stub is Beads-owned; copying it would re-add the warning.
        text = _read(hook)
        kept = None if is_retired_stub(text) else strip_beads(text)
        if kept is None:
            continue
        target = hooks_dir / hook.name
        if (target.exists() and target not in plan.deletes) or target in plan.writes:
            conflicts.append(hook.name)
            continue
        plan.writes[target] = kept
    if conflicts:
        raise MigrationConflict(
            "non-Beads content in .beads/hooks would overwrite existing default "
            f"hooks: {', '.join(conflicts)}; merge them by hand, then re-run"
        )
    return plan


def migrate(repo: Path) -> list[str]:
    """Remove Beads hooks from ``repo``; return the actions taken."""
    plan = _plan(repo)
    actions = []
    for path in plan.deletes:
        path.unlink()
        actions.append(f"removed {path.name} (Beads-only hook or retired stub)")
    for path, text in plan.writes.items():
        _write(path, text)
        actions.append(f"wrote {path.name} without the Beads section")
    if plan.unset_hooks_path:
        _git(repo, "config", "--unset-all", "core.hooksPath")
        actions.append("unset core.hooksPath")
    return actions


def main(argv: list[str] | None = None) -> int:
    """Check for or remove Beads hooks in the current checkout."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report only")
    args = parser.parse_args(argv)
    repo = Path.cwd()

    if args.check:
        problems = find_problems(repo)
        for problem in problems:
            sys.stdout.write(f"{problem}\n")
        if problems:
            sys.stdout.write("Run python scripts/retire_beads_hooks.py to fix.\n")
            return 1
        sys.stdout.write("No Beads hooks are active.\n")
        return 0

    try:
        actions = migrate(repo)
    except MigrationConflict as error:
        sys.stderr.write(f"{error}\n")
        return 2
    for action in actions or ["nothing to do; no Beads hooks are active"]:
        sys.stdout.write(f"{action}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
