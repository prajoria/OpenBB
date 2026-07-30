# openbb_platform/tools/

Canonical home for portfolio-adjacent installable tools in this fork.

Each sub-directory is an independent Python package with its own `pyproject.toml`. There is no coupling between them — install what you need.

## Index

| Package | Purpose | Install | Data location |
|---|---|---|---|
| [`portfolio_export/`](portfolio_export/README.md) | Playwright-based session recorder for broker portals | `pip install -e openbb_platform/tools/portfolio_export` | Recordings + exports live **outside the repo** at `H:\masterswork\browser_exports\` and `H:\masterswork\browser_recordings\` (enforced by `portfolio_export.config._validate_outside_repo`) |
| [`portfolio_snapshot_importer/`](portfolio_snapshot_importer/README.md) | Read-only Fidelity CSV → SQLite ingest with append-only history + basket bridge | `pip install -e openbb_platform/tools/portfolio_snapshot_importer` | User-local: `~/.portfolio_importer/positions.db` |
| [`scrape_record/`](scrape_record/README.md) | Offline snapshot framework (Yahoo options / bond-ETF / etc.) — record once, replay everywhere | `pip install -e openbb_platform/tools/scrape_record` | User-local: `~/.scrape_record/snapshots.db` |
| [`portfolio_utils/`](portfolio_utils/README.md) | Portfolio-adjacent ad-hoc utilities: brokerage import, ETF/13F ingest, quant-strategy scraper | `pip install -e openbb_platform/tools/portfolio_utils` | Per-script user paths |

## When to use each vs. the notebook stack

- **`portfolio_export`** — when you need to *capture* a broker session so it can be replayed offline. The notebooks consume the resulting exports.
- **`portfolio_snapshot_importer`** — when you have a Fidelity Positions CSV and want it in the user-local SQLite so the notebooks can query it. Read-only from the perspective of downstream code.
- **`scrape_record`** — when you need to hit a public site once (Yahoo, macrotrends, …) and cache the JSON so notebook runs are deterministic and reproducible.
- **`portfolio_utils`** — one-off scripts, batch CLIs, and the quant-strategy scraper. Not routinely called from notebooks.

## Security & data-location rules

Enforced by CLAUDE.md § "Sensitive data — brokerage exports & credentials" and § "Notebook local sandbox":

1. Brokerage exports NEVER live under the repo path — always outside (`H:\masterswork\browser_exports\`).
2. Credentials NEVER appear in code, recordings, or chat. Login is manual-in-browser.
3. Persistent Chrome profile at `C:\Users\daaji\.portfolio_export\chrome_profile\` — never committed.
4. `notebooks_local/` sandbox is the only place personal-data notebook runs happen. The tracked `notebooks/` tree stays clean.

## History

- **2026-07-30 (gh-1628)** — Reconciled top-level `Tools/` into `openbb_platform/tools/portfolio_utils/` and consolidated this README. `Tools/` no longer exists.
