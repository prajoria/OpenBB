# quant_scraper/scrape_quant_strategies.py — Spec

| | |
|---|---|
| **Category** | Infra utility |
| **Path** | `Tools/quant_scraper/scrape_quant_strategies.py` |
| **Config** | `Tools/quant_scraper/config.toml` |
| **Writes** | cloned GitHub repos on disk |

## Purpose

Scrape the `awesome-quant` README and clone every GitHub repo it links to, into
a target directory. A bulk acquisition helper for building a local library of
quant-strategy reference repos.

## Clone target resolution order

1. `--target DIR` CLI flag
2. `QUANT_REPO_PATH` from the repo-root `.env`
3. `clone.target_dir` in `config.toml`

## How it works

1. Fetch the README markdown (`urllib`, descriptive User-Agent).
2. Extract `github.com/<owner>/<repo>` links with a strict 2-segment regex,
   filtering reserved owners (`sponsors`, `topics`, `collections`, ...) and
   reserved second segments (`blob`, `tree`, `raw`, `releases`, `wiki`,
   `issues`, `pull`).
3. Clone each repo concurrently (`concurrent.futures` + `git` subprocess).

## CLI

```
python Tools/quant_scraper/scrape_quant_strategies.py [--target DIR] [...]
```

| Flag | Meaning |
|------|---------|
| `--target` | clone destination (highest precedence) |

## Config — `config.toml`

TOML loaded via `tomllib` (3.11+) / `tomli` fallback; provides
`clone.target_dir` and related settings. Missing file -> empty config.

## Notes

- Full spec referenced by the script docstring:
  `docs/Tools/Quant-Strategies-scrape.md`.
- Stdlib-only HTTP (`urllib.request`) — no `requests`/`aiohttp` dependency.
- Skips non-repo links defensively to avoid cloning org/owner pages.
