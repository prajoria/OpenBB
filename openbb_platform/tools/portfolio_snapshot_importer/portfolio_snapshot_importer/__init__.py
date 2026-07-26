"""Portfolio snapshot importer — read-only ingest of dated broker CSVs into
an append-only SQLite history store.

See ``docs/superpowers/specs/2026-07-18-portfolio-snapshot-importer-design.md``
for the full spec. This v1 implements the Fidelity happy path only.
"""

from portfolio_snapshot_importer.basket_bridge import (
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
from portfolio_snapshot_importer.store import PortfolioStore

__all__ = [
    "FilenameParseError",
    "parse_fidelity_filename",
    "IngestReport",
    "IngestResult",
    "import_file",
    "import_files",
    "import_folder",
    "snapshot_to_basket",
    "write_basket_json",
    "PortfolioStore",
]

__version__ = "0.1.0"
