"""Scrape the awesome-quant README and clone every GitHub repo it links to.

Clone target resolution order:
1. ``--target DIR`` CLI flag
2. ``QUANT_REPO_PATH`` from the repo-root ``.env``
3. ``clone.target_dir`` in ``config.toml``

See ``docs/Tools/Quant-Strategies-scrape.md`` for the full spec.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

# github.com/<owner>/<repo>  — capture exactly two path segments.
_REPO_RE = re.compile(
    r"https?://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)", re.IGNORECASE
)
# Owner-level paths that are never repos.
_RESERVED_OWNERS = {"sponsors", "topics", "collections", "marketplace", "settings"}
# Second segments that mean "not a plain repo root".
_RESERVED_SECOND = {"blob", "tree", "raw", "releases", "wiki", "issues", "pull"}


def load_config(config_path: Path) -> dict:
    """Load the TOML config, returning an empty dict if it is missing."""
    if not config_path.exists():
        return {}
    with config_path.open("rb") as fh:
        return tomllib.load(fh)


def load_env_path(repo_root: Path) -> str | None:
    """Return QUANT_REPO_PATH from the environment or repo-root .env."""
    val = os.environ.get("QUANT_REPO_PATH")
    if val:
        return val
    env_file = repo_root / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "QUANT_REPO_PATH":
            return value.strip().strip('"').strip("'")
    return None


def fetch_readme(url: str) -> str:
    """Fetch the README markdown text."""
    req = urllib.request.Request(url, headers={"User-Agent": "quant-scraper"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return resp.read().decode("utf-8", errors="replace")


def extract_slugs(markdown: str) -> list[str]:
    """Extract unique ``owner/repo`` slugs from README markdown."""
    seen: dict[str, None] = {}
    for owner, repo in _REPO_RE.findall(markdown):
        if owner.lower() in _RESERVED_OWNERS:
            continue
        repo = repo[:-4] if repo.lower().endswith(".git") else repo
        if repo.lower() in _RESERVED_SECOND:
            continue
        slug = f"{owner}/{repo}"
        seen.setdefault(slug, None)
    return list(seen)


def apply_filters(
    slugs: list[str], exclude: list[str], include_owners: list[str]
) -> list[str]:
    """Drop excluded slugs and, if set, keep only allowed owners."""
    exclude_l = [e.lower() for e in exclude]
    include_l = [o.lower() for o in include_owners]
    out = []
    for slug in slugs:
        sl = slug.lower()
        if any(e in sl for e in exclude_l):
            continue
        if include_l and slug.split("/")[0].lower() not in include_l:
            continue
        out.append(slug)
    return out


def plan_action(slug: str, target_dir: Path, update_existing: bool) -> tuple[str, Path]:
    """Decide clone/pull/skip for a slug and return (action, local_dir)."""
    owner, repo = slug.split("/", 1)
    local = target_dir / f"{owner}__{repo}"
    if not local.exists():
        return "clone", local
    if (local / ".git").exists():
        return ("pull", local) if update_existing else ("skip", local)
    return "failed", local  # exists but not a git repo


def run_git(action: str, slug: str, local: Path, shallow: bool) -> tuple[str, str]:
    """Execute the git command for a planned action. Returns (status, detail)."""
    if action == "skip":
        return "skipped", "exists"
    if action == "failed":
        return "failed", "destination exists and is not a git repo"
    url = f"https://github.com/{slug}.git"
    if action == "clone":
        cmd = ["git", "clone"]
        if shallow:
            cmd += ["--depth", "1"]
        cmd += [url, str(local)]
    else:  # pull
        cmd = ["git", "-C", str(local), "pull", "--ff-only"]
    proc = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    if proc.returncode != 0:
        return "failed", (proc.stderr or proc.stdout).strip()[:500]
    return ("cloned" if action == "clone" else "updated"), "ok"


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    p.add_argument("--config", type=Path, default=here / "config.toml")
    p.add_argument("--target", type=Path, default=None)
    p.add_argument("--jobs", type=int, default=None)
    p.add_argument("--no-update", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def resolve_target(args: argparse.Namespace, cfg: dict, repo_root: Path) -> Path | None:
    if args.target:
        return args.target
    env_path = load_env_path(repo_root)
    if env_path:
        return Path(env_path)
    fallback = (cfg.get("clone") or {}).get("target_dir") or ""
    return Path(fallback) if fallback else None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    repo_root = Path(__file__).resolve().parents[2]
    cfg = load_config(args.config)
    clone_cfg = cfg.get("clone") or {}
    filter_cfg = cfg.get("filter") or {}
    source_cfg = cfg.get("source") or {}

    target = resolve_target(args, cfg, repo_root)
    if not target:
        print("ERROR: no clone target (set QUANT_REPO_PATH in .env or --target).")
        return 2

    readme_url = source_cfg.get("readme_url")
    if not readme_url:
        print("ERROR: source.readme_url missing from config.")
        return 2

    shallow = bool(clone_cfg.get("shallow", True))
    update_existing = bool(clone_cfg.get("update_existing", True)) and not args.no_update
    jobs = args.jobs or int(clone_cfg.get("parallelism", 8))

    print(f"Fetching README: {readme_url}")
    try:
        markdown = fetch_readme(readme_url)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: failed to fetch README: {exc}")
        return 2

    slugs = apply_filters(
        extract_slugs(markdown),
        list(filter_cfg.get("exclude", [])),
        list(filter_cfg.get("include_owners", [])),
    )
    print(f"Found {len(slugs)} unique repos. Target: {target}")

    plans = [(slug, *plan_action(slug, target, update_existing)) for slug in slugs]

    if args.dry_run:
        from collections import Counter

        counts = Counter(action for _, action, _ in plans)
        for slug, action, local in plans:
            print(f"  [{action:6}] {slug} -> {local.name}")
        print(f"DRY-RUN summary: {dict(counts)}")
        return 0

    target.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}

    def work(item):
        slug, action, local = item
        status, detail = run_git(action, slug, local, shallow)
        return slug, {"action": action, "status": status, "detail": detail}

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        for slug, res in ex.map(work, plans):
            results[slug] = res
            print(f"  [{res['status']:7}] {slug}")

    from collections import Counter

    summary = Counter(r["status"] for r in results.values())
    state = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "target": str(target),
        "summary": dict(summary),
        "repos": results,
    }
    (target / ".scrape_state.json").write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )
    print(f"Summary: {dict(summary)}")
    return 1 if summary.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
