"""Make all .pth files in .venv_win site-packages portable (relative to site-packages dir).

Editable installs leave absolute paths in .pth files (e.g.
``H:/masterswork/git/OpenBBTechnical/openbb_platform/extensions/techtrade``).
Move the repo to a new drive / user / machine and every editable install breaks.

Python's ``site`` module joins each line in a .pth file with the containing site-packages
directory when the line is a relative path, so we can repoint every line to its repo-
relative form. The venv at ``<repo>/.venv_win`` has site-packages at
``<repo>/.venv_win/Lib/site-packages``, four levels below the repo root, so a target like
``<repo>/openbb_platform/extensions/techtrade`` becomes
``../../../openbb_platform/extensions/techtrade`` from site-packages.

Idempotent: lines already relative are left alone. Only paths inside the repo root are
rewritten -- anything pointing outside the repo (a system install, another project) is
preserved verbatim.

Usage:
    .venv_win/Scripts/python.exe Tools/make_venv_portable.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    venv = repo_root / ".venv_win"
    site_packages = venv / "Lib" / "site-packages"
    if not site_packages.is_dir():
        print(f"error: site-packages not found at {site_packages}", file=sys.stderr)
        return 1

    rewritten = 0
    skipped_outside_repo: list[str] = []
    repo_root_str = str(repo_root).replace("\\", "/")

    for pth in sorted(site_packages.glob("*.pth")):
        text = pth.read_text(encoding="utf-8")
        original_lines = text.splitlines()
        new_lines: list[str] = []
        changed = False
        for line in original_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "import ")):
                new_lines.append(line)
                continue
            normalized = stripped.replace("\\", "/")
            # Detect absolute Windows path (DRIVE:) or POSIX absolute path
            is_absolute = (
                (len(normalized) >= 3 and normalized[1] == ":" and normalized[2] == "/")
                or normalized.startswith("/")
            )
            if not is_absolute:
                new_lines.append(line)  # already relative; leave alone
                continue
            # Build a Path resolved to the same drive/case (case-insensitive on Windows).
            try:
                target = Path(stripped).resolve()
            except OSError:
                new_lines.append(line)
                continue
            try:
                relative_to_site = os.path.relpath(target, site_packages)
            except ValueError:
                # Different drive entirely -- e.g. C:\ from H:\. Try string-substitution:
                # any of D:/ , H:/ , etc., that points into <drive>:/masterswork/git/OpenBBTechnical/
                # is fixed by mapping the prefix to ``repo_root``.
                low = normalized.lower()
                if "masterswork/git/openbbtechnical/" in low:
                    suffix = low.split("masterswork/git/openbbtechnical/", 1)[1]
                    candidate = (repo_root / suffix).resolve()
                    if candidate.exists():
                        relative_to_site = os.path.relpath(candidate, site_packages)
                    else:
                        skipped_outside_repo.append(line)
                        new_lines.append(line)
                        continue
                else:
                    skipped_outside_repo.append(line)
                    new_lines.append(line)
                    continue
            # Only rewrite if the resolved target is inside the repo root.
            target_str = (site_packages / relative_to_site).resolve()
            try:
                target_str.relative_to(repo_root)
            except ValueError:
                # Outside the repo -- a system install or another project; keep as is.
                if target.exists():
                    new_lines.append(line)
                    continue
                # Outside the repo AND missing -- it's an orphaned absolute path; leave it
                # to surface in install logs rather than silently rewriting somewhere wrong.
                skipped_outside_repo.append(line)
                new_lines.append(line)
                continue
            relative_posix = relative_to_site.replace("\\", "/")
            new_lines.append(relative_posix)
            changed = True

        if changed:
            pth.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            rewritten += 1
            print(f"rewrote: {pth.name}")

    print(f"\ndone. rewrote {rewritten} .pth file(s).")
    if skipped_outside_repo:
        print(
            f"skipped {len(skipped_outside_repo)} line(s) pointing outside the repo "
            "or to missing absolute paths."
        )
    print(f"repo_root used: {repo_root_str}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
