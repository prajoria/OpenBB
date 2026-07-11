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

# Bound on how long any single git subprocess (clone or pull) may run.
# Generous for shallow clones of typical awesome-quant repos (usually
# under a minute) but small enough to catch a truly-stuck subprocess
# waiting on network, credential prompts, or local hooks (bd-1uie).
GIT_TIMEOUT_SECONDS = 600  # 10 minutes


def _reject_dash_prefixed_path(source: str, value: str | None) -> None:
    """Reject paths beginning with ``-`` up front (bd-1uie / bd-55mp).

    Git and other Unix tools treat argv elements starting with ``-`` as
    option flags. Even with ``--`` separators in the git argv, a target
    path from operator config like ``-evil`` is a signal of intentional
    tampering (or a typo) that should surface as a loud error rather
    than be silently coerced.
    """
    if value is None:
        return
    text = str(value).strip()
    if text.startswith("-"):
        raise ValueError(
            f"quant-scraper target path from {source} must not start with a "
            f"dash (would be interpreted as a git flag): {value!r}"
        )


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
        # Insert ``--`` before positional args (url + destination) so a
        # path starting with ``-`` cannot be interpreted as a git flag
        # (bd-1uie / bd-55mp). ``resolve_target`` also rejects dash-
        # prefixed paths at CLI-parse time — this is defense in depth.
        cmd += ["--", url, str(local)]
    else:  # pull
        # ``-C`` accepts its own path operand cleanly, but adding ``--``
        # after the subcommand locks in that any future refactor
        # introducing positional args stays safe.
        cmd = ["git", "-C", str(local), "pull", "--ff-only", "--"]
    # ``timeout=`` bounds the wait so a hung git (network stall, local
    # hook, prompt for creds) doesn't freeze the executor. 600s = 10 min
    # is generous for shallow clones of typical awesome-quant repos but
    # small enough to catch a truly-stuck subprocess. bd-1uie flags this.
    # ``subprocess.TimeoutExpired`` is caught + mapped to the same
    # ``('failed', <detail>)`` contract as returncode-based failures so
    # a single stalled repo doesn't abort the batch mid-flight (would
    # otherwise skip the ``.scrape_state.json`` write and lose completed
    # per-repo statuses — flagged by Round-1 review).
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return "failed", f"timed out after {GIT_TIMEOUT_SECONDS}s"
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
    """Resolve the clone target dir from CLI / env / config, in that order.

    All three sources are validated to reject paths starting with ``-``
    which would be interpreted as git flags on the ``git clone``
    positional argument (bd-1uie / bd-55mp).
    """
    if args.target:
        _reject_dash_prefixed_path("--target CLI arg", str(args.target))
        return args.target
    env_path = load_env_path(repo_root)
    if env_path:
        _reject_dash_prefixed_path("QUANT_REPO_PATH env / .env", env_path)
        return Path(env_path)
    fallback = (cfg.get("clone") or {}).get("target_dir") or ""
    if fallback:
        _reject_dash_prefixed_path("config.toml clone.target_dir", fallback)
        return Path(fallback)
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    repo_root = Path(__file__).resolve().parents[2]
    cfg = load_config(args.config)
    clone_cfg = cfg.get("clone") or {}
    filter_cfg = cfg.get("filter") or {}
    source_cfg = cfg.get("source") or {}

    try:
        target = resolve_target(args, cfg, repo_root)
    except ValueError as exc:
        # Dash-prefixed target path from any of the 3 sources — surface
        # cleanly instead of dumping a traceback. Matches the existing
        # config-error return-2 contract below (bd-1uie / bd-55mp).
        print(f"ERROR: {exc}")
        return 2
    if not target:
        print("ERROR: no clone target (set QUANT_REPO_PATH in .env or --target).")
        return 2

    readme_url = source_cfg.get("readme_url")
    if not readme_url:
        print("ERROR: source.readme_url missing from config.")
        return 2

    shallow = bool(clone_cfg.get("shallow", True))
    update_existing = (
        bool(clone_cfg.get("update_existing", True)) and not args.no_update
    )
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
