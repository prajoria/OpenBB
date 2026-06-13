# Quant-Strategies Scraper — Design Spec

**Status:** Draft
**Date:** 2026-06-02
**Author:** (you)

## 1. Purpose

A local utility that reads the [awesome-quant](https://github.com/wilsonfreitas/awesome-quant)
README, extracts every GitHub repository link, and clones all of them into a
pre-configured local directory. The goal is to keep the full set of quant
"ideas"/reference projects available locally for browsing and inspiration.

The **cloned repos are not part of the OpenBB repo** — they live in a
gitignored directory as plain working copies (no git submodule wiring). The
scraper tool *code* is tracked in the OpenBB repo; the *clones* are not.

The clone target directory is read from the **`QUANT_REPO_PATH` environment
variable** in the repo-root `.env` file:

```
QUANT_REPO_PATH=I:\masterswork\git\OpenBB\quant_repos
```

This path is inside the repo, so it **must be gitignored** (see §9).

## 2. Decisions (locked)

| Decision | Choice |
|---|---|
| How clones relate to git | **Plain clones**, gitignored (no submodules) |
| What to clone | **Everything** in the README (every GitHub repo link), with an exclude list |
| Tool language/location | **Python script** in the OpenBB repo, run via `.venv_win` |
| Config format | **TOML** |
| Re-run behavior | **Update existing** (`git pull`) + clone missing |
| Clone depth / concurrency | **Shallow** (`--depth 1`) + **parallel** (thread pool) |
| Clone target source | **`QUANT_REPO_PATH`** env var from repo-root `.env` |

## 3. Layout

```
I:\masterswork\git\OpenBB\
└── tools\quant_scraper\
    ├── scrape_quant_strategies.py   # the script (tracked)
    ├── config.toml                  # config with defaults (tracked)
    └── README.md                    # usage docs (tracked)

I:\masterswork\git\OpenBB\quant_repos\        # clone target from QUANT_REPO_PATH (gitignored)
    ├── <owner>__<repo>\             # one dir per cloned repo
    ├── ...
    └── .scrape_state.json           # run log / per-repo status (gitignored)
```

Clones default to the directory named by **`QUANT_REPO_PATH`** in the repo-root
`.env`. Because this lives inside the repo it is gitignored so hundreds of repos
never get committed.

## 4. Configuration (`config.toml`)

```toml
[source]
# Raw markdown URL of the awesome-quant README.
readme_url = "https://raw.githubusercontent.com/wilsonfreitas/awesome-quant/master/README.md"

[clone]
# Clone target is read from the QUANT_REPO_PATH env var in the repo-root .env.
# This key is an optional fallback used only if QUANT_REPO_PATH is unset.
target_dir = ""
shallow = true          # git clone --depth 1
update_existing = true  # git pull on dirs that already exist; else clone
parallelism = 8         # number of concurrent git workers

[filter]
# Owner/repo slugs to skip (case-insensitive). Substring or exact match.
exclude = [
  # "owner/repo",
]
# If non-empty, ONLY clone repos whose owner is in this list (optional allowlist).
include_owners = []
```

**Target directory resolution order:**
1. `--target DIR` CLI flag (highest priority)
2. `QUANT_REPO_PATH` from the repo-root `.env`
3. `clone.target_dir` in `config.toml` (fallback)

If none resolve to a path, abort with a clear error. The directory is created if
missing. The `.env` is loaded with `python-dotenv` (already a repo dependency).

## 5. Behavior / Data Flow

1. **Fetch README** — GET `source.readme_url` (stdlib `urllib` or `requests`).
   Fail clearly if the fetch errors (network/HTTP).
2. **Parse links** — extract all `https://github.com/<owner>/<repo>` URLs from
   the markdown.
   - Normalize: strip trailing `/`, `.git`, `#anchors`, `?query`.
   - Keep only `<owner>/<repo>` form (2 path segments). Drop links to
     `github.com/<owner>` (no repo), `/blob/`, `/tree/`, gists, topics, etc.
   - Deduplicate the resulting slug set.
3. **Apply filters** — drop any slug matching `filter.exclude`; if
   `include_owners` is non-empty, keep only those owners.
4. **Plan** — for each slug compute local dir `<owner>__<repo>`:
   - dir missing → action `clone`
   - dir exists + `update_existing` → action `pull`
   - dir exists + not `update_existing` → action `skip`
5. **Execute (parallel)** — thread pool of `parallelism` workers running:
   - clone: `git clone --depth 1 https://github.com/<owner>/<repo>.git <dir>`
     (omit `--depth 1` if `shallow=false`)
   - pull:  `git -C <dir> pull --ff-only`
6. **Report** — print a summary (`cloned`, `updated`, `skipped`, `failed`) and
   write per-repo status to `.scrape_state.json` in the target dir.

## 6. Error Handling

- **README fetch failure** → abort with a clear message and non-zero exit.
- **Per-repo git failure** (auth, deleted repo, network) → record as `failed`
  with the git stderr, continue with the rest. Never abort the whole run for one
  repo.
- **Existing non-git dir** at a target path → record `failed` (don't overwrite).
- **Re-runnable / idempotent** — safe to run repeatedly; updates existing clones
  and fills in any missing/failed ones.
- Final exit code is non-zero if any repo failed (so it's CI/automation friendly).

## 7. CLI

```bash
.venv_win\Scripts\python.exe tools\quant_scraper\scrape_quant_strategies.py [options]
```

| Option | Effect |
|---|---|
| `--config PATH` | Use a non-default config file (default: alongside the script) |
| `--dry-run` | Parse + plan + print actions, but run no git commands |
| `--target DIR` | Override the clone target dir for this run (beats `QUANT_REPO_PATH`) |
| `--jobs N` | Override `clone.parallelism` |
| `--no-update` | Override to skip existing dirs instead of pulling |

## 8. Dependencies

- Python 3.10+ via `.venv_win`.
- `git` available on PATH.
- TOML reading via stdlib `tomllib` (3.11+) or `tomli` fallback.
- `.env` reading via `python-dotenv` (already a repo dependency) for
  `QUANT_REPO_PATH`.
- README fetch via stdlib `urllib.request` (no `requests` requirement).

## 9. Git Hygiene

Add to the OpenBB repo `.gitignore`:

```
# Local quant-strategies clones (managed by tools/quant_scraper, QUANT_REPO_PATH)
/quant_repos/
**/.scrape_state.json
```

`.env` (which holds `QUANT_REPO_PATH`) is already gitignored. If `QUANT_REPO_PATH`
is pointed elsewhere, ensure that path is gitignored too.

## 10. Testing

- **Unit (no network):**
  - link extraction from a sample README markdown fixture (valid repos,
    `/blob/`, `/tree/`, owner-only links, dupes, `.git` suffixes).
  - filter application (exclude / include_owners).
  - planning logic (clone vs pull vs skip given a fake filesystem).
- **Integration (opt-in, network):** clone a tiny known repo into a temp dir,
  re-run to confirm pull/idempotency.
- `--dry-run` used as a smoke test that prints the full plan without side effects.

## 11. Out of Scope (YAGNI)

- Git submodule registration.
- Two-phase select-then-clone manifest UI.
- Non-GitHub hosts (GitLab/Bitbucket links in the README are ignored for now).
- Scheduling/automation (run manually; cron/Task Scheduler is the user's choice).
