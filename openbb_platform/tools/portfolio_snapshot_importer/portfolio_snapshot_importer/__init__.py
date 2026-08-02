"""Portfolio snapshot importer — read-only ingest of dated broker CSVs.

Two backends (#1744):

- :class:`SqlitePortfolioStore` — user-local, offline fallback.
- :class:`MySqlPortfolioStore` — canonical (``openbb_fmp_cache_test.pi_snapshot``
  + ``pi_position``).

Consumers depend on the :class:`PortfolioStore` Protocol, not either
backend directly. Use :func:`get_default_store` to pick the right
backend per environment.

See ``docs/superpowers/specs/2026-07-18-portfolio-snapshot-importer-design.md``
+ ``docs/superpowers/specs/2026-08-02-mysql-positions-store-design.md``
for the full spec + #1744 decision record.
"""

from portfolio_snapshot_importer.basket_bridge import (
    redact_basket_preview,
    snapshot_to_basket,
    write_basket_json,
)
from portfolio_snapshot_importer.filename import (
    FilenameParseError,
    parse_fidelity_filename,
)
from portfolio_snapshot_importer.ingest import (
    IngestReport,
    IngestResult,
    import_file,
    import_files,
    import_folder,
)
from portfolio_snapshot_importer.store import (
    DEFAULT_SQLITE_PATH,
    PortfolioStore,
    SqlitePortfolioStore,
    get_default_store,
)

__all__ = [
    "FilenameParseError",
    "parse_fidelity_filename",
    "IngestReport",
    "IngestResult",
    "import_file",
    "import_files",
    "import_folder",
    "redact_basket_preview",
    "snapshot_to_basket",
    "write_basket_json",
    "PortfolioStore",
    "SqlitePortfolioStore",
    "DEFAULT_SQLITE_PATH",
    "get_default_store",
]

__version__ = "0.2.0"
