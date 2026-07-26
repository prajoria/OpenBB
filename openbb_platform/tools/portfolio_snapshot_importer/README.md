# portfolio-snapshot-importer

Read-only ingest of dated broker portfolio-positions CSVs into an
**append-only** SQLite history store. v1 supports the Fidelity happy path
(`Portfolio_Positions_<Mon>-<DD>-<YYYY>_<user_id>.csv`).

Full design: `docs/superpowers/specs/2026-07-18-portfolio-snapshot-importer-design.md`.

## Install

```bash
# From repo root, using .venv_portfolio
.venv_portfolio\Scripts\python.exe -m pip install -e openbb_platform/tools/portfolio_snapshot_importer
```

## Usage

```bash
# Import specific files
portfolio-snapshot-import import path/to/Portfolio_Positions_Jul-18-2026_alice.csv

# Recursive folder import
portfolio-snapshot-import import --folder H:\masterswork\browser_exports\

# List what's been imported
portfolio-snapshot-import list

# Show positions in a specific snapshot
portfolio-snapshot-import show <snapshot_id>
```

The default database lives at `~/.portfolio_importer/positions.db`. That
path is user-local and **must not** sit under the git repo checkout — the
CLI validates this at every call. To use a different DB, pass `--db`.

## Guarantees

- **Idempotent**: importing the same file twice is a no-op. Idempotence
  key is `(source_sha256, user_id)`.
- **Append-only**: never `UPDATE`s or `DELETE`s positions. Corrections
  come as new snapshots on later dates.
- **Filename-only provenance**: full paths are never stored (they'd leak
  the operator home directory).

## Extension

`filename.py` currently ships a single Fidelity regex. Additional broker
loaders (Schwab, Vanguard, IBKR) will be added as sibling modules that
plug into a `LOADERS` registry — see the design spec §4 for the intended
shape.

## Security

Brokerage-data files live **outside** the repo (typically under
`H:\masterswork\browser_exports\`). This importer reads them and stores
parsed values in a **user-local** SQLite DB (`~/.portfolio_importer/`).
Neither the input CSVs nor the DB should ever be committed. See CLAUDE.md
"Sensitive data — brokerage exports & credentials".
